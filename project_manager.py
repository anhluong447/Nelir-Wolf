import os
import json
import sqlite3
import shutil
import zipfile
import re
from datetime import datetime
from typing import Optional, List, Dict, Any

class ProjectManager:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.bin_dir = os.path.join(root_dir, 'bin')
        self.wolftl_path = os.path.join(self.bin_dir, 'WolfTL.exe')
        self.projects_dir = os.path.join(root_dir, 'projects')
        self.global_db_path = os.path.join(root_dir, 'global_settings.db')
        
        os.makedirs(self.projects_dir, exist_ok=True)
        self._init_global_db()
        self._migrate_legacy_data_if_needed()

    def _init_global_db(self):
        with sqlite3.connect(self.global_db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS global_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            ''')
            # Defaults
            default_prompt = (
                "Bạn là một chuyên gia bản địa hóa game từ tiếng Nhật sang tiếng Việt.\n"
                "YÊU CẦU BẮT BUỘC:\n"
                "1. Dịch 100% sang tiếng Việt tự nhiên, phù hợp văn phong hội thoại game. Xác định đúng chủ ngữ theo ngữ cảnh (không tự nhận là 'Tôi' khi mô tả đồ vật/kỹ năng).\n"
                "2. Giữ nguyên số dòng (ngắt bởi \\n), phân bổ câu chữ cân đối giữa các dòng, không dồn chữ làm một dòng quá dài.\n"
                "3. Giữ nguyên vẹn mã điều khiển (\\s[...], \\c[...], \\cself[...], @1, dấu ・・・, ngoặc 「」, \"\") ở đúng dòng tương ứng.\n"
                "4. Chỉ xuất duy nhất bản dịch, tuyệt đối không thêm lời chào, giải thích hay ghi chú."
            )
            conn.execute('''
                INSERT OR IGNORE INTO global_settings (key, value) VALUES
                ('active_project_id', 'Ghoul_Goula_Compagnia'),
                ('batch_size', '15'),
                ('active_provider', 'gemini'),
                ('gemini_base_url', 'https://generativelanguage.googleapis.com/v1beta/openai'),
                ('openrouter_base_url', 'https://openrouter.ai/api/v1'),
                ('kaggle_base_url', 'https://immune-passive-vegas-district.trycloudflare.com/v1'),
                ('kaggle_key', 'local'),
                ('kaggle_model', 'qwen2.5:32b'),
                ('openrouter_key', ''),
                ('openrouter_model', 'deepseek/deepseek-v4.1-flash-1017'),
                ('system_prompt', ?)
            ''', (default_prompt,))
            conn.commit()

    def get_global_setting(self, key: str, default: str = '') -> str:
        with sqlite3.connect(self.global_db_path) as conn:
            row = conn.execute('SELECT value FROM global_settings WHERE key = ?', (key,)).fetchone()
            return row[0] if row else default

    def set_global_setting(self, key: str, value: str):
        with sqlite3.connect(self.global_db_path) as conn:
            conn.execute('INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)', (key, value))
            conn.commit()

    def _migrate_legacy_data_if_needed(self):
        """Automatically migrates root nelir_wolf.db and dump/ into projects/Ghoul_Goula_Compagnia/"""
        legacy_db = os.path.join(self.root_dir, 'nelir_wolf.db')
        legacy_dump = os.path.join(self.root_dir, 'dump')
        legacy_proj_dir = os.path.join(self.projects_dir, 'Ghoul_Goula_Compagnia')

        # 1. Migrate settings from legacy_db to global_settings.db if present
        if os.path.exists(legacy_db):
            try:
                with sqlite3.connect(legacy_db) as l_conn:
                    # Check if settings table exists
                    has_settings = l_conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
                    if has_settings:
                        s_rows = l_conn.execute("SELECT key, value FROM settings").fetchall()
                        with sqlite3.connect(self.global_db_path) as g_conn:
                            for k, v in s_rows:
                                g_conn.execute("INSERT OR REPLACE INTO global_settings (key, value) VALUES (?, ?)", (k, v))
                            g_conn.commit()
            except Exception as e:
                print(f"[Migration] Warning reading legacy settings: {e}")

        # 2. Check if legacy project needs to be initialized in projects/
        if not os.path.exists(legacy_proj_dir):
            print("[Migration] Migrating legacy Ghoul_Goula_Compagnia to projects/...")
            os.makedirs(legacy_proj_dir, exist_ok=True)
            
            # Copy or move DB
            target_db = os.path.join(legacy_proj_dir, 'translation.db')
            if os.path.exists(legacy_db):
                shutil.copy2(legacy_db, target_db)
                print(f"[Migration] Copied {legacy_db} -> {target_db}")

            # Copy dump
            target_dump = os.path.join(legacy_proj_dir, 'dump')
            if os.path.exists(legacy_dump) and not os.path.exists(target_dump):
                shutil.copytree(legacy_dump, target_dump)
                print(f"[Migration] Copied {legacy_dump} -> {target_dump}")

            # Create project.json
            game_folder = os.path.join(os.path.dirname(self.root_dir), 'Ghoul_Goula_Compagnia')
            game_data_path = os.path.join(game_folder, 'Data') if os.path.exists(os.path.join(game_folder, 'Data')) else game_folder

            proj_meta = {
                "id": "Ghoul_Goula_Compagnia",
                "name": "Ghoul Goula Compagnia",
                "engine": "WOLF RPG",
                "game_path": game_folder,
                "game_data_path": game_data_path,
                "created_at": datetime.now().isoformat(),
                "last_modified": datetime.now().isoformat()
            }
            with open(os.path.join(legacy_proj_dir, 'project.json'), 'w', encoding='utf-8') as f:
                json.dump(proj_meta, f, ensure_ascii=False, indent=2)

            self.set_global_setting('active_project_id', 'Ghoul_Goula_Compagnia')
            print("[Migration] Ghoul_Goula_Compagnia migrated successfully!")

    def list_projects(self) -> List[Dict[str, Any]]:
        projects = []
        active_id = self.get_active_project_id()

        for item in os.listdir(self.projects_dir):
            proj_dir = os.path.join(self.projects_dir, item)
            if not os.path.isdir(proj_dir):
                continue
            meta_file = os.path.join(proj_dir, 'project.json')
            if not os.path.exists(meta_file):
                continue

            try:
                with open(meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            except Exception:
                meta = {"id": item, "name": item}

            # Fetch row stats from translation.db
            db_path = os.path.join(proj_dir, 'translation.db')
            stats = {"total": 0, "completed": 0, "translated": 0, "mtl": 0, "empty": 0, "percent": 0.0}
            if os.path.exists(db_path):
                try:
                    with sqlite3.connect(db_path) as conn:
                        total = conn.execute("SELECT COUNT(*) FROM translation_rows").fetchone()[0]
                        empty = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 0").fetchone()[0]
                        mtl = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 1").fetchone()[0]
                        trans = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 2").fetchone()[0]
                        completed = mtl + trans
                        pct = round((completed / total * 100), 1) if total > 0 else 0.0
                        stats = {
                            "total": total,
                            "completed": completed,
                            "translated": trans,
                            "mtl": mtl,
                            "empty": empty,
                            "percent": pct
                        }
                except Exception as e:
                    print(f"Error reading stats for {item}: {e}")

            meta["stats"] = stats
            meta["is_active"] = (meta.get("id") == active_id)
            meta["dir"] = proj_dir
            meta["game_path_exists"] = os.path.exists(meta.get("game_data_path", ""))
            projects.append(meta)

        return projects

    def get_active_project_id(self) -> str:
        return self.get_global_setting('active_project_id', 'Ghoul_Goula_Compagnia')

    def set_active_project_id(self, project_id: str):
        proj_dir = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(proj_dir):
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")
        self.set_global_setting('active_project_id', project_id)

    def get_project(self, project_id: str) -> Optional[Dict[str, Any]]:
        for p in self.list_projects():
            if p.get("id") == project_id:
                return p
        return None

    def get_active_project(self) -> Optional[Dict[str, Any]]:
        active_id = self.get_active_project_id()
        proj = self.get_project(active_id)
        if not proj:
            # Fallback to first project if available
            all_projs = self.list_projects()
            if all_projs:
                self.set_active_project_id(all_projs[0]["id"])
                return all_projs[0]
        return proj

    def validate_game_path(self, game_path: str) -> Dict[str, Any]:
        """Validates a Wolf RPG game directory and finds the Data directory."""
        if not os.path.exists(game_path):
            return {"valid": False, "error": f"Đường dẫn không tồn tại: {game_path}"}

        # Check if folder contains Data/ subfolder
        data_sub = os.path.join(game_path, 'Data')
        if os.path.exists(data_sub) and os.path.isdir(data_sub):
            return {"valid": True, "game_path": game_path, "game_data_path": data_sub}

        # Check if the given folder IS the Data folder directly
        # E.g. has BasicData/ or Game.dat
        if os.path.exists(os.path.join(game_path, 'BasicData')) or os.path.exists(os.path.join(game_path, 'Game.dat')):
            parent_game = os.path.dirname(game_path)
            return {"valid": True, "game_path": parent_game, "game_data_path": game_path}

        # Check for any .dat or Game.exe
        exe_files = [f for f in os.listdir(game_path) if f.lower().endswith('.exe')]
        return {
            "valid": True,
            "game_path": game_path,
            "game_data_path": data_sub if os.path.exists(data_sub) else game_path,
            "warning": "Không tìm thấy thư mục 'Data' chuẩn, sẽ dùng thư mục gốc để bóc tách."
        }

    def create_project(self, name: str, game_path: str, extract_now: bool = True) -> Dict[str, Any]:
        """Creates a new translation project for a Wolf RPG game."""
        validation = self.validate_game_path(game_path)
        if not validation["valid"]:
            raise ValueError(validation["error"])

        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Tên dự án không được để trống!")

        # Generate slug ID
        slug = re.sub(r'[^a-zA-Z0-9_\-]', '_', clean_name).strip('_')
        if not slug:
            slug = f"project_{int(datetime.now().timestamp())}"

        # Ensure unique ID
        project_id = slug
        counter = 1
        while os.path.exists(os.path.join(self.projects_dir, project_id)):
            project_id = f"{slug}_{counter}"
            counter += 1

        proj_dir = os.path.join(self.projects_dir, project_id)
        os.makedirs(proj_dir, exist_ok=True)
        dump_dir = os.path.join(proj_dir, 'dump')
        os.makedirs(dump_dir, exist_ok=True)

        meta = {
            "id": project_id,
            "name": clean_name,
            "engine": "WOLF RPG",
            "game_path": validation["game_path"],
            "game_data_path": validation["game_data_path"],
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat()
        }

        with open(os.path.join(proj_dir, 'project.json'), 'w', encoding='utf-8') as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        # Set as active
        self.set_active_project_id(project_id)

        # Extract dump using WolfTL if extract_now is True
        if extract_now:
            import subprocess
            cmd = [self.wolftl_path, '--create', validation["game_data_path"], proj_dir]
            print(f"[ProjectManager] Running: {' '.join(cmd)}")
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode != 0:
                print(f"[ProjectManager] WolfTL dump warning: {res.stderr}")

        return self.get_project(project_id)

    def export_nel(self, project_id: str, output_path: Optional[str] = None) -> str:
        """Packs a project into a .nel (ZIP archive) containing manifest.json, project.json, and translation.db."""
        proj_dir = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(proj_dir):
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")

        meta_file = os.path.join(proj_dir, 'project.json')
        meta = {}
        if os.path.exists(meta_file):
            with open(meta_file, 'r', encoding='utf-8') as f:
                meta = json.load(f)

        db_path = os.path.join(proj_dir, 'translation.db')
        if not os.path.exists(db_path):
            raise ValueError("Không tìm thấy translation.db của dự án để xuất gói!")

        # Gather stats
        with sqlite3.connect(db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM translation_rows").fetchone()[0]
            empty = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 0").fetchone()[0]
            mtl = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 1").fetchone()[0]
            trans = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 2").fetchone()[0]
            completed = mtl + trans
            pct = round((completed / total * 100), 1) if total > 0 else 0.0

        manifest = {
            "app": "Nelir-Wolf",
            "format_version": 1,
            "project_id": project_id,
            "game_name": meta.get("name", project_id),
            "engine": meta.get("engine", "WOLF RPG"),
            "original_game_path": meta.get("game_path", ""),
            "original_game_data_path": meta.get("game_data_path", ""),
            "exported_at": datetime.now().isoformat(),
            "stats": {
                "total_rows": total,
                "completed_rows": completed,
                "translated_rows": trans,
                "mtl_rows": mtl,
                "empty_rows": empty,
                "completion_rate": pct
            }
        }

        # Default output path
        if not output_path:
            clean_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', meta.get("name", project_id))
            date_str = datetime.now().strftime("%Y%m%d_%H%M")
            output_path = os.path.join(self.projects_dir, f"{clean_name}_{date_str}.nel")

        # Create zip (.nel)
        with zipfile.ZipFile(output_path, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            zf.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
            if os.path.exists(meta_file):
                zf.write(meta_file, arcname='project.json')
            zf.write(db_path, arcname='translation.db')

        print(f"[ProjectManager] Exported .nel to {output_path} ({os.path.getsize(output_path)} bytes)")
        return output_path

    def import_nel(self, nel_file_path: str, override_game_path: Optional[str] = None) -> Dict[str, Any]:
        """Imports a .nel package into projects/ and restores the translation project."""
        if not os.path.exists(nel_file_path):
            raise ValueError(f"File .nel không tồn tại: {nel_file_path}")

        if not zipfile.is_zipfile(nel_file_path):
            raise ValueError("File tải lên không phải là định dạng gói .nel hợp lệ!")

        with zipfile.ZipFile(nel_file_path, 'r') as zf:
            namelist = zf.namelist()
            if 'manifest.json' not in namelist or 'translation.db' not in namelist:
                raise ValueError("Gói .nel bị thiếu manifest.json hoặc translation.db!")

            manifest_bytes = zf.read('manifest.json')
            manifest = json.loads(manifest_bytes.decode('utf-8'))

            game_name = manifest.get("game_name", "Imported_Game")
            base_id = manifest.get("project_id") or re.sub(r'[^a-zA-Z0-9_\-]', '_', game_name)
            
            # Ensure unique project id
            project_id = base_id
            counter = 1
            while os.path.exists(os.path.join(self.projects_dir, project_id)):
                project_id = f"{base_id}_imported_{counter}"
                counter += 1

            proj_dir = os.path.join(self.projects_dir, project_id)
            os.makedirs(proj_dir, exist_ok=True)

            # Extract translation.db
            zf.extract('translation.db', proj_dir)

            # Determine game path
            final_game_path = override_game_path or manifest.get("original_game_path", "")
            final_game_data_path = ""
            if final_game_path:
                val = self.validate_game_path(final_game_path)
                if val.get("valid"):
                    final_game_data_path = val["game_data_path"]

            meta = {
                "id": project_id,
                "name": game_name,
                "engine": manifest.get("engine", "WOLF RPG"),
                "game_path": final_game_path,
                "game_data_path": final_game_data_path,
                "created_at": manifest.get("exported_at", datetime.now().isoformat()),
                "last_modified": datetime.now().isoformat(),
                "imported_from_nel": True
            }

            with open(os.path.join(proj_dir, 'project.json'), 'w', encoding='utf-8') as f:
                json.dump(meta, f, ensure_ascii=False, indent=2)

            # If game_data_path exists, dump kịch bản if needed
            dump_dir = os.path.join(proj_dir, 'dump')
            os.makedirs(dump_dir, exist_ok=True)
            if final_game_data_path and os.path.exists(final_game_data_path):
                import subprocess
                cmd = [self.wolftl_path, '--create', final_game_data_path, proj_dir]
                print(f"[ProjectManager] Creating dump for imported project: {' '.join(cmd)}")
                subprocess.run(cmd, capture_output=True, text=True)

            # Set as active project
            self.set_active_project_id(project_id)
            print(f"[ProjectManager] Successfully imported project '{project_id}' from {nel_file_path}!")
            return self.get_project(project_id)

    def delete_project(self, project_id: str) -> bool:
        """Deletes a project directory."""
        if project_id == self.get_active_project_id():
            raise ValueError("Không thể xóa dự án đang được kích hoạt! Hãy chuyển sang dự án khác trước.")

        proj_dir = os.path.join(self.projects_dir, project_id)
        if not os.path.exists(proj_dir):
            raise ValueError(f"Dự án '{project_id}' không tồn tại!")

        import gc
        import time
        gc.collect()

        for attempt in range(5):
            try:
                shutil.rmtree(proj_dir)
                print(f"[ProjectManager] Deleted project: {project_id}")
                return True
            except (PermissionError, OSError) as e:
                if attempt == 4:
                    raise e
                time.sleep(0.3)
                gc.collect()
        return True
