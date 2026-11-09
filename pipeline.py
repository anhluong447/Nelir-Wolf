"""Translation workflow: selection -> translation memory -> AI (unique texts only) -> QA -> DB.

Every function takes an explicit db_path so a running job never follows a project
switch made in the UI.
"""
from collections import Counter
from typing import Iterator, List, Optional

import config
from config import STATUS_EMPTY, STATUS_MTL, STATUS_QA, STATUS_REVIEWED
from db import connect
from openrouter import TranslationAPIError
from qa import is_blocking, qa_flags


def machine_status(raw, text, row_type, max_line_chars):
    flags = qa_flags(raw, text, row_type, max_line_chars)
    return (STATUS_QA if is_blocking(flags) else STATUS_MTL), ",".join(flags)


def load_glossary(db_path) -> List[tuple]:
    with connect(db_path) as conn:
        return [(s, d) for s, d in conn.execute("SELECT src, dst FROM glossary ORDER BY length(src) DESC")]


def select_rows(db_path, file: Optional[str] = None, overwrite=False, types: Optional[List[str]] = None,
                row_ids: Optional[List[int]] = None) -> list:
    cond = ["locked = 0"]
    params = []
    for f in config.EXCLUDED_FILES:
        cond.append("file NOT LIKE ?")
        params.append(f"%{f}")
    if row_ids is not None:
        if not row_ids:
            return []
        cond.append(f"id IN ({','.join('?' * len(row_ids))})")
        params.extend(row_ids)
    if file and file != "ALL":
        cond.append("file = ?")
        params.append(file)
    if not overwrite:
        cond.append("status IN (0, 3)")
    if types:
        cond.append(f"row_type IN ({','.join('?' * len(types))})")
        params.extend(types)
    sql = (f"SELECT id, file, raw, translated, status, row_type FROM translation_rows "
           f"WHERE {' AND '.join(cond)} ORDER BY file, id")
    with connect(db_path) as conn:
        return conn.execute(sql, params).fetchall()


def apply_memory(db_path, rows, max_line_chars) -> tuple:
    """Fill rows from existing translations of the same raw text.
    Returns (filled_rows, remaining_rows)."""
    raws = list({r[2] for r in rows})
    memory = {}
    with connect(db_path) as conn:
        for i in range(0, len(raws), 500):
            chunk = raws[i:i + 500]
            for raw, text, status in conn.execute(
                    f"SELECT raw, CASE WHEN translated != '' THEN translated ELSE mtl END, status "
                    f"FROM translation_rows WHERE status IN (1, 2) AND locked = 0 "
                    f"AND raw IN ({','.join('?' * len(chunk))})", chunk):
                if not text:
                    continue
                best = memory.get(raw)
                # Prefer reviewed translations, then the first one found.
                if best is None or (status == STATUS_REVIEWED and best[1] != STATUS_REVIEWED):
                    memory[raw] = (text, status)
        filled, remaining = [], []
        for row in rows:
            rid, _f, raw, _t, _s, rt = row
            hit = memory.get(raw)
            if not hit:
                remaining.append(row)
                continue
            text, src_status = hit
            status, flags = machine_status(raw, text, rt, max_line_chars)
            if status != STATUS_QA and src_status == STATUS_REVIEWED:
                status = STATUS_REVIEWED
            conn.execute("UPDATE translation_rows SET mtl = ?, translated = ?, status = ?, qa_flags = ? WHERE id = ?",
                         (text, text, status, flags, rid))
            filled.append({"id": rid, "raw": raw, "translated": text, "status": status})
    return filled, remaining


def write_results(db_path, rows_by_raw, results: dict, auto_fill, overwrite, max_line_chars) -> list:
    items = []
    with connect(db_path) as conn:
        for raw, mtl_text in results.items():
            for rid, _f, _raw, cur_trans, cur_status, rt in rows_by_raw[raw]:
                keep_human = cur_status == STATUS_REVIEWED and cur_trans.strip() and not overwrite
                if keep_human or not auto_fill:
                    final = cur_trans
                else:
                    final = mtl_text
                if keep_human:
                    status, flags = STATUS_REVIEWED, ",".join(qa_flags(raw, cur_trans, rt, max_line_chars))
                else:
                    status, flags = machine_status(raw, final or mtl_text, rt, max_line_chars)
                conn.execute(
                    "UPDATE translation_rows SET mtl = ?, translated = ?, status = ?, qa_flags = ? WHERE id = ?",
                    (mtl_text, final, status, flags, rid))
                items.append({"id": rid, "raw": raw, "translated": final or mtl_text, "status": status})
    return items


