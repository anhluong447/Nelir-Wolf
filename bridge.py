import os
import glob
import json
import re
import sqlite3
import subprocess
import shutil
from typing import Optional, Dict, Any
from project_manager import ProjectManager

ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.wav', '.ogg', '.mp3', '.mid', '.dll', '.txt', '.html', '.cur')

def is_translatable(s):
    if not isinstance(s, str):
        return False
    s = s.strip()
    if len(s) < 1:
        return False
    if any(s.lower().endswith(ext) for ext in ASSET_EXTS):
        return False
    if ('/' in s or '\\' in s) and ('.' in s):
        return False
    # Must contain Japanese characters (hiragana, katakana, or kanji)
    return any('\u3040' <= c <= '\u30ff' or '\u4e00' <= c <= '\u9fff' for c in s)

class WolfBridge:
    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        self.bin_dir = os.path.join(root_dir, 'bin')
        self.wolftl_path = os.path.join(self.bin_dir, 'WolfTL.exe')
        self.pm = ProjectManager(root_dir)
        self.load_active_project()

    def load_active_project(self, project_id: Optional[str] = None):
        """Loads the active project or switches to a specified project_id."""
        if project_id:
            self.pm.set_active_project_id(project_id)
        
        proj = self.pm.get_active_project()
        if not proj:
            # If no projects exist at all, create default
            proj = self.pm.get_project('Ghoul_Goula_Compagnia')
            if not proj:
                # Fallback to root if completely empty
                self.project_id = 'default'
                self.project_dir = self.root_dir
                self.dump_dir = os.path.join(self.root_dir, 'dump')
                self.db_path = os.path.join(self.root_dir, 'nelir_wolf.db')
                self.game_data_path = os.path.join(os.path.dirname(self.root_dir), 'Ghoul_Goula_Compagnia', 'Data')
                self.game_path = os.path.dirname(self.game_data_path)
                self._init_db()
                return

        self.project_id = proj["id"]
        self.project_dir = proj["dir"]
        self.dump_dir = os.path.join(self.project_dir, 'dump')
        self.db_path = os.path.join(self.project_dir, 'translation.db')
        self.game_data_path = proj.get("game_data_path", "")
        self.game_path = proj.get("game_path", "")
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS translation_rows (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    file TEXT NOT NULL,
                    category TEXT NOT NULL,
                    path TEXT NOT NULL,
                    row_type TEXT NOT NULL,
                    raw TEXT NOT NULL,
                    mtl TEXT DEFAULT '',
                    translated TEXT DEFAULT '',
                    status INTEGER DEFAULT 0 -- 0: empty, 1: mtl, 2: translated
                )
            ''')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_file ON translation_rows(file)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_status ON translation_rows(status)')
            conn.execute('CREATE INDEX IF NOT EXISTS idx_category ON translation_rows(category)')
            conn.commit()

    def get_setting(self, key: str, default: str = '') -> str:
        return self.pm.get_global_setting(key, default)

    def set_setting(self, key: str, value: str):
        self.pm.set_global_setting(key, value)

    def dump_game_if_needed(self) -> bool:
        """Runs WolfTL.exe --create if dump doesn't exist for active project."""
        if not os.path.exists(self.dump_dir) or not os.listdir(self.dump_dir):
            if not os.path.exists(self.game_data_path):
                print(f"[WolfBridge] Game data path does not exist: {self.game_data_path}")
                return False
            os.makedirs(self.dump_dir, exist_ok=True)
            cmd = [self.wolftl_path, '--create', self.game_data_path, self.project_dir]
            print(f"[WolfBridge] Running: {' '.join(cmd)}")
            subprocess.run(cmd, check=True)
        return True

    def extract_strings_to_db(self, force: bool = False):
        """Extracts translatable rows from project dump/ into project SQLite."""
        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute('SELECT COUNT(*) FROM translation_rows').fetchone()[0]
            if count > 0 and not force:
                print(f"Project '{self.project_id}' database already has {count} rows. Skipping extraction.")
                return count

            if force:
                conn.execute('DELETE FROM translation_rows')
                conn.commit()

        self.dump_game_if_needed()

        rows = []
        # 1. Process Game.json
        game_json = os.path.join(self.dump_dir, 'Game.json')
        if os.path.exists(game_json):
            with open(game_json, 'r', encoding='utf-8') as f:
                d = json.load(f)
                for k in ['Title', 'StartUpMsg', 'TitleMsg']:
                    val = d.get(k, '')
                    if is_translatable(val):
                        rows.append(('Game.json', 'System', k, 'GameTitle', val))

        # 2. Process common events (common/*.json)
        for f in glob.glob(os.path.join(self.dump_dir, 'common', '*.json')):
            rel = os.path.relpath(f, self.dump_dir)
            with open(f, 'r', encoding='utf-8') as fp:
                try:
                    d = json.load(fp)
                    for i, cmd in enumerate(d.get('commands', [])):
                        code_str = cmd.get('codeStr', '')
                        args = cmd.get('stringArgs', [])
                        for j, arg in enumerate(args):
                            if is_translatable(arg):
                                path = f"commands[{i}].stringArgs[{j}]"
                                row_type = 'Message' if code_str == 'Message' else ('Choice' if code_str == 'Choices' else code_str)
                                rows.append((rel, 'CommonEvent', path, row_type, arg))
                except Exception as e:
                    print(f"Error reading {f}: {e}")

        # 3. Process maps (mps/*.json)
        for f in glob.glob(os.path.join(self.dump_dir, 'mps', '*.json')):
            rel = os.path.relpath(f, self.dump_dir)
            with open(f, 'r', encoding='utf-8') as fp:
                try:
                    d = json.load(fp)
                    for e_idx, ev in enumerate(d.get('events', [])):
                        for p_idx, page in enumerate(ev.get('pages', [])):
                            for c_idx, cmd in enumerate(page.get('list', [])):
                                code_str = cmd.get('codeStr', '')
                                args = cmd.get('stringArgs', [])
                                for a_idx, arg in enumerate(args):
                                    if is_translatable(arg):
                                        path = f"events[{e_idx}].pages[{p_idx}].list[{c_idx}].stringArgs[{a_idx}]"
                                        row_type = 'Message' if code_str == 'Message' else ('Choice' if code_str == 'Choices' else code_str)
                                        rows.append((rel, 'Map', path, row_type, arg))
                except Exception as e:
                    print(f"Error reading {f}: {e}")

        # 4. Process databases (db/*.json)
        for f in glob.glob(os.path.join(self.dump_dir, 'db', '*.json')):
            if os.path.basename(f) == 'CDataBase.json':
                continue  # CDataBase is Wolf RPG engine runtime memory (variables, party counts) - NEVER extract!
            rel = os.path.relpath(f, self.dump_dir)
            with open(f, 'r', encoding='utf-8') as fp:
                try:
                    d = json.load(fp)
                    for t_idx, t in enumerate(d.get('types', [])):
                        for d_idx, item in enumerate(t.get('data', [])):
                            # item.name
                            item_name = item.get('name', '')
                            if is_translatable(item_name):
                                rows.append((rel, 'Database', f"types[{t_idx}].data[{d_idx}].name", 'DBName', item_name))
                            for f_idx, field in enumerate(item.get('data', [])):
                                val = field.get('value', '')
                                if is_translatable(val):
                                    rows.append((rel, 'Database', f"types[{t_idx}].data[{d_idx}].data[{f_idx}].value", 'DBField', val))
                except Exception as e:
                    print(f"Error reading {f}: {e}")

        # Batch insert into SQLite
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                'INSERT INTO translation_rows (file, category, path, row_type, raw) VALUES (?, ?, ?, ?, ?)',
                rows
            )
            conn.commit()

        print(f"Successfully extracted {len(rows)} translatable rows into '{self.project_id}' SQLite!")
        return len(rows)

    def patch_to_game(self) -> dict:
        """Takes translated rows from project SQLite, applies to dump JSON, and runs WolfTL --patch --inplace.
        NOTE: Untranslated or cleared rows are automatically restored to their original 'raw' Japanese text!"""
        if not self.game_data_path or not os.path.exists(self.game_data_path):
            return {
                "success": False,
                "message": f"Không tìm thấy thư mục Data của game: '{self.game_data_path}'. Vui lòng kiểm tra lại đường dẫn cài đặt game!"
            }

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute('''
                SELECT file, path, raw, translated, mtl
                FROM translation_rows
            ''')
            all_rows = cursor.fetchall()

        if not all_rows:
            return {"success": False, "message": "Không tìm thấy dữ liệu trong database dự án!"}

        # Group by file
        file_map = {}
        translated_count = 0
        for f, p, raw, trans, mtl in all_rows:
            if 'CDataBase.json' in f:
                continue  # Never touch or overwrite CDataBase.json!
            if f not in file_map:
                file_map[f] = []
            
            # If user has translated this row, apply translation; otherwise revert to raw original!
            if trans and trans.strip():
                final_text = trans
                translated_count += 1
            elif mtl and mtl.strip():
                final_text = mtl
                translated_count += 1
            else:
                final_text = raw  # Restore original Japanese text!

            file_map[f].append((p, final_text))

        def set_by_path(root, path, val):
            tokens = re.findall(r'([a-zA-Z0-9_]+)|\[(\d+)\]', path)
            cur = root
            for k, idx in tokens[:-1]:
                if k:
                    cur = cur[k]
                else:
                    cur = cur[int(idx)]
            last_k, last_idx = tokens[-1]
            if last_k:
                cur[last_k] = val
            else:
                cur[int(last_idx)] = val

        # Update JSON files
        updated_files = 0
        for rel_file, patches in file_map.items():
            full_path = os.path.join(self.dump_dir, rel_file)
            if not os.path.exists(full_path):
                continue
            with open(full_path, 'r', encoding='utf-8') as fp:
                data = json.load(fp)

            for path, text in patches:
                try:
                    set_by_path(data, path, text)
                except Exception as e:
                    print(f"Failed setting path {path} in {rel_file}: {e}")

            with open(full_path, 'w', encoding='utf-8') as fp:
                json.dump(data, fp, ensure_ascii=False, indent=4)
            updated_files += 1

        # Run WolfTL --patch --inplace
        cmd = [self.wolftl_path, '--patch', '--inplace', self.game_data_path, self.project_dir]
        print(f"Running patch command: {' '.join(cmd)}")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            return {
                "success": True,
                "message": f"Vá bản dịch thành công vào game! Đã áp dụng {translated_count} dòng tiếng Việt (và đồng bộ lại các dòng chưa dịch/đã xóa về tiếng Nhật gốc) qua {updated_files} file.",
                "details": res.stdout
            }
        else:
            return {
                "success": False,
                "message": f"Lỗi khi chạy WolfTL patch: {res.stderr or res.stdout}"
            }
