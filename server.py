import os
import json
import requests
import time
import sqlite3
import uvicorn
import tempfile
from fastapi import FastAPI, BackgroundTasks, HTTPException, Query, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel
from typing import List, Optional

from bridge import WolfBridge
from openrouter import OpenRouterTranslator, TranslationAPIError, test_connection

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
bridge = WolfBridge(ROOT_DIR)

app = FastAPI(title="Nelir Wolf Translator")

# Serve static files
static_dir = os.path.join(ROOT_DIR, "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.on_event("startup")
def startup_event():
    bridge.extract_strings_to_db(force=False)

@app.get("/")
def get_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

# ==========================================
# PROJECT MANAGEMENT & .NEL APIS
# ==========================================
class ProjectSelectRequest(BaseModel):
    project_id: str

class ProjectCreateRequest(BaseModel):
    name: str
    game_path: str

@app.get("/api/projects")
def get_projects():
    projects = bridge.pm.list_projects()
    active_proj = bridge.pm.get_active_project()
    return {
        "active_project_id": bridge.project_id,
        "active_project": active_proj,
        "projects": projects
    }

@app.post("/api/projects/select")
def select_project(req: ProjectSelectRequest):
    bridge.load_active_project(req.project_id)
    return {
        "success": True,
        "active_project": bridge.pm.get_active_project()
    }

@app.post("/api/projects/create")
def create_project(req: ProjectCreateRequest):
    try:
        new_proj = bridge.pm.create_project(req.name, req.game_path, extract_now=True)
        bridge.load_active_project(new_proj["id"])
        bridge.extract_strings_to_db(force=False)
        return {"success": True, "project": new_proj}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/projects/export-nel")
def export_nel(project_id: Optional[str] = Query(None)):
    target_id = project_id or bridge.project_id
    try:
        nel_path = bridge.pm.export_nel(target_id)
        filename = os.path.basename(nel_path)
        return FileResponse(
            nel_path,
            media_type="application/octet-stream",
            filename=filename,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/projects/import-nel")
async def import_nel(file: UploadFile = File(...), override_game_path: Optional[str] = Form(None)):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".nel") as tmp:
            tmp_path = tmp.name
            content = await file.read()
            tmp.write(content)

        imported_proj = bridge.pm.import_nel(tmp_path, override_game_path)
        bridge.load_active_project(imported_proj["id"])
        bridge.extract_strings_to_db(force=False)
        
        try:
            os.remove(tmp_path)
        except Exception:
            pass

        return {"success": True, "project": imported_proj}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str):
    try:
        bridge.pm.delete_project(project_id)
        return {"success": True}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/stats")
def get_stats():
    with sqlite3.connect(bridge.db_path) as conn:
        total = conn.execute("SELECT COUNT(*) FROM translation_rows").fetchone()[0]
        empty = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 0").fetchone()[0]
        mtl = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 1").fetchone()[0]
        translated = conn.execute("SELECT COUNT(*) FROM translation_rows WHERE status = 2").fetchone()[0]
    return {
        "total": total,
        "empty": empty,
        "mtl": mtl,
        "translated": translated,
        "completed": mtl + translated
    }

@app.get("/api/files")
def get_files():
    with sqlite3.connect(bridge.db_path) as conn:
        cursor = conn.execute("""
            SELECT file, category, COUNT(*) as total,
                   SUM(CASE WHEN status > 0 THEN 1 ELSE 0 END) as translated_count
            FROM translation_rows
            GROUP BY file
            ORDER BY category, file
        """)
        results = [
            {"file": r[0], "category": r[1], "total": r[2], "translated": r[3] or 0}
            for r in cursor.fetchall()
        ]
    return results

class QueryParams(BaseModel):
    page: int = 1
    page_size: int = 50
    file: Optional[str] = None
    category: Optional[str] = None
    status: int = -1
    search: Optional[str] = None

