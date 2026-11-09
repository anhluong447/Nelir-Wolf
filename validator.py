"""Static checks on a dump (original or about-to-be-patched).

Patching compares the patched dump against the original one and only blocks on
*new* errors, so pre-existing quirks of the game never block a patch.

CLI:  python validator.py --project <project_id>
"""
import argparse
import glob
import os
import sys

import config
from db import connect
from extractor import load_json
from qa import qa_flags


def load_dump(dump_dir) -> dict:
    files = {}
    for sub in ('common', 'mps', 'db'):
        for f in glob.glob(os.path.join(dump_dir, sub, '*.json')):
            files[os.path.relpath(f, dump_dir)] = load_json(f)
    return files


def _command_pages(rel, data):
    if "commands" in data:
        yield "main", data.get("commands", [])
    for e_idx, ev in enumerate(data.get("events", []) or []):
        for p_idx, page in enumerate(ev.get("pages", [])):
            yield f"Ev{e_idx}_P{p_idx}", page.get("list", [])


def _db_index(files):
    names = {}
    for rel, data in files.items():
        if not rel.startswith("db"):
            continue
        for t in data.get("types", []):
            bucket = names.setdefault(t.get("name", ""), set())
            bucket.update(d.get("name", "") for d in t.get("data", []) if d.get("name"))
    return names


def check_dump(files) -> set:
    """Return a set of error strings (stable, so they can be diffed)."""
    errors = set()
    db_names = _db_index(files)
    all_names = set().union(*db_names.values()) if db_names else set()
    for rel, data in files.items():
        if rel.startswith("db"):
            continue
        for page_name, cmds in _command_pages(rel, data):
            set_labels, jumps = set(), []
            for idx, cmd in enumerate(cmds):
                code = cmd.get("codeStr")
                s_args = cmd.get("stringArgs", []) or []
                if code == "SetLabel" and s_args and s_args[0]:
                    set_labels.add(s_args[0].strip())
                elif code == "JumpLabel" and s_args and s_args[0]:
                    jumps.append((idx, s_args[0].strip()))
                elif code == "Database" and len(s_args) > 2 and s_args[2]:
                    type_name, data_name = (s_args[1] if len(s_args) > 1 else ""), s_args[2]
                    pool = db_names.get(type_name, set()) if type_name else all_names
                    if data_name not in pool and data_name not in all_names:
                        errors.add(f"[DB] {rel} {page_name} #{idx}: tra cứu '{data_name}' (type '{type_name}') không tồn tại")
            for idx, lbl in jumps:
                if lbl not in set_labels:
                    errors.add(f"[LABEL] {rel} {page_name} #{idx}: JumpLabel '{lbl}' không có SetLabel tương ứng")
    return errors


def check_key_consistency(db_path) -> list:
    """Translated key-capable rows whose raw is still referenced elsewhere (should be locked)."""
    refs = tuple(config.REFERENCE_TYPES)
    keys = tuple(config.KEY_CAPABLE_TYPES)
    with connect(db_path) as conn:
        rows = conn.execute(f"""
            SELECT id, file, row_type, raw FROM translation_rows
            WHERE locked = 0 AND row_type IN ({','.join('?' * len(keys))})
              AND (translated != '' OR mtl != '')
              AND raw IN (SELECT raw FROM translation_rows WHERE row_type IN ({','.join('?' * len(refs))}))
        """, keys + refs).fetchall()
    return [f"[KEY] Row #{r[0]} ({r[1]}) [{r[2]}] '{r[3]}' đã dịch nhưng vẫn bị lệnh khác tham chiếu" for r in rows]


def check_translations(db_path, max_line_chars=0) -> dict:
    counts = {}
    with connect(db_path) as conn:
        for raw, trans, mtl, rt in conn.execute(
                "SELECT raw, translated, mtl, row_type FROM translation_rows WHERE locked = 0 AND status > 0"):
            for f in qa_flags(raw, trans or mtl, rt, max_line_chars):
                counts[f] = counts.get(f, 0) + 1
    return counts


def validate_project(project_dir, db_path, max_line_chars=0) -> dict:
    original = os.path.join(project_dir, 'dump_original')
    dump_errors = sorted(check_dump(load_dump(original))) if os.path.isdir(original) else []
    return {
        "dump_errors_in_original": dump_errors,
        "key_errors": check_key_consistency(db_path),
        "qa_counts": check_translations(db_path, max_line_chars),
    }


def main():
    ap = argparse.ArgumentParser(description="Validate a Nelir-Wolf project")
    ap.add_argument("--project", required=True, help="project id under projects/")
    args = ap.parse_args()
    if not config.is_valid_project_id(args.project):
        sys.exit("Project id không hợp lệ")
    pdir = os.path.join(config.PROJECTS_DIR, args.project)
    report = validate_project(pdir, os.path.join(pdir, 'translation.db'))
    print(f"Lỗi sẵn có trong dump gốc: {len(report['dump_errors_in_original'])}")
    for e in report['dump_errors_in_original'][:20]:
        print("  ", e)
    print(f"Lỗi khóa logic: {len(report['key_errors'])}")
    for e in report['key_errors'][:20]:
        print("  ", e)
    print("QA:", report['qa_counts'])
    sys.exit(1 if report['key_errors'] else 0)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    main()
