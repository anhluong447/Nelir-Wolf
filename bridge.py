"""Active-project facade: preparation, extraction sync, patching and restore."""
import os
import shutil
import threading
from datetime import datetime
from typing import Optional

import config
import pipeline
from db import SCHEMA_VERSION, connect, get_meta, init_project_db, set_meta
from extractor import (WolfTLError, ensure_original_dump, get_by_path, load_json, recreate_original_from_game,
                       refresh_locks, save_json, set_by_path, sync_rows, wolftl_patch)
from project_manager import ProjectManager
from validator import check_dump, load_dump

# Game data sub-folders that WolfTL rewrites when patching.
GAME_TEXT_DIRS = ('BasicData', 'MapData')


class NoActiveProject(RuntimeError):
    pass


class ProjectContext:
    """Immutable snapshot of a project's paths (safe to hand to long-running jobs)."""

    def __init__(self, proj: dict):
        self.project_id = proj["id"]
        self.name = proj.get("name", proj["id"])
        self.project_dir = proj["dir"]
        self.dump_dir = os.path.join(self.project_dir, 'dump')
        self.original_dump_dir = os.path.join(self.project_dir, 'dump_original')
        self.db_path = os.path.join(self.project_dir, 'translation.db')
        self.game_data_path = proj.get("game_data_path", "") or ""
        self.game_path = proj.get("game_path", "") or ""