@app.post("/api/rows")
def get_rows(q: QueryParams):
    conditions = []
    params = []

    if q.file:
        conditions.append("file = ?")
        params.append(q.file)
    if q.category:
        conditions.append("category = ?")
        params.append(q.category)
    if q.status == 0:
        conditions.append("status = 0")
    elif q.status == 1:
        conditions.append("status = 1")
    elif q.status == 2:
        conditions.append("status = 2")
    elif q.status == 3:
        conditions.append("status IN (0, 1)")

    if q.search:
        s = f"%{q.search}%"
        conditions.append("(raw LIKE ? OR mtl LIKE ? OR translated LIKE ?)")
        params.extend([s, s, s])

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    with sqlite3.connect(bridge.db_path) as conn:
        count_sql = f"SELECT COUNT(*) FROM translation_rows {where_clause}"
        total_rows = conn.execute(count_sql, params).fetchone()[0]

        offset = (q.page - 1) * q.page_size
        sql = f"""
            SELECT id, file, category, path, row_type, raw, mtl, translated, status
            FROM translation_rows
            {where_clause}
            ORDER BY id
            LIMIT ? OFFSET ?
        """
        cursor = conn.execute(sql, params + [q.page_size, offset])
        rows = [
            {
                "id": r[0],
                "file": r[1],
                "category": r[2],
                "path": r[3],
                "row_type": r[4],
                "raw": r[5],
                "mtl": r[6],
                "translated": r[7],
                "status": r[8]
            }
            for r in cursor.fetchall()
        ]

    return {
        "page": q.page,
        "page_size": q.page_size,
        "total": total_rows,
        "rows": rows
    }

class RowUpdate(BaseModel):
    id: int
    translated: Optional[str] = None
    mtl: Optional[str] = None

@app.post("/api/rows/update")
def update_row(u: RowUpdate):
    with sqlite3.connect(bridge.db_path) as conn:
        if u.translated is not None:
            status = 2 if u.translated.strip() else (1 if u.mtl else 0)
            conn.execute(
                "UPDATE translation_rows SET translated = ?, status = ? WHERE id = ?",
                (u.translated, status, u.id)
            )
        elif u.mtl is not None:
            conn.execute(
                "UPDATE translation_rows SET mtl = ?, status = CASE WHEN translated != '' THEN 2 ELSE 1 END WHERE id = ?",
                (u.mtl, u.id)
            )
        conn.commit()
    return {"success": True}

class ClearRequest(BaseModel):
    target: str # "row", "file", "range", "type", "all"
    row_id: Optional[int] = None
    file: Optional[str] = None
    start_id: Optional[int] = None
    end_id: Optional[int] = None
    row_types: Optional[List[str]] = None
    clear_type: str # "mtl_only", "trans_only", "both"

@app.post("/api/rows/clear")
def clear_rows(req: ClearRequest):
    with sqlite3.connect(bridge.db_path) as conn:
        conditions = []
        params = []

        if req.target == "row" and req.row_id:
            conditions.append("id = ?")
            params.append(req.row_id)
        elif req.target == "file" and req.file:
            conditions.append("file = ?")
            params.append(req.file)
        elif req.target == "range":
            if req.file and req.file != "ALL":
                conditions.append("file = ?")
                params.append(req.file)
            if req.start_id is not None:
                conditions.append("id >= ?")
                params.append(req.start_id)
            if req.end_id is not None:
                conditions.append("id <= ?")
                params.append(req.end_id)
        elif req.target == "type":
            if req.file and req.file != "ALL":
                conditions.append("file = ?")
                params.append(req.file)
            if req.row_types and len(req.row_types) > 0:
                conditions.append(f"row_type IN ({','.join(['?']*len(req.row_types))})")
                params.extend(req.row_types)
        elif req.target == "all":
            if req.row_types and len(req.row_types) > 0:
                conditions.append(f"row_type IN ({','.join(['?']*len(req.row_types))})")
                params.extend(req.row_types)
        else:
            raise HTTPException(status_code=400, detail="Target không hợp lệ")

        if req.row_types and len(req.row_types) > 0 and req.target not in ("type", "all"):
            conditions.append(f"row_type IN ({','.join(['?']*len(req.row_types))})")
            params.extend(req.row_types)

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        if req.clear_type == "mtl_only":
            sql = f"""
                UPDATE translation_rows
                SET mtl = '',
                    status = CASE WHEN translated != '' THEN 2 ELSE 0 END
                {where}
            """
        elif req.clear_type == "trans_only":
            sql = f"""
                UPDATE translation_rows
                SET translated = '',
                    status = CASE WHEN mtl != '' THEN 1 ELSE 0 END
                {where}
            """
        elif req.clear_type == "both":
            sql = f"""
                UPDATE translation_rows
                SET mtl = '',
                    translated = '',
                    status = 0
                {where}
            """
        else:
            raise HTTPException(status_code=400, detail="Loại xóa không hợp lệ")

        cursor = conn.execute(sql, params)
        affected = cursor.rowcount
        conn.commit()

    return {"success": True, "affected": affected}

