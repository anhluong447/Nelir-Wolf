"""Projects on disk (projects/<id>/), global settings and .nel packages."""
import json
import os
import re
import shutil
import sqlite3
import tempfile
import time
import zipfile
from datetime import datetime
from typing import Any, Dict, List, Optional

import config
from db import connect, status_counts
from extractor import WolfTLError, wolftl_create_dump

LEGACY_PROJECT_ID = 'Ghoul_Goula_Compagnia'


def _slug(name: str) -> str:
    return re.sub(r'[^a-zA-Z0-9_\-]', '_', name or '').strip('_')[:60]


class ProjectManager:
    def __init__(self, root_dir: str = config.ROOT_DIR):
        self.root_dir = root_dir
        self.projects_dir = os.path.join(root_dir, 'projects')
        self.global_db_path = os.path.join(root_dir, 'global_settings.db')
        os.makedirs(self.projects_dir, exist_ok=True)
        self._init_global_db()
        self._migrate_legacy_data_once()

    # ------------------------------------------------------------------
    # Global settings
    # ------------------------------------------------------------------
    def _init_global_db(self):
        with connect(self.global_db_path) as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS global_settings (key TEXT PRIMARY KEY, value TEXT)')
            conn.executemany('INSERT OR IGNORE INTO global_settings (key, value) VALUES (?, ?)',
                             list(config.DEFAULT_SETTINGS.items()))
            conn.executemany('DELETE FROM global_settings WHERE key = ?',
                             [(k,) for k in config.OBSOLETE_SETTINGS])

    def get_global_setting(self, key: str, default: Optional[str] = None) -> str:
        with connect(self.global_db_path) as conn:
            row = conn.execute('SELECT value FROM global_settings WHERE key = ?', (key,)).fetchone()
        if row and row[0] is not None:
            return row[0]
        return default if default is not None else config.DEFAULT_SETTINGS.get(key, '')

    def set_global_setting(self, key: str, value: str):
        with connect(self.global_db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)', (key, value))

    def _migrate_legacy_data_once(self):
        """Import data from the pre-multi-project layout (root nelir_wolf.db + dump/).
        Runs once; legacy settings never overwrite current ones."""
        if self.get_global_setting('legacy_migrated', '') == '1':
            return
        legacy_db = os.path.join(self.root_dir, 'nelir_wolf.db')
        legacy_dump = os.path.join(self.root_dir, 'dump')
        if os.path.exists(legacy_db):
            try:
                with connect(legacy_db) as l_conn:
                    has = l_conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
                    s_rows = l_conn.execute("SELECT key, value FROM settings").fetchall() if has else []
                with connect(self.global_db_path) as g_conn:
                    g_conn.executemany("INSERT OR IGNORE INTO global_settings (key, value) VALUES (?, ?)", s_rows)
            except Exception as e:
                print(f"[Migration] Warning reading legacy settings: {e}")

            proj_dir = os.path.join(self.projects_dir, LEGACY_PROJECT_ID)
            if not os.path.exists(proj_dir):
                os.makedirs(proj_dir)
                shutil.copy2(legacy_db, os.path.join(proj_dir, 'translation.db'))
                if os.path.isdir(legacy_dump):
                    shutil.copytree(legacy_dump, os.path.join(proj_dir, 'dump'))
                game_folder = os.path.join(os.path.dirname(self.root_dir), LEGACY_PROJECT_ID)
                data = os.path.join(game_folder, 'Data')
                self._write_meta(proj_dir, {
                    "id": LEGACY_PROJECT_ID, "name": "Ghoul Goula Compagnia", "engine": "WOLF RPG",
                    "game_path": game_folder, "game_data_path": data if os.path.isdir(data) else game_folder,
                    "created_at": datetime.now().isoformat(), "last_modified": datetime.now().isoformat(),
                })
                if not self.get_global_setting('active_project_id'):
                    self.set_global_setting('active_project_id', LEGACY_PROJECT_ID)
                print("[Migration] Legacy project migrated to projects/")
        self.set_global_setting('legacy_migrated', '1')

    # ------------------------------------------------------------------
    # Projects
    # ------------------------------------------------------------------
    def _check_id(self, project_id: str) -> str:
        if not config.is_valid_project_id(project_id):
            raise ValueError(f"ID dự án không hợp lệ: '{project_id}'")
        return project_id

    def project_dir(self, project_id: str) -> str:
        return os.path.join(self.projects_dir, self._check_id(project_id))

    @staticmethod
    def _write_meta(proj_dir, meta):
        with open(os.path.join(proj_dir, 'project.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

    def _read_project(self, item: str, active_id: str, with_stats: bool = True) -> Optional[Dict[str, Any]]:
        if not config.is_valid_project_id(item):
            return None
        proj_dir = os.path.join(self.projects_dir, item)
        meta_file = os.path.join(proj_dir, 'project.json')
        if not os.path.isfile(meta_file):
            return None
        try:
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)
        except Exception:
            meta = {"name": item}
        meta["id"] = item  # folder name is the source of truth
        stats = {"total": 0, "completed": 0, "translated": 0, "mtl": 0, "empty": 0, "qa": 0, "locked": 0,
                 "percent": 0.0}
        db_path = os.path.join(proj_dir, 'translation.db')
        if with_stats and os.path.exists(db_path):
            try:
                with connect(db_path) as conn:
                    stats = status_counts(conn)
            except sqlite3.Error as e:
                print(f"Error reading stats for {item}: {e}")
        meta["stats"] = stats
        meta["is_active"] = item == active_id
        meta["dir"] = proj_dir
        meta["game_path_exists"] = os.path.isdir(meta.get("game_data_path", "") or "")
        return meta

    def list_projects(self) -> List[Dict[str, Any]]:
        active_id = self.get_active_project_id()
        out = []
        for item in sorted(os.listdir(self.projects_dir)):
            p = self._read_project(item, active_id)
            if p:
                out.append(p)
        return out

    def get_project(self, project_id: str, with_stats: bool = True) -> Optional[Dict[str, Any]]:
        if not config.is_valid_project_id(project_id):
            return None
        return self._read_project(project_id, self.get_active_project_id(), with_stats)

    def get_active_project_id(self) -> str:
        return self.get_global_setting('active_project_id', '')

    def set_active_project_id(self, project_id: str):
        if not os.path.isfile(os.path.join(self.project_dir(project_id), 'project.json')):
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")
        self.set_global_setting('active_project_id', project_id)

    def get_active_project(self, with_stats: bool = False) -> Optional[Dict[str, Any]]:
        proj = self.get_project(self.get_active_project_id(), with_stats)
        if proj:
            return proj
        for item in sorted(os.listdir(self.projects_dir)):
            p = self._read_project(item, '', with_stats)
            if p:
                self.set_active_project_id(p["id"])
                p["is_active"] = True
                return p
        return None

    def validate_game_path(self, game_path: str) -> Dict[str, Any]:
        """Validates a WOLF RPG game directory and finds its Data directory."""
        game_path = (game_path or '').strip().strip('"')
        if not game_path or not os.path.isdir(game_path):
            return {"valid": False, "error": f"Đường dẫn không tồn tại: {game_path}"}
        data_sub = os.path.join(game_path, 'Data')
        if os.path.isdir(data_sub):
            return {"valid": True, "game_path": game_path, "game_data_path": data_sub}
        if os.path.isdir(os.path.join(game_path, 'BasicData')):
            return {"valid": True, "game_path": os.path.dirname(game_path), "game_data_path": game_path}
        return {"valid": False,
                "error": "Không tìm thấy thư mục 'Data' (hoặc 'BasicData'). Nếu game đóng gói Data.wolf, "
                         "hãy giải nén ra thư mục Data trước."}

    def _unique_id(self, base: str) -> str:
        base = base or f"project_{int(time.time())}"
        project_id, n = base, 1
        while os.path.exists(os.path.join(self.projects_dir, project_id)):
            project_id = f"{base}_{n}"
            n += 1
        return project_id

    def create_project(self, name: str, game_path: str) -> Dict[str, Any]:
        """Creates a project and dumps the game with WolfTL. Rolls back on failure."""
        clean_name = (name or '').strip()
        if not clean_name:
            raise ValueError("Tên dự án không được để trống!")
        validation = self.validate_game_path(game_path)
        if not validation["valid"]:
            raise ValueError(validation["error"])

        project_id = self._unique_id(_slug(clean_name))
        proj_dir = os.path.join(self.projects_dir, project_id)
        os.makedirs(proj_dir)
        try:
            wolftl_create_dump(validation["game_data_path"], proj_dir)
            now = datetime.now().isoformat()
            self._write_meta(proj_dir, {
                "id": project_id, "name": clean_name, "engine": "WOLF RPG",
                "game_path": validation["game_path"], "game_data_path": validation["game_data_path"],
                "created_at": now, "last_modified": now,
            })
        except Exception:
            shutil.rmtree(proj_dir, ignore_errors=True)
            raise
        self.set_active_project_id(project_id)
        return self.get_project(project_id)

    def update_game_path(self, project_id: str, game_path: str) -> Dict[str, Any]:
        validation = self.validate_game_path(game_path)
        if not validation["valid"]:
            raise ValueError(validation["error"])
        proj = self.get_project(project_id, with_stats=False)
        if not proj:
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")
        meta = {k: v for k, v in proj.items() if k not in ("stats", "is_active", "dir", "game_path_exists")}
        meta.update(game_path=validation["game_path"], game_data_path=validation["game_data_path"],
                    last_modified=datetime.now().isoformat())
        self._write_meta(proj["dir"], meta)
        return self.get_project(project_id)

    # ------------------------------------------------------------------
    # .nel packages
    # ------------------------------------------------------------------
    def export_nel(self, project_id: str, output_path: Optional[str] = None) -> str:
        """Pack manifest.json + project.json + a consistent snapshot of translation.db."""
        proj = self.get_project(project_id)
        if not proj:
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")
        proj_dir = proj["dir"]
        db_path = os.path.join(proj_dir, 'translation.db')
        if not os.path.exists(db_path):
            raise ValueError("Không tìm thấy translation.db của dự án để xuất gói!")

        s = proj["stats"]
        manifest = {
            "app": "Nelir-Wolf", "format_version": 2, "project_id": project_id,
            "game_name": proj.get("name", project_id), "engine": proj.get("engine", "WOLF RPG"),
            "original_game_path": proj.get("game_path", ""),
            "original_game_data_path": proj.get("game_data_path", ""),
            "exported_at": datetime.now().isoformat(),
            "stats": {"total_rows": s.get("total", 0), "completed_rows": s.get("completed", 0),
                      "translated_rows": s.get("translated", 0), "mtl_rows": s.get("mtl", 0),
                      "qa_rows": s.get("qa", 0), "locked_rows": s.get("locked", 0),
                      "empty_rows": s.get("empty", 0), "completion_rate": s.get("percent", 0.0)},
        }
        if not output_path:
            output_path = os.path.join(
                self.projects_dir, f"{_slug(proj.get('name', project_id))}_{datetime.now():%Y%m%d_%H%M}.nel")

        fd, snap = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(snap)
            try:
                src.backup(dst)
            finally:
                dst.close()
                src.close()
            with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
                zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                meta_file = os.path.join(proj_dir, 'project.json')
                if os.path.exists(meta_file):
                    zf.write(meta_file, arcname='project.json')
                zf.write(snap, arcname='translation.db')
        finally:
            os.remove(snap)
        return output_path

    def import_nel(self, nel_file_path: str, override_game_path: Optional[str] = None) -> Dict[str, Any]:
        """Import a .nel package as a new project (never overwrites an existing one)."""
        if not zipfile.is_zipfile(nel_file_path):
            raise ValueError("File tải lên không phải là gói .nel hợp lệ!")
        with zipfile.ZipFile(nel_file_path, 'r') as zf:
            names = zf.namelist()
            if 'manifest.json' not in names or 'translation.db' not in names:
                raise ValueError("Gói .nel bị thiếu manifest.json hoặc translation.db!")
            manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
            game_name = str(manifest.get("game_name") or "Imported_Game")
            base_id = _slug(str(manifest.get("project_id") or "")) or _slug(game_name)
            project_id = self._unique_id(base_id)
            proj_dir = os.path.join(self.projects_dir, project_id)
            os.makedirs(proj_dir)
            try:
                with zf.open('translation.db') as src, open(os.path.join(proj_dir, 'translation.db'), 'wb') as dst:
                    shutil.copyfileobj(src, dst)
                with connect(os.path.join(proj_dir, 'translation.db')) as conn:
                    conn.execute("SELECT COUNT(*) FROM translation_rows").fetchone()
            except Exception as e:
                shutil.rmtree(proj_dir, ignore_errors=True)
                raise ValueError(f"translation.db trong gói .nel bị hỏng: {e}")

        game_path = override_game_path or manifest.get("original_game_path", "")
        val = self.validate_game_path(game_path) if game_path else {"valid": False}
        warning = ""
        if val.get("valid"):
            try:
                wolftl_create_dump(val["game_data_path"], proj_dir)
            except WolfTLError as e:
                warning = f"Không bóc tách được game: {e}"
        else:
            warning = "Chưa có đường dẫn game hợp lệ: hãy cập nhật đường dẫn game để có thể Patch."
        now = datetime.now().isoformat()
        self._write_meta(proj_dir, {
            "id": project_id, "name": game_name, "engine": manifest.get("engine", "WOLF RPG"),
            "game_path": val.get("game_path", game_path or ""),
            "game_data_path": val.get("game_data_path", ""),
            "created_at": manifest.get("exported_at", now), "last_modified": now, "imported_from_nel": True,
        })
        self.set_active_project_id(project_id)
        proj = self.get_project(project_id)
        proj["warning"] = warning
        return proj

    def delete_project(self, project_id: str) -> bool:
        proj_dir = self.project_dir(project_id)
        if project_id == self.get_active_project_id():
            raise ValueError("Không thể xóa dự án đang được kích hoạt! Hãy chuyển sang dự án khác trước.")
        if not os.path.isdir(proj_dir):
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")
        for attempt in range(3):
            try:
                shutil.rmtree(proj_dir)
                return True
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(0.3)
        return True
