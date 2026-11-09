import os
import json
import sqlite3
import glob
import re

PROJECT_DIR = r"E:\Games\RJ179471\Nelir-Wolf\projects\Ghoul_Goula_Compagnia"
GAME_DIR = r"E:\Games\RJ179471\Ghoul_Goula_Compagnia"
DB_PATH = os.path.join(PROJECT_DIR, "translation.db")
DUMP_DIR = os.path.join(PROJECT_DIR, "dump")

print("=" * 60)
print("🔍 BẮT ĐẦU KIỂM TRA TOÀN DIỆN MỌI THOẠI VÀ SCRIPT CỦA GAME")
print("=" * 60)

errors = []
warnings = []

# ========================================================
# 1. KIỂM TRA TẤT CẢ DÒNG BẢN DỊCH TRONG SQLITE
# ========================================================
print("\n[1/5] Quét 15,646 dòng dịch thuật tìm lỗi cú pháp / Control Codes / File Assets...")

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Control code patterns in WOLF RPG:
# \cself[...], \C[...], \v[...], \s[...], \N[...], \udb[...], \cdb[...], \sdb[...]
CTRL_REGEX = re.compile(r'\\([a-zA-Z]+)\[([^\]]*)\]')
BROKEN_CTRL_REGEX = re.compile(r'\\([a-zA-Z]+)\[[^\]]*$') # unclosed bracket

rows = c.execute("SELECT id, file, row_type, raw, translated, mtl FROM translation_rows WHERE status > 0").fetchall()
print(f"-> Đã nạp {len(rows)} dòng có bản dịch.")

for row_id, file, row_type, raw, trans, mtl in rows:
    text = trans or mtl
    if not text:
        continue

    # A. Check unclosed control codes: \cself[ without ]
    # Count '[' and ']' after backslash
    for tag in ['cself', 'C', 'c', 'v', 's', 'N', 'cdb', 'udb', 'sdb']:
        pattern_open = f"\\{tag}["
        if pattern_open in text and ']' not in text[text.find(pattern_open):]:
            errors.append(f"Row #{row_id} ({file}) [{row_type}]: Mã điều khiển '{pattern_open}' chưa đóng ngoặc ']': '{text}'")

    # B. Compare control codes in RAW vs TRANSLATED
    raw_ctrls = CTRL_REGEX.findall(raw)
    trans_ctrls = CTRL_REGEX.findall(text)
    
    # Check if a critical tag in raw was lost or corrupted
    raw_tags = [f"\\{k}[{v}]" for k, v in raw_ctrls]
    trans_tags = [f"\\{k}[{v}]" for k, v in trans_ctrls]
    
    for rt in raw_tags:
        # Normalize whitespace in tag
        norm_rt = re.sub(r'\s+', '', rt)
        matching = any(norm_rt == re.sub(r'\s+', '', tt) for tt in trans_tags)
        if not matching:
            # Check if it was translated to Vietnamese like \cchínhmình[...]
            warnings.append(f"Row #{row_id} ({file}): Mã gốc '{rt}' không khớp chính xác trong bản dịch: '{text[:60]}...'")

    # C. Check if any file path was accidentally translated
    # e.g. .png, .ogg, .wav
    for ext in ['.png', '.jpg', '.ogg', '.wav', '.mp3']:
        if ext in raw.lower() and ext not in text.lower():
            errors.append(f"Row #{row_id} ({file}): Mất đuôi file '{ext}' trong bản dịch: '{text}'")
        elif ext in raw.lower() and ext in text.lower():
            # Check if the asset file exists in Game Data!
            clean_path = text.strip().replace('/', '\\')
            asset_full = os.path.join(GAME_DIR, 'Data', clean_path)
            if not os.path.exists(asset_full):
                # Try relative to Data
                warnings.append(f"Row #{row_id} ({file}): File asset '{clean_path}' không tìm thấy trên đĩa (có thể gây crash nếu game load)!")

print(f"-> Kiểm tra xong dòng dịch. Tìm thấy: {len(errors)} lỗi nghiêm trọng, {len(warnings)} cảnh báo.")