def run_translation(db_path, rows, translator, batch_size=15, auto_fill=True, overwrite=False,
                    max_line_chars=0, use_memory=True) -> Iterator[dict]:
    """Generator of progress events. Rows come from select_rows()."""
    total = len(rows)
    yield {"type": "start", "total": total}
    if total == 0:
        yield {"type": "complete", "total_translated": 0, "qa": 0, "message": "Không có dòng nào cần dịch."}
        return

    done = 0
    qa_count = 0
    if use_memory and not overwrite:
        filled, rows = apply_memory(db_path, rows, max_line_chars)
        if filled:
            done += len(filled)
            qa_count += sum(1 for it in filled if it["status"] == STATUS_QA)
            yield {"type": "memory", "count": len(filled),
                   "message": f"♻️ Bộ nhớ dịch: điền sẵn {len(filled)} dòng trùng với câu đã dịch."}
            yield {"type": "progress", "done": done, "total": total, "percent": round(done / total * 100, 1),
                   "current_file": "", "batch_size": len(filled), "items": filled[:50]}

    rows_by_raw = {}
    for row in rows:
        rows_by_raw.setdefault(row[2], []).append(row)
    unique_raws = list(rows_by_raw.keys())  # insertion order == scene order
    if len(unique_raws) < len(rows):
        yield {"type": "memory", "count": len(rows) - len(unique_raws),
               "message": f"♻️ Khử trùng lặp: {len(rows)} dòng → {len(unique_raws)} câu duy nhất gửi lên AI."}

    for i in range(0, len(unique_raws), batch_size):
        chunk = unique_raws[i:i + batch_size]
        events = []

        def on_fallback(from_m, to_m, nv_num, reason="Rate Limit"):
            events.append({"type": "fallback", "from_model": from_m, "to_model": to_m, "priority": nv_num,
                           "reason": reason,
                           "message": f"⚠️ Model {from_m} gặp sự cố [{reason}]! Chuyển sang NV{nv_num} ({to_m})."})

        def on_key_rotate(old_idx, new_idx, old_masked, new_masked, reason=""):
            if translator.on_key_rotate:
                translator.on_key_rotate(old_idx, new_idx, old_masked, new_masked, reason)
            events.append({"type": "key_rotate", "old_idx": old_idx, "new_idx": new_idx,
                           "message": f"🔑 Key #{old_idx} ({old_masked}) lỗi [{reason}] → chuyển sang Key #{new_idx} ({new_masked})."})

        try:
            translations = translator.translate_batch(chunk, on_fallback=on_fallback, on_key_rotate=on_key_rotate)
        except TranslationAPIError as err:
            yield from events
            yield {"type": "error", "code": err.status_code, "message": err.message, "done": done}
            return
        except Exception as err:  # noqa: BLE001 - surfaced to the UI
            yield from events
            yield {"type": "error", "code": 500, "message": str(err), "done": done}
            return
        yield from events

        items = write_results(db_path, rows_by_raw, dict(zip(chunk, translations)), auto_fill, overwrite,
                              max_line_chars)
        done += len(items)
        qa_count += sum(1 for it in items if it["status"] == STATUS_QA)
        current_file = rows_by_raw[chunk[0]][0][1] if chunk else ""
        yield {"type": "progress", "done": done, "total": total, "percent": round(done / total * 100, 1),
               "current_file": current_file, "batch_size": len(items), "items": items}

    msg = f"Hoàn thành dịch {done} dòng!"
    if qa_count:
        msg += f" ({qa_count} dòng không đạt QA, lọc trạng thái ⚠ để xem lại)"
    yield {"type": "complete", "total_translated": done, "qa": qa_count, "message": msg}