@app.get("/api/types/stats")
def get_types_stats(file: Optional[str] = Query(None)):
    with sqlite3.connect(bridge.db_path) as conn:
        conditions = []
        params = []
        if file and file != "ALL":
            conditions.append("file = ?")
            params.append(file)
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""
            SELECT row_type, 
                   COUNT(*) as total,
                   SUM(CASE WHEN status > 0 THEN 1 ELSE 0 END) as translated,
                   SUM(CASE WHEN status = 0 THEN 1 ELSE 0 END) as empty
            FROM translation_rows
            {where}
            GROUP BY row_type
            ORDER BY total DESC
        """
        rows = conn.execute(sql, params).fetchall()
        return [
            {
                "row_type": r[0] or "Unknown",
                "total": r[1],
                "translated": r[2] or 0,
                "empty": r[3] or 0
            }
            for r in rows
        ]

def get_translator() -> OpenRouterTranslator:
    provider = bridge.get_setting("active_provider", "gemini")
    sys_prompt = bridge.get_setting("system_prompt")

    if provider == "gemini":
        base_url = bridge.get_setting("gemini_base_url", "https://generativelanguage.googleapis.com/v1beta/openai")
        keys_json = bridge.get_setting("gemini_keys", "")
        keys_list = []
        if keys_json:
            try:
                keys_list = json.loads(keys_json)
            except Exception:
                pass
        if not keys_list:
            single = bridge.get_setting("gemini_key", "")
            if single:
                keys_list = [single]

        active_idx = int(bridge.get_setting("gemini_active_key_index", "0"))

        m1 = bridge.get_setting("gemini_model_1", "gemini-3.5-flash-lite")
        m2 = bridge.get_setting("gemini_model_2", "gemini-3-flash-preview")
        m3 = bridge.get_setting("gemini_model_3", "gemini-2.5-flash")
        m4 = bridge.get_setting("gemini_model_4", "gemini-3.1-flash-lite")
        m5 = bridge.get_setting("gemini_model_5", "gemini-2.5-flash-lite")
        models = [m.strip() for m in [m1, m2, m3, m4, m5] if m.strip()]
        return OpenRouterTranslator(keys_list or ["local"], models or ["gemini-3.5-flash-lite"], sys_prompt, base_url, active_key_index=active_idx)
    elif provider == "kaggle":
        base_url = bridge.get_setting("kaggle_base_url", "https://immune-passive-vegas-district.trycloudflare.com/v1")
        api_key = bridge.get_setting("kaggle_key", "local")
        model = bridge.get_setting("kaggle_model", "qwen2.5:32b")
        return OpenRouterTranslator(api_key, model, sys_prompt, base_url)
    else:
        base_url = bridge.get_setting("openrouter_base_url", "https://openrouter.ai/api/v1")
        api_key = bridge.get_setting("openrouter_key", "")
        model = bridge.get_setting("openrouter_model", "deepseek/deepseek-v4.1-flash-1017")
        return OpenRouterTranslator(api_key, model, sys_prompt, base_url)

class TranslateSingleRequest(BaseModel):
    id: int

@app.post("/api/translate/single")
def translate_single(req: TranslateSingleRequest):
    with sqlite3.connect(bridge.db_path) as conn:
        row = conn.execute("SELECT raw, translated FROM translation_rows WHERE id = ?", (req.id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Row not found")
        raw_text = row[0]
        cur_trans = row[1]

    tr = get_translator()
    try:
        translated_text = tr.translate_single(raw_text)
    except TranslationAPIError as err:
        raise HTTPException(status_code=400, detail=f"Lỗi AI ({err.status_code}): {err.message}")
    except Exception as err:
        raise HTTPException(status_code=500, detail=f"Lỗi dịch thuật: {str(err)}")

    new_trans = cur_trans if cur_trans.strip() else translated_text
    new_status = 2 if new_trans.strip() else 1

    with sqlite3.connect(bridge.db_path) as conn:
        conn.execute(
            "UPDATE translation_rows SET mtl = ?, translated = ?, status = ? WHERE id = ?",
            (translated_text, new_trans, new_status, req.id)
        )
        conn.commit()

    return {"id": req.id, "mtl": translated_text, "translated": new_trans, "status": new_status}

@app.get("/api/translate/stream")
def stream_translate(
    file: Optional[str] = Query(None),
    overwrite: bool = Query(False),
    auto_fill: bool = Query(True),
    types: Optional[str] = Query(None)
):
    def event_stream():
        batch_size = int(bridge.get_setting("batch_size", "15"))
        tr = get_translator()

        with sqlite3.connect(bridge.db_path) as conn:
            conditions = []
            params = []
            if file and file != "ALL":
                conditions.append("file = ?")
                params.append(file)
            conditions.append("file NOT LIKE '%CDataBase.json%'")
            if not overwrite:
                conditions.append("status = 0")
            if types:
                type_list = [t.strip() for t in types.split(",") if t.strip()]
                if type_list:
                    conditions.append(f"row_type IN ({','.join(['?']*len(type_list))})")
                    params.extend(type_list)

            where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
            sql = f"SELECT id, file, raw, translated FROM translation_rows {where} ORDER BY file, id"
            rows = conn.execute(sql, params).fetchall()

        total = len(rows)
        yield f"data: {json.dumps({'type': 'start', 'total': total, 'file': file or 'Toàn bộ Game'})}\n\n"

        if total == 0:
            yield f"data: {json.dumps({'type': 'complete', 'total_translated': 0, 'message': 'Không có dòng nào cần dịch.'})}\n\n"
            return

        total_done = 0
        for i in range(0, total, batch_size):
            chunk = rows[i:i + batch_size]
            chunk_ids = [r[0] for r in chunk]
            chunk_files = [r[1] for r in chunk]
            chunk_texts = [r[2] for r in chunk]
            chunk_trans = [r[3] for r in chunk]

            current_file_name = chunk_files[0] if chunk_files else ""
            fallback_events = []
            key_rotate_events = []

            def on_fallback(from_m, to_m, nv_num, reason="Rate Limit"):
                fallback_events.append((from_m, to_m, nv_num, reason))

            def on_key_rotate(old_idx, new_idx, old_masked, new_masked, reason="Quota Exceeded"):
                bridge.set_setting("gemini_active_key_index", str(new_idx - 1))
                if new_idx - 1 < len(tr.api_keys):
                    bridge.set_setting("gemini_key", tr.api_keys[new_idx - 1])
                key_rotate_events.append((old_idx, new_idx, old_masked, new_masked, reason))

            try:
                translations = tr.translate_batch(chunk_texts, on_fallback=on_fallback, on_key_rotate=on_key_rotate)
            except TranslationAPIError as err:
                yield f"data: {json.dumps({'type': 'error', 'code': err.status_code, 'message': err.message})}\n\n"
                return
            except Exception as err:
                yield f"data: {json.dumps({'type': 'error', 'code': 500, 'message': str(err)})}\n\n"
                return

            # Emit key rotation events first if any occurred
            for old_idx, new_idx, old_masked, new_masked, reason in key_rotate_events:
                yield f"data: {json.dumps({'type': 'key_rotate', 'old_idx': old_idx, 'new_idx': new_idx, 'old_key': old_masked, 'new_key': new_masked, 'reason': reason, 'message': f'🔑 Key #{old_idx} ({old_masked}) đã hết quota ngày! Tự động xoay sang Key #{new_idx} ({new_masked}) để tiếp tục dịch.'})}\n\n"

            # Emit model fallback notifications if any occurred
            for from_m, to_m, nv_num, reason in fallback_events:
                yield f"data: {json.dumps({'type': 'fallback', 'from_model': from_m, 'to_model': to_m, 'priority': nv_num, 'reason': reason, 'message': f'⚠️ Model {from_m} gặp sự cố [{reason}]! Đã tự động chuyển sang NV{nv_num} ({to_m}) cho batch này.'})}\n\n"

            batch_items = []
            with sqlite3.connect(bridge.db_path, check_same_thread=False) as conn:
                for row_id, raw_txt, mtl_txt, cur_trans in zip(chunk_ids, chunk_texts, translations, chunk_trans):
                    if auto_fill:
                        final_trans = mtl_txt if (overwrite or not cur_trans.strip()) else cur_trans
                        status = 2
                    else:
                        final_trans = cur_trans
                        status = 2 if cur_trans.strip() else 1

                    conn.execute(
                        "UPDATE translation_rows SET mtl = ?, translated = ?, status = ? WHERE id = ?",
                        (mtl_txt, final_trans, status, row_id)
                    )
                    batch_items.append({
                        "id": row_id,
                        "raw": raw_txt,
                        "translated": final_trans or mtl_txt
                    })

                conn.commit()
            total_done += len(chunk)
            percent = round((total_done / total) * 100, 1)

            yield f"data: {json.dumps({'type': 'progress', 'done': total_done, 'total': total, 'percent': percent, 'current_file': current_file_name, 'batch_size': len(chunk), 'items': batch_items})}\n\n"

        yield f"data: {json.dumps({'type': 'complete', 'total_translated': total_done, 'message': f'Hoàn thành dịch {total_done} dòng!'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/api/patch")
def patch_game():
    res = bridge.patch_to_game()
    return res

class SettingsTestModel(BaseModel):
    provider: Optional[str] = "gemini"
    base_url: Optional[str] = ""
    api_key: Optional[str] = ""
    model: str

@app.post("/api/settings/test")
def test_ai_connection(s: SettingsTestModel):
    res = test_connection(s.base_url, s.api_key, s.model)
    return res

class SingleKeyTestModel(BaseModel):
    api_key: str
    base_url: Optional[str] = "https://generativelanguage.googleapis.com/v1beta/openai"
    model: Optional[str] = "gemini-3.5-flash-lite"

@app.post("/api/settings/test-key")
def test_single_key(req: SingleKeyTestModel):
    base_url = (req.base_url or "https://generativelanguage.googleapis.com/v1beta/openai").rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {req.api_key.strip()}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": req.model or "gemini-3.5-flash-lite",
        "messages": [{"role": "user", "content": "1"}],
        "temperature": 0.1,
        "max_tokens": 5
    }
    t0 = time.time()
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=8)
        ms = round((time.time() - t0) * 1000)
        if r.status_code == 200:
            return {"ok": True, "status_code": 200, "message": f"✅ Sẵn sàng ({ms}ms)"}
        elif r.status_code == 429:
            return {"ok": False, "status_code": 429, "message": f"⚠️ Hết Quota (429)"}
        elif r.status_code in (401, 403):
            return {"ok": False, "status_code": r.status_code, "message": f"❌ Key lỗi ({r.status_code})"}
        elif r.status_code == 404:
            return {"ok": False, "status_code": 404, "message": f"⚠️ Model không hỗ trợ (404)"}
        else:
            return {"ok": False, "status_code": r.status_code, "message": f"Lỗi {r.status_code}"}
    except requests.exceptions.Timeout:
        return {"ok": False, "status_code": 408, "message": "❌ Timeout (8s)"}
    except Exception as e:
        return {"ok": False, "status_code": 500, "message": f"Lỗi: {str(e)[:30]}"}

class GeminiSettings(BaseModel):
    base_url: Optional[str] = "https://generativelanguage.googleapis.com/v1beta/openai"
    api_key: Optional[str] = ""
    keys: Optional[List[str]] = []
    active_key_index: Optional[int] = 0
    model_1: Optional[str] = "gemini-3.5-flash-lite"
    model_2: Optional[str] = "gemini-3-flash-preview"
    model_3: Optional[str] = "gemini-2.5-flash"
    model_4: Optional[str] = "gemini-3.1-flash-lite"
    model_5: Optional[str] = "gemini-2.5-flash-lite"

class KaggleSettings(BaseModel):
    base_url: Optional[str] = ""
    api_key: Optional[str] = "local"
    model: Optional[str] = "qwen2.5:32b"

class OpenRouterSettings(BaseModel):
    base_url: Optional[str] = "https://openrouter.ai/api/v1"
    api_key: Optional[str] = ""
    model: Optional[str] = "deepseek/deepseek-v4.1-flash-1017"

class FullSettingsModel(BaseModel):
    active_provider: Optional[str] = "gemini"
    batch_size: Optional[str] = "15"
    system_prompt: Optional[str] = ""
    gemini: Optional[GeminiSettings] = None
    kaggle: Optional[KaggleSettings] = None
    openrouter: Optional[OpenRouterSettings] = None

@app.get("/api/settings")
def get_settings():
    provider = bridge.get_setting("active_provider", "gemini")
    
    keys_json = bridge.get_setting("gemini_keys", "")
    gemini_keys_list = []
    if keys_json:
        try:
            gemini_keys_list = json.loads(keys_json)
        except Exception:
            pass
    if not gemini_keys_list:
        single = bridge.get_setting("gemini_key", "")
        if single:
            gemini_keys_list = [single]

    active_idx = int(bridge.get_setting("gemini_active_key_index", "0"))
    if gemini_keys_list:
        active_idx = min(max(0, active_idx), len(gemini_keys_list) - 1)
        cur_k = gemini_keys_list[active_idx]
        masked = cur_k[:6] + "..." + cur_k[-4:] if len(cur_k) > 10 else "***"
        key_tag = f"Key #{active_idx + 1}/{len(gemini_keys_list)}"
    else:
        key_tag = "Chưa có Key"

    if provider == "gemini":
        display = f"Gemini: {bridge.get_setting('gemini_model_1', 'gemini-3.5-flash-lite')} ({key_tag})"
    elif provider == "kaggle":
        display = f"Kaggle: {bridge.get_setting('kaggle_model', 'qwen2.5:32b')}"
    else:
        display = f"OpenRouter: {bridge.get_setting('openrouter_model', 'deepseek/deepseek-v4.1-flash-1017')}"

    return {
        "active_provider": provider,
        "active_model_display": display,
        "batch_size": bridge.get_setting("batch_size", "15"),
        "system_prompt": bridge.get_setting("system_prompt"),
        "gemini": {
            "base_url": bridge.get_setting("gemini_base_url", "https://generativelanguage.googleapis.com/v1beta/openai"),
            "api_key": bridge.get_setting("gemini_key", ""),
            "keys": gemini_keys_list,
            "active_key_index": active_idx,
            "model_1": bridge.get_setting("gemini_model_1", "gemini-3.5-flash-lite"),
            "model_2": bridge.get_setting("gemini_model_2", "gemini-3-flash-preview"),
            "model_3": bridge.get_setting("gemini_model_3", "gemini-2.5-flash"),
            "model_4": bridge.get_setting("gemini_model_4", "gemini-3.1-flash-lite"),
            "model_5": bridge.get_setting("gemini_model_5", "gemini-2.5-flash-lite"),
        },
        "kaggle": {
            "base_url": bridge.get_setting("kaggle_base_url", "https://immune-passive-vegas-district.trycloudflare.com/v1"),
            "api_key": bridge.get_setting("kaggle_key", "local"),
            "model": bridge.get_setting("kaggle_model", "qwen2.5:32b"),
        },
        "openrouter": {
            "base_url": bridge.get_setting("openrouter_base_url", "https://openrouter.ai/api/v1"),
            "api_key": bridge.get_setting("openrouter_key", ""),
            "model": bridge.get_setting("openrouter_model", "deepseek/deepseek-v4.1-flash-1017"),
        }
    }

@app.post("/api/settings")
def save_settings(s: FullSettingsModel):
    if s.active_provider:
        bridge.set_setting("active_provider", s.active_provider)
    if s.batch_size:
        bridge.set_setting("batch_size", s.batch_size)
    if s.system_prompt:
        bridge.set_setting("system_prompt", s.system_prompt)

    if s.gemini:
        bridge.set_setting("gemini_base_url", s.gemini.base_url or "https://generativelanguage.googleapis.com/v1beta/openai")
        if s.gemini.keys is not None and len(s.gemini.keys) > 0:
            clean_keys = [k.strip() for k in s.gemini.keys if k and k.strip()]
            bridge.set_setting("gemini_keys", json.dumps(clean_keys))
            idx = s.gemini.active_key_index or 0
            if clean_keys:
                idx = min(max(0, idx), len(clean_keys) - 1)
                bridge.set_setting("gemini_key", clean_keys[idx])
            bridge.set_setting("gemini_active_key_index", str(idx))
        elif s.gemini.api_key:
            bridge.set_setting("gemini_key", s.gemini.api_key.strip())
            bridge.set_setting("gemini_keys", json.dumps([s.gemini.api_key.strip()]))
            bridge.set_setting("gemini_active_key_index", "0")

        bridge.set_setting("gemini_model_1", s.gemini.model_1 or "gemini-3.5-flash-lite")
        bridge.set_setting("gemini_model_2", s.gemini.model_2 or "gemini-3-flash-preview")
        bridge.set_setting("gemini_model_3", s.gemini.model_3 or "gemini-2.5-flash")
        bridge.set_setting("gemini_model_4", s.gemini.model_4 or "gemini-3.1-flash-lite")
        bridge.set_setting("gemini_model_5", s.gemini.model_5 or "gemini-2.5-flash-lite")

    if s.kaggle:
        bridge.set_setting("kaggle_base_url", s.kaggle.base_url or "")
        bridge.set_setting("kaggle_key", s.kaggle.api_key or "local")
        bridge.set_setting("kaggle_model", s.kaggle.model or "qwen2.5:32b")

    if s.openrouter:
        bridge.set_setting("openrouter_base_url", s.openrouter.base_url or "https://openrouter.ai/api/v1")
        bridge.set_setting("openrouter_key", s.openrouter.api_key or "")
        bridge.set_setting("openrouter_model", s.openrouter.model or "deepseek/deepseek-v4.1-flash-1017")

    # Legacy fallback keys
    if s.active_provider == "gemini":
        bridge.set_setting("base_url", s.gemini.base_url if s.gemini else "https://generativelanguage.googleapis.com/v1beta/openai")
        bridge.set_setting("model", s.gemini.model_1 if s.gemini else "gemini-3.5-flash-lite")
    elif s.active_provider == "kaggle":
        bridge.set_setting("base_url", s.kaggle.base_url if s.kaggle else "")
        bridge.set_setting("model", s.kaggle.model if s.kaggle else "qwen2.5:32b")
    else:
        bridge.set_setting("base_url", s.openrouter.base_url if s.openrouter else "https://openrouter.ai/api/v1")
        bridge.set_setting("model", s.openrouter.model if s.openrouter else "deepseek/deepseek-v4.1-flash-1017")

    return {"success": True}

if __name__ == "__main__":
    print("Starting Nelir Wolf Translator on http://127.0.0.1:8765...")
    uvicorn.run(app, host="127.0.0.1", port=8765)