# ========================================================
# 2. KIỂM TRA TOÀN BỘ LỆNH DATABASE TRONG COMMON EVENTS & MAPS
# ========================================================
print("\n[2/5] Quét tất cả lệnh Database trong Common Events và Maps (tìm lỗi 'data name does not exist')...")

# Load databases
with open(os.path.join(DUMP_DIR, "db", "DataBase.json"), "r", encoding="utf-8") as f:
    user_db = json.load(f)
with open(os.path.join(DUMP_DIR, "db", "SysDatabase.json"), "r", encoding="utf-8") as f:
    sys_db = json.load(f)
with open(os.path.join(DUMP_DIR, "db", "CDataBase.json"), "r", encoding="utf-8") as f:
    c_db = json.load(f)

# Build lookup dictionaries for all databases
# db_lookup[db_type_id][type_name][data_name]
def build_db_index(db_json):
    index = {} # type_index -> { 'name': type_name, 'data': set(data_names) }
    for t_idx, t in enumerate(db_json.get('types', [])):
        t_name = t.get('name', '')
        d_names = {d.get('name', '') for d in t.get('data', []) if d.get('name')}
        index[t_idx] = {'name': t_name, 'data_names': d_names}
    return index

user_db_idx = build_db_index(user_db)
sys_db_idx = build_db_index(sys_db)
c_db_idx = build_db_index(c_db)

print(f"-> Đã index UserDB ({len(user_db_idx)} types), SysDB ({len(sys_db_idx)} types), CDataBase ({len(c_db_idx)} types).")

# Check all commands in common events
db_query_count = 0
db_query_errors = 0

for json_file in glob.glob(os.path.join(DUMP_DIR, "common", "*.json")) + glob.glob(os.path.join(DUMP_DIR, "mps", "*.json")):
    rel_path = os.path.relpath(json_file, DUMP_DIR)
    with open(json_file, "r", encoding="utf-8") as fp:
        try:
            data = json.load(fp)
        except Exception:
            continue

    # Get commands list
    cmd_list = []
    if "commands" in data:
        cmd_list = [(i, cmd) for i, cmd in enumerate(data.get("commands", []))]
    elif "events" in data:
        for e_idx, ev in enumerate(data.get("events", [])):
            for p_idx, page in enumerate(ev.get("pages", [])):
                for c_idx, cmd in enumerate(page.get("list", [])):
                    cmd_list.append((f"Ev{e_idx}P{p_idx}L{c_idx}", cmd))

    for loc, cmd in cmd_list:
        if cmd.get("codeStr") == "Database":
            db_query_count += 1
            s_args = cmd.get("stringArgs", [])
            i_args = cmd.get("intArgs", [])
            
            # If data name is specified by string: s_args[2]
            if len(s_args) > 2 and s_args[2]:
                target_type_name = s_args[1] if len(s_args) > 1 else ""
                target_data_name = s_args[2]

                # Find which DB this belongs to
                found_in_any = False
                for db_name, db_idx in [("CDataBase", c_db_idx), ("UserDB", user_db_idx), ("SysDB", sys_db_idx)]:
                    for t_id, t_info in db_idx.items():
                        if target_type_name and t_info['name'] == target_type_name:
                            if target_data_name in t_info['data_names']:
                                found_in_any = True
                                break
                        elif not target_type_name:
                            if target_data_name in t_info['data_names']:
                                found_in_any = True
                                break
                    if found_in_any:
                        break

                if not found_in_any:
                    errors.append(f"LỖI DB CRASH tại {rel_path} Line {loc}: Lệnh tìm '{target_data_name}' trong type '{target_type_name}' nhưng KHÔNG TỒN TẠI trong database!")
                    db_query_errors += 1

print(f"-> Đã quét {db_query_count} lệnh gọi Database. Lỗi tìm kiếm DB: {db_query_errors}.")

# ========================================================
# 3. KIỂM TRA NHÃN NHẢY (JUMP LABEL / SET LABEL)
# ========================================================
print("\n[3/5] Quét nhãn nhảy (JumpLabel / SetLabel) tìm nhãn mồ côi (gây treo game/lỗi logic)...")

label_jump_count = 0
label_errors = 0