# ---------------------------------------------------------------------------
# Maintenance
# ---------------------------------------------------------------------------
def recheck_qa(db_path, max_line_chars=0) -> dict:
    """Re-run QA on machine rows (status 1/3) and refresh flags on reviewed rows."""
    changed = Counter()
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, raw, translated, mtl, status, row_type FROM translation_rows WHERE status > 0").fetchall()
        for rid, raw, trans, mtl, status, rt in rows:
            text = trans or mtl
            if not text:
                conn.execute("UPDATE translation_rows SET status = 0, qa_flags = '' WHERE id = ?", (rid,))
                changed["reset"] += 1
                continue
            flags = qa_flags(raw, text, rt, max_line_chars)
            if status == STATUS_REVIEWED:
                new_status = STATUS_REVIEWED
            else:
                new_status = STATUS_QA if is_blocking(flags) else STATUS_MTL
            conn.execute("UPDATE translation_rows SET status = ?, qa_flags = ? WHERE id = ?",
                         (new_status, ",".join(flags), rid))
            if new_status != status:
                changed[f"{status}->{new_status}"] += 1
    return dict(changed)


def unify_duplicates(db_path, max_line_chars=0) -> dict:
    """Give every unreviewed row the preferred translation of its raw text
    (most common reviewed version, else most common machine version that passes QA)."""
    updated = 0
    groups = 0
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, raw, CASE WHEN translated != '' THEN translated ELSE mtl END, status, row_type "
            "FROM translation_rows WHERE locked = 0 AND status > 0").fetchall()
        by_raw = {}
        for r in rows:
            by_raw.setdefault(r[1], []).append(r)
        for raw, items in by_raw.items():
            if len({it[2] for it in items}) < 2:
                continue
            reviewed = Counter(it[2] for it in items if it[3] == STATUS_REVIEWED and it[2])
            machine = Counter(it[2] for it in items if it[3] == STATUS_MTL and it[2])
            pool = reviewed or machine
            if not pool:
                continue
            preferred = pool.most_common(1)[0][0]
            groups += 1
            for rid, _raw, text, status, rt in items:
                if status == STATUS_REVIEWED or text == preferred:
                    continue
                new_status, flags = machine_status(raw, preferred, rt, max_line_chars)
                if reviewed and new_status != STATUS_QA:
                    new_status = STATUS_REVIEWED
                conn.execute(
                    "UPDATE translation_rows SET mtl = ?, translated = ?, status = ?, qa_flags = ? WHERE id = ?",
                    (preferred, preferred, new_status, flags, rid))
                updated += 1
    return {"groups": groups, "updated": updated}


def repair_escaped_newlines(db_path) -> int:
    """Fix stored AI output that contains a literal backslash-n instead of a line break."""
    from openrouter import align_translation_to_raw
    fixed = 0
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT id, raw, mtl, translated FROM translation_rows "
            "WHERE instr(raw, char(10)) > 0 AND (instr(mtl, '\\n') > 0 OR instr(translated, '\\n') > 0)").fetchall()
        for rid, raw, mtl, trans in rows:
            if "\\n" in raw:
                continue
            new_mtl = align_translation_to_raw(raw, mtl) if "\\n" in mtl else mtl
            new_trans = align_translation_to_raw(raw, trans) if "\\n" in trans else trans
            if (new_mtl, new_trans) != (mtl, trans):
                conn.execute("UPDATE translation_rows SET mtl = ?, translated = ? WHERE id = ?",
                             (new_mtl, new_trans, rid))
                fixed += 1
    return fixed


def migrate_status_semantics(db_path, max_line_chars=0) -> dict:
    """One-time upgrade from the old scheme where every AI result was status 2.
    Rows whose translation equals the AI output were never edited -> status 1."""
    with connect(db_path) as conn:
        demoted = conn.execute(
            "UPDATE translation_rows SET status = 1 WHERE status = 2 AND mtl != '' AND translated = mtl").rowcount
    repaired = repair_escaped_newlines(db_path)
    result = recheck_qa(db_path, max_line_chars)
    result["demoted_to_mtl"] = demoted
    result["repaired_newlines"] = repaired
    return result
