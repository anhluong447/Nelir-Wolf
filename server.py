"""FastAPI backend for Nelir Wolf Translator."""
import json
import os
import tempfile
import time
from typing import List, Optional

import requests
import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import config
import pipeline
from bridge import NoActiveProject, WolfBridge
from config import STATUS_EMPTY, STATUS_MTL, STATUS_QA, STATUS_REVIEWED
from db import connect, status_counts
from extractor import WolfTLError
from openrouter import OpenRouterTranslator, TranslationAPIError, test_connection
from qa import FLAG_LABELS, qa_flags

bridge = WolfBridge(config.ROOT_DIR)
app = FastAPI(title="Nelir Wolf Translator")
os.makedirs(config.STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


@app.exception_handler(NoActiveProject)
def _no_project(_req: Request, exc: NoActiveProject):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(WolfTLError)
def _wolftl_error(_req: Request, exc: WolfTLError):
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.on_event("startup")
def startup_event():
    if bridge.ctx:
        bridge.prepare_active_project()


@app.get("/")
def get_index():
    return FileResponse(os.path.join(config.STATIC_DIR, "index.html"))


def _check_project_id(project_id: str):
    if not config.is_valid_project_id(project_id):
        raise HTTPException(status_code=400, detail=f"ID dự án không hợp lệ: '{project_id}'")


def _switch_project(project_id: str):
    bridge.load_active_project(project_id)
    return bridge.prepare_active_project()


# ==========================================
# PROJECTS & .NEL
# ==========================================
class ProjectSelectRequest(BaseModel):
    project_id: str


class ProjectCreateRequest(BaseModel):
    name: str
    game_path: str


class GamePathRequest(BaseModel):
    game_path: str


class ReextractRequest(BaseModel):
    from_game: bool = False


@app.get("/api/projects")
def get_projects():
    projects = bridge.pm.list_projects()
    active = next((p for p in projects if p["is_active"]), None)
    return {"active_project_id": bridge.project_id, "active_project": active, "projects": projects}


@app.post("/api/projects/select")
def select_project(req: ProjectSelectRequest):
    _check_project_id(req.project_id)
    try:
        report = _switch_project(req.project_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"success": True, "active_project": bridge.pm.get_project(req.project_id), "report": report}


@app.post("/api/projects/create")
def create_project(req: ProjectCreateRequest):
    try:
        new_proj = bridge.pm.create_project(req.name, req.game_path)
    except (ValueError, WolfTLError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    report = _switch_project(new_proj["id"])
    return {"success": True, "project": bridge.pm.get_project(new_proj["id"]), "report": report}


@app.post("/api/projects/game-path")
def update_game_path(req: GamePathRequest):
    ctx = bridge.require()
    try:
        proj = bridge.pm.update_game_path(ctx.project_id, req.game_path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    bridge.load_active_project(ctx.project_id)
    return {"success": True, "project": proj}


@app.post("/api/projects/reextract")
def reextract(req: ReextractRequest):
    try:
        stats = bridge.reextract(from_game=req.from_game)
    except WolfTLError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True, "stats": stats}


@app.get("/api/projects/export-nel")
def export_nel(project_id: Optional[str] = Query(None)):
    target_id = project_id or bridge.require().project_id
    _check_project_id(target_id)
    try:
        nel_path = bridge.pm.export_nel(target_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    filename = os.path.basename(nel_path)
    return FileResponse(nel_path, media_type="application/octet-stream", filename=filename)


@app.post("/api/projects/import-nel")
async def import_nel(file: UploadFile = File(...), override_game_path: Optional[str] = Form(None)):
    fd, tmp_path = tempfile.mkstemp(suffix=".nel")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(await file.read())
        try:
            imported = bridge.pm.import_nel(tmp_path, override_game_path)
        except (ValueError, WolfTLError) as e:
            raise HTTPException(status_code=400, detail=str(e))
    finally:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
    report = _switch_project(imported["id"])
    return {"success": True, "project": imported, "warning": imported.get("warning", ""), "report": report}


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    _check_project_id(project_id)
    try:
        bridge.pm.delete_project(project_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"success": True}


# ==========================================
# ROWS
# ==========================================
@app.get("/api/stats")
def get_stats():
    with connect(bridge.db_path) as conn:
        return status_counts(conn)


@app.get("/api/files")
def get_files():
    with connect(bridge.db_path) as conn:
        rows = conn.execute("""
            SELECT file, category, COUNT(*),
                   SUM(CASE WHEN status IN (1, 2) AND locked = 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN locked = 0 THEN 1 ELSE 0 END)
            FROM translation_rows GROUP BY file ORDER BY category, file
        """).fetchall()
    return [{"file": r[0], "category": r[1], "total": r[2], "translated": r[3] or 0, "translatable": r[4] or 0}
            for r in rows]


class QueryParams(BaseModel):
    page: int = 1
    page_size: int = 50
    file: Optional[str] = None
    category: Optional[str] = None
    status: int = -1
    search: Optional[str] = None


# status filter value -> SQL condition
STATUS_FILTERS = {
    0: "status = 0 AND locked = 0",
    1: "status = 1 AND locked = 0",
    2: "status = 2 AND locked = 0",
    3: "status = 3 AND locked = 0",
    4: "status IN (0, 1, 3) AND locked = 0",   # chưa duyệt
    5: "locked = 1",
}


def _row_dict(r):
    return {"id": r[0], "file": r[1], "category": r[2], "path": r[3], "row_type": r[4], "raw": r[5],
            "mtl": r[6], "translated": r[7], "status": r[8], "locked": bool(r[9]),
            "qa_flags": [f for f in (r[10] or "").split(",") if f]}


ROW_COLUMNS = "id, file, category, path, row_type, raw, mtl, translated, status, locked, qa_flags"


@app.post("/api/rows")
def get_rows(q: QueryParams):
    conditions, params = [], []
    if q.file:
        conditions.append("file = ?")
        params.append(q.file)
    if q.category:
        conditions.append("category = ?")
        params.append(q.category)
    if q.status in STATUS_FILTERS:
        conditions.append(STATUS_FILTERS[q.status])
    if q.search:
        s = f"%{q.search}%"
        conditions.append("(raw LIKE ? OR mtl LIKE ? OR translated LIKE ?)")
        params.extend([s, s, s])
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    page_size = min(max(1, q.page_size), 500)
    with connect(bridge.db_path) as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM translation_rows {where}", params).fetchone()[0]
        rows = conn.execute(f"SELECT {ROW_COLUMNS} FROM translation_rows {where} ORDER BY id LIMIT ? OFFSET ?",
                            params + [page_size, (max(1, q.page) - 1) * page_size]).fetchall()
    return {"page": q.page, "page_size": page_size, "total": total, "rows": [_row_dict(r) for r in rows],
            "flag_labels": FLAG_LABELS}


class RowUpdate(BaseModel):
    id: int
    translated: Optional[str] = None


@app.post("/api/rows/update")
def update_row(u: RowUpdate):
    """Manual edit: non-empty text => reviewed (2); QA flags are kept as warnings."""
    if u.translated is None:
        raise HTTPException(status_code=400, detail="Thiếu nội dung bản dịch")
    with connect(bridge.db_path) as conn:
        row = conn.execute("SELECT raw, mtl, locked, row_type FROM translation_rows WHERE id = ?",
                           (u.id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Không tìm thấy dòng")
        raw, mtl, locked, rt = row
        if locked:
            raise HTTPException(status_code=400, detail="Dòng này bị khóa (là khóa logic của game), không được dịch.")
        text = u.translated
        if text.strip():
            status, flags = STATUS_REVIEWED, ",".join(qa_flags(raw, text, rt, bridge.max_line_chars()))
        elif mtl.strip():
            status, flags = pipeline.machine_status(raw, mtl, rt, bridge.max_line_chars())
        else:
            status, flags = STATUS_EMPTY, ""
        conn.execute("UPDATE translation_rows SET translated = ?, status = ?, qa_flags = ? WHERE id = ?",
                     (text, status, flags, u.id))
        r = conn.execute(f"SELECT {ROW_COLUMNS} FROM translation_rows WHERE id = ?", (u.id,)).fetchone()
    return {"success": True, "row": _row_dict(r)}


class ConfirmRequest(BaseModel):
    ids: List[int]


@app.post("/api/rows/confirm")
def confirm_rows(req: ConfirmRequest):
    """Mark machine rows as reviewed, copying the MTL into the translation if needed."""
    if not req.ids:
        return {"success": True, "affected": 0}
    ph = ",".join("?" * len(req.ids))
    with connect(bridge.db_path) as conn:
        affected = conn.execute(f"""
            UPDATE translation_rows
            SET translated = CASE WHEN translated = '' THEN mtl ELSE translated END, status = 2
            WHERE id IN ({ph}) AND locked = 0 AND (translated != '' OR mtl != '')
        """, req.ids).rowcount
    return {"success": True, "affected": affected}


class ClearRequest(BaseModel):
    target: str  # "row", "file", "range", "type", "all"
    row_id: Optional[int] = None
    file: Optional[str] = None
    start_id: Optional[int] = None
    end_id: Optional[int] = None
    row_types: Optional[List[str]] = None
    clear_type: str  # "mtl_only", "trans_only", "both"


CLEAR_SQL = {
    "mtl_only": "mtl = '', status = CASE WHEN translated = '' THEN 0 ELSE status END",
    "trans_only": "translated = '', status = CASE WHEN mtl = '' THEN 0 WHEN status = 2 THEN 1 ELSE status END",
    "both": "mtl = '', translated = '', status = 0",
}


@app.post("/api/rows/clear")
def clear_rows(req: ClearRequest):
    conditions, params = [], []
    if req.target == "row" and req.row_id is not None:
        conditions.append("id = ?")
        params.append(req.row_id)
    elif req.target == "file" and req.file:
        conditions.append("file = ?")
        params.append(req.file)
    elif req.target in ("range", "type", "all"):
        if req.target != "all" and req.file and req.file != "ALL":
            conditions.append("file = ?")
            params.append(req.file)
        if req.target == "range":
            if req.start_id is None and req.end_id is None:
                raise HTTPException(status_code=400, detail="Cần ít nhất một mốc ID")
            if req.start_id is not None:
                conditions.append("id >= ?")
                params.append(req.start_id)
            if req.end_id is not None:
                conditions.append("id <= ?")
                params.append(req.end_id)
    else:
        raise HTTPException(status_code=400, detail="Target không hợp lệ")
    if req.row_types:
        conditions.append(f"row_type IN ({','.join('?' * len(req.row_types))})")
        params.extend(req.row_types)
    if req.clear_type not in CLEAR_SQL:
        raise HTTPException(status_code=400, detail="Loại xóa không hợp lệ")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    with connect(bridge.db_path) as conn:
        affected = conn.execute(f"UPDATE translation_rows SET {CLEAR_SQL[req.clear_type]} {where}", params).rowcount
        conn.execute("UPDATE translation_rows SET qa_flags = '' WHERE status = 0")
    return {"success": True, "affected": affected}


@app.get("/api/types/stats")
def get_types_stats(file: Optional[str] = Query(None)):
    where, params = "", []
    if file and file != "ALL":
        where, params = "WHERE file = ?", [file]
    with connect(bridge.db_path) as conn:
        rows = conn.execute(f"""
            SELECT row_type, COUNT(*),
                   SUM(CASE WHEN status > 0 THEN 1 ELSE 0 END),
                   SUM(CASE WHEN status IN (0, 3) AND locked = 0 THEN 1 ELSE 0 END),
                   SUM(locked)
            FROM translation_rows {where} GROUP BY row_type ORDER BY COUNT(*) DESC
        """, params).fetchall()
    return [{"row_type": r[0] or "Unknown", "total": r[1], "translated": r[2] or 0, "empty": r[3] or 0,
             "locked": r[4] or 0, "translatable": (r[0] in config.TRANSLATABLE_TYPES)} for r in rows]


# ==========================================
# TRANSLATION
# ==========================================
def _persist_key_rotation(_old_idx, new_idx, *_args):
    keys = json.loads(bridge.get_setting("gemini_keys") or "[]")
    idx = new_idx - 1
    bridge.set_setting("gemini_active_key_index", str(idx))
    if 0 <= idx < len(keys):
        bridge.set_setting("gemini_key", keys[idx])


def _gemini_keys() -> list:
    try:
        keys = json.loads(bridge.get_setting("gemini_keys") or "[]")
    except ValueError:
        keys = []
    if not keys and bridge.get_setting("gemini_key"):
        keys = [bridge.get_setting("gemini_key")]
    return [k for k in keys if isinstance(k, str) and k.strip()]


def get_translator(db_path: str) -> OpenRouterTranslator:
    provider = bridge.get_setting("active_provider")
    prompt = bridge.get_setting("system_prompt")
    glossary = pipeline.load_glossary(db_path)
    if provider == "gemini":
        models = [bridge.get_setting(f"gemini_model_{i}").strip() for i in range(1, 6)]
        return OpenRouterTranslator(_gemini_keys(), [m for m in models if m], prompt,
                                    bridge.get_setting("gemini_base_url"),
                                    active_key_index=int(bridge.get_setting("gemini_active_key_index") or 0),
                                    glossary=glossary, on_key_rotate=_persist_key_rotation)
    if provider == "kaggle":
        base = bridge.get_setting("kaggle_base_url")
        if not base:
            raise HTTPException(status_code=400, detail="Chưa cấu hình Base URL cho Kaggle/Local LLM.")
        return OpenRouterTranslator(bridge.get_setting("kaggle_key"), bridge.get_setting("kaggle_model"), prompt,
                                    base, glossary=glossary)
    return OpenRouterTranslator(bridge.get_setting("openrouter_key"), bridge.get_setting("openrouter_model"),
                                prompt, bridge.get_setting("openrouter_base_url"), glossary=glossary)


def _batch_size() -> int:
    try:
        return min(max(1, int(bridge.get_setting("batch_size"))), 100)
    except ValueError:
        return 15


class TranslateSingleRequest(BaseModel):
    id: int


@app.post("/api/translate/single")
def translate_single(req: TranslateSingleRequest):
    db_path = bridge.db_path
    rows = pipeline.select_rows(db_path, overwrite=True, row_ids=[req.id])
    if not rows:
        raise HTTPException(status_code=404, detail="Không tìm thấy dòng hoặc dòng đang bị khóa")
    tr = get_translator(db_path)
    try:
        text = tr.translate_single(rows[0][2])
    except TranslationAPIError as err:
        raise HTTPException(status_code=502, detail=f"Lỗi AI ({err.status_code}): {err.message}")
    pipeline.write_results(db_path, {rows[0][2]: rows}, {rows[0][2]: text}, auto_fill=True, overwrite=False,
                           max_line_chars=bridge.max_line_chars())
    with connect(db_path) as conn:
        r = conn.execute(f"SELECT {ROW_COLUMNS} FROM translation_rows WHERE id = ?", (req.id,)).fetchone()
    return _row_dict(r)


class TranslateBatchRequest(BaseModel):
    row_ids: List[int]


@app.post("/api/translate/batch")
def translate_batch(req: TranslateBatchRequest):
    db_path = bridge.db_path
    rows = pipeline.select_rows(db_path, row_ids=req.row_ids)
    tr = get_translator(db_path)
    last = {}
    for event in pipeline.run_translation(db_path, rows, tr, _batch_size(), auto_fill=True,
                                          max_line_chars=bridge.max_line_chars()):
        if event["type"] == "error":
            raise HTTPException(status_code=502, detail=f"Lỗi AI ({event['code']}): {event['message']}")
        last = event
    return {"success": True, "translated_count": last.get("total_translated", 0), "qa": last.get("qa", 0)}


@app.get("/api/translate/stream")
def stream_translate(
    file: Optional[str] = Query(None),
    overwrite: bool = Query(False),
    auto_fill: bool = Query(True),
    types: Optional[str] = Query(None),
):
    db_path = bridge.db_path  # snapshot: a project switch mid-run must not redirect writes
    type_list = [t.strip() for t in (types or "").split(",") if t.strip()] or None
    rows = pipeline.select_rows(db_path, file=file, overwrite=overwrite, types=type_list)
    tr = get_translator(db_path)
    batch_size, max_chars = _batch_size(), bridge.max_line_chars()
    label = file if file and file != "ALL" else "Toàn bộ Game"

    def event_stream():
        for event in pipeline.run_translation(db_path, rows, tr, batch_size, auto_fill, overwrite, max_chars):
            if event["type"] == "start":
                event["file"] = label
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


# ==========================================
# QUALITY / MEMORY / GLOSSARY
# ==========================================
@app.post("/api/qa/recheck")
def qa_recheck():
    return {"success": True, "changes": pipeline.recheck_qa(bridge.db_path, bridge.max_line_chars())}


@app.post("/api/tm/unify")
def tm_unify():
    return {"success": True, **pipeline.unify_duplicates(bridge.db_path, bridge.max_line_chars())}


@app.get("/api/validate")
def validate():
    from validator import validate_project
    ctx = bridge.require()
    return validate_project(ctx.project_dir, ctx.db_path, bridge.max_line_chars())


class GlossaryEntry(BaseModel):
    src: str
    dst: str
    note: Optional[str] = ""


class GlossaryRequest(BaseModel):
    entries: List[GlossaryEntry]


@app.get("/api/glossary")
def get_glossary():
    return {"entries": bridge.get_glossary()}


@app.post("/api/glossary")
def set_glossary(req: GlossaryRequest):
    return {"success": True, "count": bridge.set_glossary([e.dict() for e in req.entries])}


# ==========================================
# PATCH
# ==========================================
class PatchRequest(BaseModel):
    force: bool = False


@app.post("/api/patch")
def patch_game(req: Optional[PatchRequest] = None):
    try:
        return bridge.patch_to_game(force=bool(req and req.force))
    except WolfTLError as e:
        return {"success": False, "message": str(e)}


@app.post("/api/patch/restore")
def restore_original():
    try:
        return bridge.restore_original_text()
    except WolfTLError as e:
        return {"success": False, "message": str(e)}


# ==========================================
# SETTINGS
# ==========================================
class SettingsTestModel(BaseModel):
    provider: Optional[str] = "gemini"
    base_url: Optional[str] = ""
    api_key: Optional[str] = ""
    model: str


@app.post("/api/settings/test")
def test_ai_connection(s: SettingsTestModel):
    return test_connection(s.base_url, s.api_key, s.model, s.provider or "")


class SingleKeyTestModel(BaseModel):
    api_key: str
    base_url: Optional[str] = None
    model: Optional[str] = None


@app.post("/api/settings/test-key")
def test_single_key(req: SingleKeyTestModel):
    base_url = (req.base_url or config.GEMINI_BASE_URL).rstrip("/")
    payload = {"model": req.model or config.GEMINI_DEFAULT_MODELS[0],
               "messages": [{"role": "user", "content": "1"}], "temperature": 0.1, "max_tokens": 5}
    t0 = time.time()
    try:
        r = requests.post(f"{base_url}/chat/completions", json=payload, timeout=8,
                          headers={"Authorization": f"Bearer {req.api_key.strip()}",
                                   "Content-Type": "application/json"})
    except requests.exceptions.Timeout:
        return {"ok": False, "status_code": 408, "message": "❌ Timeout (8s)"}
    except Exception as e:
        return {"ok": False, "status_code": 500, "message": f"Lỗi: {str(e)[:30]}"}
    ms = round((time.time() - t0) * 1000)
    messages = {200: f"✅ Sẵn sàng ({ms}ms)", 429: "⚠️ Hết Quota (429)", 401: "❌ Key lỗi (401)",
                403: "❌ Key lỗi (403)", 404: "⚠️ Model không hỗ trợ (404)"}
    return {"ok": r.status_code == 200, "status_code": r.status_code,
            "message": messages.get(r.status_code, f"Lỗi {r.status_code}")}


class GeminiSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    keys: Optional[List[str]] = None
    active_key_index: Optional[int] = 0
    model_1: Optional[str] = None
    model_2: Optional[str] = None
    model_3: Optional[str] = None
    model_4: Optional[str] = None
    model_5: Optional[str] = None


class KaggleSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class OpenRouterSettings(BaseModel):
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


class FullSettingsModel(BaseModel):
    active_provider: Optional[str] = None
    batch_size: Optional[str] = None
    system_prompt: Optional[str] = None
    qa_max_line_chars: Optional[str] = None
    gemini: Optional[GeminiSettings] = None
    kaggle: Optional[KaggleSettings] = None
    openrouter: Optional[OpenRouterSettings] = None


def _set_or_default(key: str, value: Optional[str]):
    """Save a value; empty/None falls back to the documented default."""
    value = (value or "").strip()
    bridge.set_setting(key, value or config.DEFAULT_SETTINGS.get(key, ""))


@app.get("/api/settings")
def get_settings():
    g = bridge.get_setting
    provider = g("active_provider")
    keys = _gemini_keys()
    active_idx = min(max(0, int(g("gemini_active_key_index") or 0)), max(0, len(keys) - 1))
    key_tag = f"Key #{active_idx + 1}/{len(keys)}" if keys else "Chưa có Key"
    if provider == "gemini":
        display = f"Gemini: {g('gemini_model_1')} ({key_tag})"
    elif provider == "kaggle":
        display = f"Kaggle: {g('kaggle_model')}"
    else:
        display = f"OpenRouter: {g('openrouter_model')}"
    return {
        "active_provider": provider,
        "active_model_display": display,
        "batch_size": g("batch_size"),
        "system_prompt": g("system_prompt"),
        "default_system_prompt": config.DEFAULT_SYSTEM_PROMPT,
        "qa_max_line_chars": g("qa_max_line_chars"),
        "gemini": {"base_url": g("gemini_base_url"), "api_key": keys[active_idx] if keys else "", "keys": keys,
                   "active_key_index": active_idx, **{f"model_{i}": g(f"gemini_model_{i}") for i in range(1, 6)}},
        "kaggle": {"base_url": g("kaggle_base_url"), "api_key": g("kaggle_key"), "model": g("kaggle_model")},
        "openrouter": {"base_url": g("openrouter_base_url"), "api_key": g("openrouter_key"),
                       "model": g("openrouter_model")},
    }


@app.post("/api/settings")
def save_settings(s: FullSettingsModel):
    if s.active_provider in ("gemini", "kaggle", "openrouter"):
        bridge.set_setting("active_provider", s.active_provider)
    if s.batch_size is not None:
        _set_or_default("batch_size", s.batch_size if s.batch_size.strip().isdigit() else "")
    if s.system_prompt is not None:  # empty => back to the default prompt
        _set_or_default("system_prompt", s.system_prompt)
    if s.qa_max_line_chars is not None:
        _set_or_default("qa_max_line_chars", s.qa_max_line_chars if s.qa_max_line_chars.strip().isdigit() else "")

    if s.gemini:
        _set_or_default("gemini_base_url", s.gemini.base_url)
        if s.gemini.keys is not None:
            keys = [k.strip() for k in s.gemini.keys if k and k.strip()]
        elif s.gemini.api_key is not None:
            keys = [s.gemini.api_key.strip()] if s.gemini.api_key.strip() else []
        else:
            keys = None
        if keys is not None:
            idx = min(max(0, s.gemini.active_key_index or 0), max(0, len(keys) - 1))
            bridge.set_setting("gemini_keys", json.dumps(keys))
            bridge.set_setting("gemini_key", keys[idx] if keys else "")
            bridge.set_setting("gemini_active_key_index", str(idx))
        for i in range(1, 6):
            _set_or_default(f"gemini_model_{i}", getattr(s.gemini, f"model_{i}"))
    if s.kaggle:
        bridge.set_setting("kaggle_base_url", (s.kaggle.base_url or "").strip())
        _set_or_default("kaggle_key", s.kaggle.api_key)
        _set_or_default("kaggle_model", s.kaggle.model)
    if s.openrouter:
        _set_or_default("openrouter_base_url", s.openrouter.base_url)
        bridge.set_setting("openrouter_key", (s.openrouter.api_key or "").strip())
        _set_or_default("openrouter_model", s.openrouter.model)
    return {"success": True}


if __name__ == "__main__":
    print(f"Starting Nelir Wolf Translator on http://{config.HOST}:{config.PORT} ...")
    uvicorn.run(app, host=config.HOST, port=config.PORT)