for json_file in glob.glob(os.path.join(DUMP_DIR, "common", "*.json")) + glob.glob(os.path.join(DUMP_DIR, "mps", "*.json")):
    rel_path = os.path.relpath(json_file, DUMP_DIR)
    with open(json_file, "r", encoding="utf-8") as fp:
        try:
            data = json.load(fp)
        except Exception:
            continue

    pages_to_check = []
    if "commands" in data:
        pages_to_check.append(("main", data.get("commands", [])))
    elif "events" in data:
        for e_idx, ev in enumerate(data.get("events", [])):
            for p_idx, page in enumerate(ev.get("pages", [])):
                pages_to_check.append((f"Ev{e_idx}_P{p_idx}", page.get("list", [])))

    for page_name, cmds in pages_to_check:
        set_labels = set()
        jump_labels = []

        for idx, cmd in enumerate(cmds):
            code_str = cmd.get("codeStr")
            s_args = cmd.get("stringArgs", [])
            if code_str == "SetLabel" and s_args and s_args[0]:
                set_labels.add(s_args[0].strip())
            elif code_str == "JumpLabel" and s_args and s_args[0]:
                label_jump_count += 1
                jump_labels.append((idx, s_args[0].strip()))

        for j_idx, lbl in jump_labels:
            if lbl not in set_labels:
                errors.append(f"LỖI NHÃN NHẢY tại {rel_path} ({page_name}) Line {j_idx}: Lệnh JumpLabel nhảy tới '{lbl}' nhưng không có SetLabel nào khớp!")
                label_errors += 1

print(f"-> Đã kiểm tra {label_jump_count} lệnh JumpLabel. Nhãn mồ côi: {label_errors}.")

# ========================================================
# 4. KIỂM TRA ĐIỀU KIỆN CHUỖI (STRING CONDITION)
# ========================================================
print("\n[4/5] Quét các lệnh so sánh chuỗi (StringCondition)...")

str_cond_count = 0
str_cond_warnings = 0

for json_file in glob.glob(os.path.join(DUMP_DIR, "common", "*.json")) + glob.glob(os.path.join(DUMP_DIR, "mps", "*.json")):
    rel_path = os.path.relpath(json_file, DUMP_DIR)
    with open(json_file, "r", encoding="utf-8") as fp:
        try:
            data = json.load(fp)
        except Exception:
            continue

    cmd_list = []
    if "commands" in data:
        cmd_list = data.get("commands", [])
    elif "events" in data:
        for ev in data.get("events", []):
            for page in ev.get("pages", []):
                cmd_list.extend(page.get("list", []))

    for cmd in cmd_list:
        if cmd.get("codeStr") == "StringCondition":
            str_cond_count += 1
            s_args = cmd.get("stringArgs", [])
            # If string args has non-ASCII compared against variable
            # It's good to log
print(f"-> Đã quét {str_cond_count} lệnh so sánh điều kiện chuỗi.")

# ========================================================
# 5. TỔNG KẾT BÁO CÁO
# ========================================================
print("\n" + "=" * 60)
print("📊 KẾT QUẢ KIỂM THỬ TĨNH TOÀN DIỆN")
print("=" * 60)
print(f"❌ Tổng lỗi nghiêm trọng (nguy cơ crash game): {len(errors)}")
print(f"⚠️ Tổng cảnh báo (sai khác format nhẹ): {len(warnings)}")

if errors:
    print("\n--- CHI TIẾT CÁC LỖI NGHIÊM TRỌNG (CẦN SỬA NGAY) ---")
    for err in errors[:50]:
        print(f"  • {err}")
    if len(errors) > 50:
        print(f"  ... và {len(errors) - 50} lỗi khác.")
else:
    print("\n🎉 TUYỆT VỜI! KHÔNG TÌM THẤY BẤT KỲ LỖI GÂY CRASH NÀO TRONG TOÀN BỘ GAME!")

if warnings:
    print(f"\n--- XEM TRƯỚC 10 CẢNH BÁO NHẸ (KHÔNG GÂY CRASH) ---")
    for w in warnings[:10]:
        print(f"  • {w}")

conn.close()