class WolfBridge:
    def __init__(self, root_dir: str = config.ROOT_DIR):
        self.root_dir = root_dir
        self.pm = ProjectManager(root_dir)
        self.ctx: Optional[ProjectContext] = None
        self._lock = threading.Lock()  # serialises patch / extraction jobs
        self.load_active_project()

    # ------------------------------------------------------------------
    # Settings passthrough
    # ------------------------------------------------------------------
    def get_setting(self, key: str, default: Optional[str] = None) -> str:
        return self.pm.get_global_setting(key, default)

    def set_setting(self, key: str, value: str):
        self.pm.set_global_setting(key, value)

    def max_line_chars(self) -> int:
        try:
            return max(0, int(self.get_setting("qa_max_line_chars")))
        except ValueError:
            return 0

    # ------------------------------------------------------------------
    # Active project
    # ------------------------------------------------------------------
    @property
    def project_id(self):
        return self.ctx.project_id if self.ctx else None

    @property
    def db_path(self):
        return self.require().db_path

    def require(self) -> ProjectContext:
        if not self.ctx:
            raise NoActiveProject("Chưa có dự án nào. Hãy tạo game mới hoặc nạp file .nel.")
        return self.ctx

    def load_active_project(self, project_id: Optional[str] = None) -> Optional[ProjectContext]:
        if project_id:
            self.pm.set_active_project_id(project_id)
        proj = self.pm.get_active_project()
        self.ctx = ProjectContext(proj) if proj else None
        if self.ctx:
            init_project_db(self.ctx.db_path)
        return self.ctx

    def prepare_active_project(self) -> dict:
        """Make the active project consistent: schema, pristine dump, rows, locks, status semantics."""
        ctx = self.require()
        report = {}
        with self._lock:
            init_project_db(ctx.db_path)
            try:
                ensure_original_dump(ctx.project_dir, ctx.db_path, ctx.game_data_path)
            except WolfTLError as e:
                report["dump_error"] = str(e)
            with connect(ctx.db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM translation_rows").fetchone()[0]
            if count == 0 and os.path.isdir(ctx.original_dump_dir):
                report["sync"] = sync_rows(ctx.db_path, ctx.original_dump_dir)
            report["locked"] = refresh_locks(ctx.db_path)
            with connect(ctx.db_path) as conn:
                version = int(get_meta(conn, "schema_version", "1"))
            if version < SCHEMA_VERSION:
                report["migration"] = pipeline.migrate_status_semantics(ctx.db_path, self.max_line_chars())
                with connect(ctx.db_path) as conn:
                    set_meta(conn, "schema_version", SCHEMA_VERSION)
        print(f"[Bridge] Project '{ctx.project_id}' ready: {report}")
        return report

    def reextract(self, from_game: bool = False) -> dict:
        """Re-sync rows from the pristine dump (or re-dump an unpatched game first)."""
        ctx = self.require()
        with self._lock:
            if from_game:
                recreate_original_from_game(ctx.project_dir, ctx.db_path, ctx.game_data_path)
            else:
                ensure_original_dump(ctx.project_dir, ctx.db_path, ctx.game_data_path)
            stats = sync_rows(ctx.db_path, ctx.original_dump_dir)
        stats["qa"] = pipeline.recheck_qa(ctx.db_path, self.max_line_chars())
        return stats

    # ------------------------------------------------------------------
    # Patching
    # ------------------------------------------------------------------
    def _check_game(self, ctx):
        if not ctx.game_data_path or not os.path.isdir(ctx.game_data_path):
            raise WolfTLError(f"Không tìm thấy thư mục Data của game: '{ctx.game_data_path}'. "
                              "Hãy cập nhật đường dẫn game của dự án.")

    def _backup_game_once(self, ctx) -> Optional[str]:
        """Copy the folders WolfTL rewrites, the first time we patch this game."""
        backup_root = os.path.join(ctx.project_dir, 'game_backup')
        if os.path.isdir(backup_root):
            return None
        tmp = backup_root + '.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        for sub in GAME_TEXT_DIRS:
            src = os.path.join(ctx.game_data_path, sub)
            if os.path.isdir(src):
                shutil.copytree(src, os.path.join(tmp, sub))
        with open(os.path.join(tmp, 'README.txt'), 'w', encoding='utf-8') as f:
            f.write(f"Backup of {ctx.game_data_path} taken {datetime.now().isoformat()} before the first patch "
                    f"by Nelir-Wolf (may already contain older patches).\n")
        os.replace(tmp, backup_root)
        return backup_root

    def _write_working_dump(self, ctx, patched_files: dict):
        """<project>/dump = copy of dump_original + patched files (WolfTL reads this)."""
        tmp = ctx.dump_dir + '.tmp'
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.copytree(ctx.original_dump_dir, tmp)
        for rel, data in patched_files.items():
            save_json(os.path.join(tmp, rel), data)
        shutil.rmtree(ctx.dump_dir, ignore_errors=True)
        os.replace(tmp, ctx.dump_dir)

    def build_patched_dump(self, ctx) -> dict:
        """Apply translations in memory on top of dump_original. Locked rows keep raw."""
        with connect(ctx.db_path) as conn:
            rows = conn.execute(
                "SELECT file, path, raw, translated, mtl, locked FROM translation_rows ORDER BY file").fetchall()
        files, mismatched, applied = {}, [], 0
        for f, p, raw, trans, mtl, locked in rows:
            if os.path.basename(f) in config.EXCLUDED_FILES:
                continue
            if f not in files:
                full = os.path.join(ctx.original_dump_dir, f)
                files[f] = load_json(full) if os.path.exists(full) else None
            data = files[f]
            if data is None:
                mismatched.append(f"{f}: file không tồn tại trong dump gốc")
                continue
            try:
                current = get_by_path(data, p)
            except Exception:
                mismatched.append(f"{f} {p}: path không tồn tại")
                continue
            if current != raw:
                mismatched.append(f"{f} {p}: dump gốc khác raw trong DB (game đã cập nhật?)")
                continue
            if trans and trans.strip():
                text = trans
            elif mtl and mtl.strip():
                text = mtl
            else:
                text = ''
            if locked or not text:
                continue
            set_by_path(data, p, text)
            applied += 1
        files = {k: v for k, v in files.items() if v is not None}
        return {"files": files, "applied": applied, "mismatched": mismatched}

    def patch_to_game(self, force: bool = False) -> dict:
        ctx = self.require()
        with self._lock:
            self._check_game(ctx)
            ensure_original_dump(ctx.project_dir, ctx.db_path, ctx.game_data_path)
            built = self.build_patched_dump(ctx)

            original_files = load_dump(ctx.original_dump_dir)
            merged = dict(original_files)
            merged.update(built["files"])
            new_errors = sorted(check_dump(merged) - check_dump(original_files))
            if new_errors and not force:
                return {"success": False, "blocked": True, "errors": new_errors[:100],
                        "message": f"Đã chặn Patch: bản dịch tạo ra {len(new_errors)} lỗi logic mới "
                                   f"(tra cứu Database / nhãn nhảy). Xem chi tiết và sửa trước khi vá."}

            backup = self._backup_game_once(ctx)
            self._write_working_dump(ctx, built["files"])
            out = wolftl_patch(ctx.game_data_path, ctx.project_dir)

        msg = f"Vá thành công {built['applied']} dòng tiếng Việt vào game."
        if built["mismatched"]:
            msg += f" Bỏ qua {len(built['mismatched'])} dòng không khớp dump gốc."
        if backup:
            msg += f" Đã sao lưu dữ liệu game vào {backup}."
        if new_errors:
            msg += f" (Bỏ qua {len(new_errors)} cảnh báo logic theo yêu cầu.)"
        return {"success": True, "message": msg, "applied": built["applied"],
                "mismatched": built["mismatched"][:100], "details": out}

    def restore_original_text(self) -> dict:
        """Write the pristine Japanese dump back into the game with WolfTL."""
        ctx = self.require()
        with self._lock:
            self._check_game(ctx)
            ensure_original_dump(ctx.project_dir, ctx.db_path, ctx.game_data_path)
            self._write_working_dump(ctx, {})
            wolftl_patch(ctx.game_data_path, ctx.project_dir)
        return {"success": True, "message": "Đã khôi phục toàn bộ văn bản gốc tiếng Nhật vào game."}

    # ------------------------------------------------------------------
    # Glossary
    # ------------------------------------------------------------------
    def get_glossary(self) -> list:
        with connect(self.db_path) as conn:
            return [{"src": s, "dst": d, "note": n} for s, d, n in
                    conn.execute("SELECT src, dst, note FROM glossary ORDER BY src")]

    def set_glossary(self, entries: list) -> int:
        clean = {}
        for e in entries:
            src, dst = (e.get("src") or "").strip(), (e.get("dst") or "").strip()
            if src and dst:
                clean[src] = (dst, (e.get("note") or "").strip())
        with connect(self.db_path) as conn:
            conn.execute("DELETE FROM glossary")
            conn.executemany("INSERT INTO glossary (src, dst, note) VALUES (?, ?, ?)",
                             [(s, d, n) for s, (d, n) in clean.items()])
        return len(clean)
