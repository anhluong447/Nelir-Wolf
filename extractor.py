"""Reading WolfTL dumps, syncing them into SQLite, key locking and WolfTL calls."""
import glob
import json
import os
import re
import shutil
import subprocess
import tempfile

import config
from db import connect

ASSET_EXTS = ('.png', '.jpg', '.jpeg', '.bmp', '.wav', '.ogg', '.mp3', '.mid', '.dll', '.txt', '.html', '.cur')
_TOKEN_RE = re.compile(r'([a-zA-Z0-9_]+)|\[(\d+)\]')


class WolfTLError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------
def _tokens(path):
    tokens = _TOKEN_RE.findall(path)
    if not tokens:
        raise ValueError(f"Invalid path: {path}")
    return tokens


def get_by_path(root, path):
    cur = root
    for key, idx in _tokens(path):
        cur = cur[key] if key else cur[int(idx)]
    return cur


def set_by_path(root, path, value):
    tokens = _tokens(path)
    cur = root
    for key, idx in tokens[:-1]:
        cur = cur[key] if key else cur[int(idx)]
    last_key, last_idx = tokens[-1]
    if last_key:
        cur[last_key] = value
    else:
        cur[int(last_idx)] = value


def load_json(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


# ---------------------------------------------------------------------------
# String extraction
# ---------------------------------------------------------------------------
def is_translatable(s) -> bool:
    if not isinstance(s, str):
        return False
    s = s.strip()
    if not s:
        return False
    if any(s.lower().endswith(ext) for ext in ASSET_EXTS):
        return False
    if ('/' in s or '\\' in s) and '.' in s:
        return False  # looks like a file path
    return any('぀' <= c <= 'ヿ' or '一' <= c <= '鿿' for c in s)


def _row_type(code_str):
    if code_str == 'Message':
        return 'Message'
    if code_str == 'Choices':
        return 'Choice'
    return code_str or 'Unknown'


def iter_dump_strings(dump_dir):
    """Yield (file, category, path, row_type, raw) for every Japanese string in a dump."""
    game_json = os.path.join(dump_dir, 'Game.json')
    if os.path.exists(game_json):
        d = load_json(game_json)
        for k in ('Title', 'StartUpMsg', 'TitleMsg'):
            val = d.get(k, '')
            if is_translatable(val):
                yield ('Game.json', 'System', k, 'GameTitle', val)

    for f in sorted(glob.glob(os.path.join(dump_dir, 'common', '*.json'))):
        rel = os.path.relpath(f, dump_dir)
        d = load_json(f)
        for i, cmd in enumerate(d.get('commands', [])):
            rt = _row_type(cmd.get('codeStr', ''))
            for j, arg in enumerate(cmd.get('stringArgs', [])):
                if is_translatable(arg):
                    yield (rel, 'CommonEvent', f"commands[{i}].stringArgs[{j}]", rt, arg)

    for f in sorted(glob.glob(os.path.join(dump_dir, 'mps', '*.json'))):
        rel = os.path.relpath(f, dump_dir)
        d = load_json(f)
        for e_idx, ev in enumerate(d.get('events', [])):
            for p_idx, page in enumerate(ev.get('pages', [])):
                for c_idx, cmd in enumerate(page.get('list', [])):
                    rt = _row_type(cmd.get('codeStr', ''))
                    for a_idx, arg in enumerate(cmd.get('stringArgs', [])):
                        if is_translatable(arg):
                            path = f"events[{e_idx}].pages[{p_idx}].list[{c_idx}].stringArgs[{a_idx}]"
                            yield (rel, 'Map', path, rt, arg)

    for f in sorted(glob.glob(os.path.join(dump_dir, 'db', '*.json'))):
        if os.path.basename(f) in config.EXCLUDED_FILES:
            continue
        rel = os.path.relpath(f, dump_dir)
        d = load_json(f)
        for t_idx, t in enumerate(d.get('types', [])):
            for d_idx, item in enumerate(t.get('data', [])):
                name = item.get('name', '')
                if is_translatable(name):
                    yield (rel, 'Database', f"types[{t_idx}].data[{d_idx}].name", 'DBName', name)
                for f_idx, field in enumerate(item.get('data', [])):
                    val = field.get('value', '')
                    if is_translatable(val):
                        yield (rel, 'Database', f"types[{t_idx}].data[{d_idx}].data[{f_idx}].value", 'DBField', val)


def sync_rows(db_path, dump_dir) -> dict:
    """Merge strings from a (pristine) dump into the DB without losing translations.

    Same (file, path, raw) -> kept as is. Same (file, path) but different raw ->
    raw replaced and translation reset. Missing in dump -> deleted. New -> inserted.
    """
    new_rows = list(iter_dump_strings(dump_dir))
    stats = {"kept": 0, "changed": 0, "inserted": 0, "deleted": 0}
    with connect(db_path) as conn:
        existing = {(f, p): (rid, raw) for rid, f, p, raw in
                    conn.execute("SELECT id, file, path, raw FROM translation_rows")}
        seen = set()
        for f, cat, p, rt, raw in new_rows:
            key = (f, p)
            seen.add(key)
            if key in existing:
                rid, old_raw = existing[key]
                if old_raw == raw:
                    conn.execute("UPDATE translation_rows SET category = ?, row_type = ? WHERE id = ?", (cat, rt, rid))
                    stats["kept"] += 1
                else:
                    conn.execute(
                        "UPDATE translation_rows SET category = ?, row_type = ?, raw = ?, mtl = '', translated = '', "
                        "status = 0, qa_flags = '' WHERE id = ?", (cat, rt, raw, rid))
                    stats["changed"] += 1
            else:
                conn.execute(
                    "INSERT INTO translation_rows (file, category, path, row_type, raw) VALUES (?, ?, ?, ?, ?)",
                    (f, cat, p, rt, raw))
                stats["inserted"] += 1
        gone = [existing[k][0] for k in existing if k not in seen]
        conn.executemany("DELETE FROM translation_rows WHERE id = ?", [(i,) for i in gone])
        stats["deleted"] = len(gone)
    refresh_locks(db_path)
    return stats


def refresh_locks(db_path) -> int:
    """Lock rows that must never be translated:
    - every non-translatable command type (Database, labels, conditions, ...);
    - key-capable rows (SetString/DBName/DBField) whose raw text is referenced by a
      reference command, because translating only one side breaks the lookup."""
    translatable = tuple(config.TRANSLATABLE_TYPES)
    key_capable = tuple(config.KEY_CAPABLE_TYPES)
    refs = tuple(config.REFERENCE_TYPES)
    ph = lambda xs: ",".join("?" * len(xs))
    with connect(db_path) as conn:
        conn.execute(f"""
            UPDATE translation_rows SET locked = CASE
                WHEN row_type NOT IN ({ph(translatable)}) THEN 1
                WHEN row_type IN ({ph(key_capable)}) AND raw IN (
                    SELECT raw FROM translation_rows WHERE row_type IN ({ph(refs)})
                ) THEN 1
                ELSE 0 END
        """, translatable + key_capable + refs)
        return conn.execute("SELECT COUNT(*) FROM translation_rows WHERE locked = 1").fetchone()[0]


# ---------------------------------------------------------------------------
# WolfTL
# ---------------------------------------------------------------------------
def run_wolftl(args, timeout=900):
    if not os.path.exists(config.WOLFTL_PATH):
        raise WolfTLError(f"Không tìm thấy WolfTL: {config.WOLFTL_PATH}")
    cmd = [config.WOLFTL_PATH] + list(args)
    print(f"[WolfTL] {' '.join(cmd)}")
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if res.returncode != 0:
        raise WolfTLError(f"WolfTL lỗi (mã {res.returncode}): {(res.stderr or res.stdout).strip()[:2000]}")
    return res.stdout


def wolftl_create_dump(game_data_path, out_dir):
    """Run `WolfTL --create`; WolfTL writes into <out_dir>/dump."""
    if not game_data_path or not os.path.isdir(game_data_path):
        raise WolfTLError(f"Thư mục Data của game không tồn tại: '{game_data_path}'")
    os.makedirs(out_dir, exist_ok=True)
    run_wolftl(['--create', game_data_path, out_dir])
    dump = os.path.join(out_dir, 'dump')
    if not os.path.isdir(dump) or not os.listdir(dump):
        raise WolfTLError("WolfTL chạy xong nhưng không tạo ra thư mục dump (game không đúng định dạng WOLF RPG?)")
    return dump


def wolftl_patch(game_data_path, project_dir):
    """Run `WolfTL --patch --inplace`; WolfTL reads <project_dir>/dump."""
    return run_wolftl(['--patch', '--inplace', game_data_path, project_dir])


def dump_looks_patched(dump_dir, db_path) -> int:
    """Count rows whose dump value equals an existing translation (≠ raw).
    > 0 means the game data the dump came from was already patched."""
    hits = 0
    cache = {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT file, path, raw, translated, mtl FROM translation_rows "
            "WHERE translated != '' OR mtl != '' LIMIT 3000").fetchall()
    for f, p, raw, trans, mtl in rows:
        full = os.path.join(dump_dir, f)
        if f not in cache:
            cache[f] = load_json(full) if os.path.exists(full) else None
        if cache[f] is None:
            continue
        try:
            v = get_by_path(cache[f], p)
        except Exception:
            continue
        if v != raw and v in (trans, mtl):
            hits += 1
    return hits


def ensure_original_dump(project_dir, db_path, game_data_path) -> str:
    """Make sure <project>/dump_original holds the pristine Japanese dump.

    - already present: nothing to do;
    - only <project>/dump present (older versions patched it in place): copy it and
      restore every known row back to its raw text from the DB;
    - nothing present: run WolfTL --create from the game data.
    """
    original = os.path.join(project_dir, 'dump_original')
    if os.path.isdir(original) and os.listdir(original):
        return original
    work = os.path.join(project_dir, 'dump')
    if not (os.path.isdir(work) and os.listdir(work)):
        wolftl_create_dump(game_data_path, project_dir)
    tmp = original + '.tmp'
    if os.path.exists(tmp):
        shutil.rmtree(tmp)
    shutil.copytree(work, tmp)
    restored = 0
    if os.path.exists(db_path):
        with connect(db_path) as conn:
            rows = conn.execute("SELECT file, path, raw FROM translation_rows ORDER BY file").fetchall()
        by_file = {}
        for f, p, raw in rows:
            by_file.setdefault(f, []).append((p, raw))
        for f, items in by_file.items():
            full = os.path.join(tmp, f)
            if not os.path.exists(full):
                continue
            data = load_json(full)
            changed = False
            for p, raw in items:
                try:
                    if get_by_path(data, p) != raw:
                        set_by_path(data, p, raw)
                        changed = True
                        restored += 1
                except Exception:
                    pass
            if changed:
                save_json(full, data)
    os.replace(tmp, original)
    print(f"[Extractor] Created dump_original ({restored} strings restored to raw)")
    return original


def recreate_original_from_game(project_dir, db_path, game_data_path) -> dict:
    """Re-dump from the game into a temp dir; refuse if the game looks patched."""
    tmp_root = tempfile.mkdtemp(prefix='nelir_dump_', dir=project_dir)
    try:
        dump = wolftl_create_dump(game_data_path, tmp_root)
        patched_hits = dump_looks_patched(dump, db_path)
        if patched_hits:
            raise WolfTLError(
                f"Dữ liệu game có vẻ ĐÃ được vá ({patched_hits} chuỗi trùng với bản dịch). "
                "Hãy khôi phục bản gốc của game trước khi trích xuất lại từ game.")
        original = os.path.join(project_dir, 'dump_original')
        if os.path.exists(original):
            shutil.rmtree(original)
        shutil.move(dump, original)
        return {"source": "game"}
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)
