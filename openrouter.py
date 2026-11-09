"""OpenAI-compatible chat client with key rotation + model fallback.

Never returns the source text on failure: it raises TranslationAPIError so the
caller can leave the row untouched instead of saving Japanese as "translated".
"""
import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

import requests

import config
from config import DEFAULT_SYSTEM_PROMPT  # re-exported for backwards compatibility


class TranslationAPIError(Exception):
    def __init__(self, status_code: int, message: str, format_only: bool = False):
        self.status_code = status_code
        self.message = message
        self.format_only = format_only
        super().__init__(f"[{status_code}] {message}")


class _AttemptFailed(Exception):
    def __init__(self, reason: str, auth: bool = False, bad_format: bool = False):
        self.reason = reason
        self.auth = auth
        self.bad_format = bad_format
        super().__init__(reason)


def mask_key(key: str) -> str:
    return key[:6] + "..." + key[-4:] if len(key) > 10 else "***"


def clean_translation(text: str) -> str:
    """Strips explanations, 'Lưu ý:', and artifacts."""
    if not text:
        return ""
    cleaned = []
    for line in text.split("\n"):
        l_strip = line.strip().lower()
        if any(l_strip.startswith(prefix) for prefix in [
            "lưu ý:", "lưu ý :", "ghi chú:", "ghi chú :", "chú thích:", "chú thích :",
            "note:", "note :", "giải thích:", "giải thích :", "lưu ý quan trọng:", "phần lưu ý:",
            "xin lỗi", "tôi xin lỗi", "chính xác:", "đính chính:", "sửa lại:", "bản dịch đúng:"
        ]):
            break
        cleaned.append(line)

    # A line made only of control tags (\s[14], \c[2]) belongs to the previous line.
    repaired = []
    for line in cleaned:
        if repaired and re.fullmatch(r'(\\[a-zA-Z]+(\[[^\]]*\])?\s*)+', line.strip()):
            repaired[-1] = repaired[-1].rstrip() + " " + line.strip()
        else:
            repaired.append(line)

    result = "\n".join(repaired).strip()
    result = re.sub(r'^(Bản dịch|bản dịch|Dịch|dịch)\s*:\s*', '', result).strip()
    if (result.startswith('"') and result.endswith('"')) or (result.startswith('“') and result.endswith('”')):
        result = result[1:-1].strip()
    return result


def align_translation_to_raw(raw: str, trans: str) -> str:
    """Aligns the number of translated lines with the raw text.

    Missing control codes are NOT re-inserted here (appending them at the end of a
    line changes their meaning); QA flags them instead (qa.missing_code)."""
    if not trans:
        return ""
    if not raw:
        return trans

    # Models sometimes return an escaped "\\n" instead of a real line break.
    if "\n" in raw and "\\n" not in raw:
        trans = re.sub(r"\\n(?!\[)", "\n", trans)

    raw_lines = raw.split("\n")
    target_count = len(raw_lines)
    trans_lines = [l.strip() for l in trans.split("\n")]

    # Drop spurious empty lines unless raw has an empty line at that spot.
    cleaned = []
    for i, l in enumerate(trans_lines):
        if not l:
            if i < len(raw_lines) and not raw_lines[i].strip():
                cleaned.append("")
            continue
        cleaned.append(l)
    trans_lines = cleaned or [trans.strip()]

    # Merge dangling tags / punctuation into the previous line.
    tag_or_punct = r'^(\\[a-zA-Z]+(\[[^\]]*\])?|\<[a-zA-Z0-9_\/]+\>|[・\.…!?,~ー\s]+)+$'
    merged = []
    for l in trans_lines:
        if merged and re.match(tag_or_punct, l):
            merged[-1] = merged[-1].rstrip() + " " + l.strip()
        else:
            merged.append(l)
    trans_lines = merged

    # Too many lines: merge the cheapest adjacent pair.
    while len(trans_lines) > target_count:
        best_idx, min_score = 0, None
        for i in range(len(trans_lines) - 1):
            last = trans_lines[i][-1:]
            priority = 0 if last in ',;' else (1 if last not in '.!?…' else 2)
            score = priority * 1000 + len(trans_lines[i]) + len(trans_lines[i + 1])
            if min_score is None or score < min_score:
                best_idx, min_score = i, score
        trans_lines[best_idx] = trans_lines[best_idx] + " " + trans_lines[best_idx + 1]
        trans_lines.pop(best_idx + 1)

    # Too few lines: split the longest line near its middle.
    while len(trans_lines) < target_count and trans_lines:
        longest_idx = max(range(len(trans_lines)), key=lambda i: len(trans_lines[i]))
        line = trans_lines[longest_idx]
        mid = len(line) // 2
        break_words = r'(?:[,;]\s+|\s+(?:và|nhưng|mà|để|khi|thì|tạo ra|bởi|với|là|được)\s+|\s+)'
        candidates = [m.start() for m in re.finditer(break_words, line)]
        if not candidates:
            break
        split_pos = min(candidates, key=lambda p: abs(p - mid))
        part1 = line[:split_pos].strip()
        part2 = re.sub(r'^[,\s]+', '', line[split_pos:].strip())
        trans_lines = trans_lines[:longest_idx] + [part1, part2] + trans_lines[longest_idx + 1:]

    return "\n".join(trans_lines)


def _strip_code_fence(content: str) -> str:
    content = content.strip()
    if content.startswith("```"):
        lines = content.split("\n")[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    return content


def glossary_block(glossary: Optional[List[tuple]], texts: List[str]) -> str:
    """Glossary entries whose source term appears in the texts."""
    if not glossary:
        return ""
    joined = "\n".join(texts)
    hits = [(s, d) for s, d in glossary if s and s in joined]
    if not hits:
        return ""
    lines = "\n".join(f"- {s} → {d}" for s, d in hits[:80])
    return f"\nTHUẬT NGỮ BẮT BUỘC (luôn dịch đúng như sau):\n{lines}\n"


def test_connection(base_url: str, api_key: str, model: str, provider: str = "") -> Dict[str, Any]:
    """Tests connection to the LLM backend and checks the model is listed."""
    base_url = (base_url or config.OPENROUTER_BASE_URL).rstrip("/")
    models_url = f"{base_url}/models"
    headers = {"Authorization": f"Bearer {api_key or 'local'}", "Content-Type": "application/json"}
    is_kaggle = provider == "kaggle"
    t0 = time.time()
    try:
        r = requests.get(models_url, headers=headers, timeout=12)
        latency = round((time.time() - t0) * 1000)
        if r.status_code == 200:
            data = r.json()
            models_list = []
            if isinstance(data, dict):
                if isinstance(data.get("data"), list):
                    models_list = [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
                elif isinstance(data.get("models"), list):
                    models_list = [m.get("name", "") for m in data["models"] if isinstance(m, dict)]
            norm = model.replace("models/", "")
            found = any(m.replace("models/", "") == norm for m in models_list) if models_list else True
            if found:
                msg = f"✅ Kết nối thành công ({latency}ms)!\nĐã xác nhận model '{model}' sẵn sàng phục vụ."
            else:
                available = ", ".join(models_list[:10]) or "Không có model nào"
                hint = f"👉 Trên Kaggle hãy chạy: !ollama pull {model}\nhoặc " if is_kaggle else "👉 "
                msg = (f"⚠️ Kết nối được tới server ({latency}ms) NHƯNG KHÔNG TÌM THẤY model '{model}'!\n"
                       f"• Model hiện có: [{available}]\n{hint}đổi tên model thành một model có sẵn ở trên.")
            return {"ok": found, "latency_ms": latency, "available_models": models_list,
                    "model_found": found, "message": msg}
        if r.status_code == 403:
            msg = "❌ Lỗi 403 Forbidden! Key bị từ chối hoặc server chặn truy cập."
            if is_kaggle:
                msg += ("\n👉 Trên Kaggle: os.environ['OLLAMA_ORIGINS'] = '*' và thêm cờ "
                        "'--http-host-header localhost' cho cloudflared.")
            return {"ok": False, "status_code": 403, "message": msg}
        if r.status_code == 401:
            return {"ok": False, "status_code": 401, "message": "❌ Lỗi 401 Unauthorized! API Key không hợp lệ."}
        if r.status_code == 404:
            return {"ok": False, "status_code": 404,
                    "message": f"❌ Lỗi 404 tại {models_url}! Hãy kiểm tra lại Base URL."}
        return {"ok": False, "status_code": r.status_code, "message": f"❌ Lỗi HTTP {r.status_code}: {r.text[:300]}"}
    except requests.exceptions.ConnectionError:
        msg = "❌ Không thể kết nối tới server."
        if is_kaggle:
            msg += "\n👉 Notebook Kaggle chưa bật/đã tắt, hoặc Cloudflare Tunnel đã đổi link mới."
        return {"ok": False, "message": msg}
    except requests.exceptions.Timeout:
        return {"ok": False, "message": "❌ Timeout! Server không phản hồi trong 12 giây."}
    except Exception as e:
        return {"ok": False, "message": f"❌ Lỗi không xác định: {e}"}


class OpenRouterTranslator:
    """Works with any OpenAI-compatible endpoint (Gemini, OpenRouter, Ollama...)."""

    def __init__(self, api_key: Any, model: Any = None, system_prompt: str = "", base_url: str = "",
                 active_key_index: int = 0, glossary: Optional[List[tuple]] = None,
                 on_key_rotate: Optional[Callable] = None):
        if isinstance(api_key, list):
            keys = [k.strip() for k in api_key if isinstance(k, str) and k.strip()]
        elif isinstance(api_key, str) and api_key.strip():
            keys = [api_key.strip()]
        else:
            keys = []
        self.api_keys = keys or ["local"]
        self.current_key_idx = min(max(0, int(active_key_index or 0)), len(self.api_keys) - 1)

        if isinstance(model, list):
            models = [m.strip() for m in model if isinstance(m, str) and m.strip()]
        elif isinstance(model, str) and model.strip():
            models = [model.strip()]
        else:
            models = []
        self.models_priority = models or [config.GEMINI_DEFAULT_MODELS[0]]

        self.base_url = (base_url or config.OPENROUTER_BASE_URL).rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self.glossary = glossary or []
        self.on_key_rotate = on_key_rotate

    @property
    def api_key(self) -> str:
        return self.api_keys[self.current_key_idx]

    # ------------------------------------------------------------------
    def _post(self, key: str, model: str, messages: list) -> str:
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "X-Title": "Nelir Wolf Translator",
        }
        data = {"model": model, "messages": messages, "temperature": 0.1}
        reason = ""
        for attempt in range(2):
            try:
                r = requests.post(self.api_url, headers=headers, json=data, timeout=config.REQUEST_TIMEOUT)
            except requests.exceptions.Timeout:
                reason = f"Timeout quá {config.REQUEST_TIMEOUT}s"
            except requests.exceptions.ConnectionError:
                reason = "Mất kết nối mạng"
            except requests.exceptions.RequestException as e:
                reason = f"Lỗi request: {str(e)[:80]}"
            else:
                if r.status_code == 200:
                    try:
                        return r.json()['choices'][0]['message']['content'] or ""
                    except Exception:
                        raise _AttemptFailed("Phản hồi API không đúng định dạng", bad_format=True)
                if r.status_code in (401, 403):
                    raise _AttemptFailed(f"Key không hợp lệ hoặc bị từ chối ({r.status_code})", auth=True)
                if r.status_code == 404:
                    raise _AttemptFailed(f"Model '{model}' không tồn tại hoặc không hỗ trợ (404)")
                if r.status_code == 429:
                    raise _AttemptFailed("Rate Limit / Hết Quota (429)")
                reason = f"Lỗi máy chủ ({r.status_code})"
                if r.status_code not in (500, 502, 503, 504):
                    raise _AttemptFailed(f"HTTP {r.status_code}")
            if attempt == 0:
                time.sleep(1)
        raise _AttemptFailed(reason)

    def _run(self, messages: list, parse: Callable[[str], Any], on_fallback=None, on_key_rotate=None):
        """Try NV1..NVn on the current key, then rotate keys circularly."""
        on_key_rotate = on_key_rotate or self.on_key_rotate
        n_keys = len(self.api_keys)
        last_reason = ""
        format_only = True
        for k_try in range(n_keys):
            if k_try > 0:
                old = self.current_key_idx
                self.current_key_idx = (old + 1) % n_keys
                if on_key_rotate:
                    on_key_rotate(old + 1, self.current_key_idx + 1, mask_key(self.api_keys[old]),
                                  mask_key(self.api_key), last_reason)
            key = self.api_key
            for p_idx, model in enumerate(self.models_priority):
                try:
                    content = self._post(key, model, messages)
                    return parse(content)
                except _AttemptFailed as f:
                    last_reason = f.reason
                    format_only = format_only and f.bad_format
                    if f.auth:
                        break
                    if p_idx < len(self.models_priority) - 1 and on_fallback:
                        on_fallback(model, self.models_priority[p_idx + 1], p_idx + 2, f.reason)
        raise TranslationAPIError(
            429 if not format_only else 502,
            f"Tất cả {n_keys} API Key và {len(self.models_priority)} Model đều thất bại ({last_reason})",
            format_only=format_only)

    # ------------------------------------------------------------------
    def translate_batch(self, texts: List[str], on_fallback=None, on_key_rotate=None) -> List[str]:
        """Translate many lines in one call. Raises TranslationAPIError on failure."""
        if not texts:
            return []
        if len(texts) == 1:
            return [self.translate_single(texts[0], on_key_rotate=on_key_rotate)]

        payload = [{"id": i, "text": t} for i, t in enumerate(texts)]
        system = (
            f"{self.system_prompt}\n"
            f"{glossary_block(self.glossary, texts)}"
            "Các câu dưới đây là các dòng liên tiếp trong cùng một cảnh game, hãy dùng chúng làm ngữ cảnh cho nhau.\n"
            "Đầu vào là JSON: [{\"id\": 0, \"text\": \"...\"}, ...].\n"
            "Trả về JSON array các chuỗi tiếng Việt theo đúng thứ tự id: [\"bản dịch 0\", \"bản dịch 1\", ...].\n"
            "Mỗi chuỗi giữ đúng số dòng (\\n) của câu gốc. Chỉ trả về JSON thuần túy, không dùng markdown."
        )
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]

        def parse(content: str):
            content = _strip_code_fence(content)
            try:
                parsed = json.loads(content)
            except Exception:
                raise _AttemptFailed("Model trả về JSON không hợp lệ", bad_format=True)
            if isinstance(parsed, dict) and isinstance(parsed.get("translations"), list):
                parsed = parsed["translations"]
            if not isinstance(parsed, list) or len(parsed) != len(texts):
                raise _AttemptFailed("Model trả về sai số lượng câu", bad_format=True)
            out = []
            for raw, x in zip(texts, parsed):
                if isinstance(x, dict):
                    x = x.get("text") or x.get("translation") or ""
                out.append(align_translation_to_raw(raw, clean_translation(str(x))))
            return out

        try:
            return self._run(messages, parse, on_fallback, on_key_rotate)
        except TranslationAPIError as err:
            if not err.format_only:
                raise
        # API works but no model returns valid batch JSON -> go line by line.
        return [self.translate_single(t, on_key_rotate=on_key_rotate) for t in texts]

    def translate_single(self, text: str, on_key_rotate=None) -> str:
        """Translate one text. Raises TranslationAPIError on failure (never returns the source)."""
        messages = [
            {"role": "system", "content": self.system_prompt + glossary_block(self.glossary, [text])},
            {"role": "user", "content": f"Dịch đoạn game sau sang tiếng Việt (giữ nguyên số dòng \\n và mã điều khiển):\n{text}"},
        ]

        def parse(content: str):
            result = align_translation_to_raw(text, clean_translation(content.strip()))
            if not result.strip():
                raise _AttemptFailed("Model trả về bản dịch rỗng", bad_format=True)
            return result

        return self._run(messages, parse, on_key_rotate=on_key_rotate)
