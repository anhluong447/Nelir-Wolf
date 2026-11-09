import requests
import json
import time
import re
from typing import List, Dict, Any, Optional

DEFAULT_SYSTEM_PROMPT = (
    "Bạn là một chuyên gia bản địa hóa game từ tiếng Nhật sang tiếng Việt.\n"
    "YÊU CẦU BẮT BUỘC:\n"
    "1. Dịch 100% sang tiếng Việt tự nhiên, phù hợp văn phong hội thoại game. Xác định đúng chủ ngữ theo ngữ cảnh (không tự nhận là 'Tôi' khi mô tả đồ vật/kỹ năng).\n"
    "2. Giữ nguyên số dòng (ngắt bởi \\n), phân bổ câu chữ cân đối giữa các dòng, không dồn chữ làm một dòng quá dài.\n"
    "3. Giữ nguyên vẹn mã điều khiển (\\s[...], \\c[...], \\cself[...], @1, dấu ・・・, ngoặc 「」, \"\") ở đúng dòng tương ứng.\n"
    "4. Chỉ xuất duy nhất bản dịch, tuyệt đối không thêm lời chào, giải thích hay ghi chú."
)

class TranslationAPIError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"[{status_code}] {message}")

def clean_translation(text: str) -> str:
    """Strips explanations, 'Lưu ý:', and artifacts."""
    if not text:
        return ""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        l_strip = line.strip().lower()
        if any(l_strip.startswith(prefix) for prefix in [
            "lưu ý:", "lưu ý :", "ghi chú:", "ghi chú :", "chú thích:", "chú thích :",
            "note:", "note :", "giải thích:", "giải thích :", "lưu ý quan trọng:", "phần lưu ý:",
            "xin lỗi", "tôi xin lỗi", "chính xác:", "đính chính:", "sửa lại:", "bản dịch đúng:"
        ]):
            break
        cleaned.append(line)

    # Auto-repair: if a line is purely control tags (like \s[14] or \c[2]), merge it back to the previous line
    repaired = []
    for line in cleaned:
        if repaired and re.fullmatch(r'(\\[a-zA-Z]+(\[[^\]]*\])?\s*)+', line.strip()):
            repaired[-1] = repaired[-1].rstrip() + " " + line.strip()
        else:
            repaired.append(line)

    result = "\n".join(repaired).strip()

    # If starts with 'Bản dịch:' or 'Dịch:'
    if re.match(r'^(Bản dịch|bản dịch|Dịch|dịch)\s*:\s*', result):
        result = re.sub(r'^(Bản dịch|bản dịch|Dịch|dịch)\s*:\s*', '', result).strip()

    # If surrounded by unnecessary quotes
    if (result.startswith('"') and result.endswith('"')) or (result.startswith('“') and result.endswith('”')):
        result = result[1:-1].strip()

    return result

def align_translation_to_raw(raw: str, trans: str) -> str:
    """Deterministically aligns translated lines and control tags with the original raw text."""
    if not trans:
        return ""
    if not raw:
        return trans

    raw_lines = raw.split("\n")
    target_count = len(raw_lines)

    # 1. Split trans
    trans_lines = [l.strip() for l in trans.split("\n")]

    # 2. Filter spurious empty lines if raw didn't have empty lines at those places
    cleaned = []
    for i, l in enumerate(trans_lines):
        if not l:
            if i < len(raw_lines) and not raw_lines[i].strip():
                cleaned.append("")
            continue
        cleaned.append(l)
    trans_lines = cleaned or [trans.strip()]

    # 3. Merge dangling tags and punctuation to previous line
    tag_or_punct_pattern = r'^(\\[a-zA-Z]+(\[[^\]]*\])?|\<[a-zA-Z0-9_\/]+\>|[・\.…!?,~ー\s]+)+$'
    merged = []
    for l in trans_lines:
        if merged and re.match(tag_or_punct_pattern, l):
            merged[-1] = merged[-1].rstrip() + " " + l.strip()
        else:
            merged.append(l)
    trans_lines = merged

    # 4. If more lines than target, intelligently merge lines
    while len(trans_lines) > target_count:
        best_idx = 0
        min_score = 999999
        for i in range(len(trans_lines) - 1):
            combined_len = len(trans_lines[i]) + len(trans_lines[i+1])
            priority = 0 if trans_lines[i][-1:] in ',;' else (1 if trans_lines[i][-1:] not in '.!?…' else 2)
            score = priority * 1000 + combined_len
            if score < min_score:
                min_score = score
                best_idx = i
        trans_lines[best_idx] = trans_lines[best_idx] + " " + trans_lines[best_idx + 1]
        trans_lines.pop(best_idx + 1)

    # 5. If fewer lines than target, intelligently split longest line
    while len(trans_lines) < target_count and trans_lines:
        longest_idx = max(range(len(trans_lines)), key=lambda i: len(trans_lines[i]))
        line_to_split = trans_lines[longest_idx]

        mid = len(line_to_split) // 2
        break_words = r'(?:[,;]\s+|\s+(?:và|nhưng|mà|để|khi|thì|tạo ra|bởi|với|là|được)\s+|\s+)'
        candidates = [m.start() for m in re.finditer(break_words, line_to_split)]
        if candidates:
            split_pos = min(candidates, key=lambda p: abs(p - mid))
            part1 = line_to_split[:split_pos].strip()
            part2 = line_to_split[split_pos:].strip()
            part2 = re.sub(r'^[,\s]+', '', part2)
            trans_lines = trans_lines[:longest_idx] + [part1, part2] + trans_lines[longest_idx+1:]
        else:
            break

    # 6. Tag preservation from raw to matching trans lines
    for i in range(min(len(raw_lines), len(trans_lines))):
        raw_tags = re.findall(r'(\\[a-zA-Z]+\[[^\]]*\]|\\[a-zA-Z]+)', raw_lines[i])
        for tag in raw_tags:
            if tag not in trans_lines[i]:
                trans_lines[i] = trans_lines[i].rstrip() + " " + tag

    return "\n".join(trans_lines)

def test_connection(base_url: str, api_key: str, model: str) -> Dict[str, Any]:
    """Tests connection to the LLM backend (Ollama / OpenRouter) and diagnoses model availability."""
    base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
    models_url = f"{base_url}/models"
    headers = {
        "Authorization": f"Bearer {api_key or 'local'}",
        "Content-Type": "application/json"
    }

    t0 = time.time()
    try:
        r = requests.get(models_url, headers=headers, timeout=12)
        latency = round((time.time() - t0) * 1000)

        if r.status_code == 200:
            data = r.json()
            models_list = []
            if isinstance(data, dict):
                if "data" in data and isinstance(data["data"], list):
                    models_list = [m.get("id", "") for m in data["data"] if isinstance(m, dict)]
                elif "models" in data and isinstance(data["models"], list):
                    models_list = [m.get("name", "") for m in data["models"] if isinstance(m, dict)]

            model_normalized = model.replace("models/", "")
            model_found = any(m.replace("models/", "") == model_normalized for m in models_list) if models_list else True
            if model_found:
                msg = f"✅ Kết nối thành công ({latency}ms)!\nĐã xác nhận model '{model}' sẵn sàng phục vụ."
            else:
                available_str = ", ".join(models_list[:10]) if models_list else "Không có model nào"
                msg = (
                    f"⚠️ Kết nối được tới server ({latency}ms) NHƯNG KHÔNG TÌM THẤY model '{model}'!\n"
                    f"• Danh sách model hiện có trên server: [{available_str}]\n"
                    f"👉 Khắc phục: Trên Kaggle hãy chạy: !ollama pull {model}\n"
                    f"hoặc đổi tên model trong cài đặt thành một trong các model có sẵn ở trên."
                )

            return {
                "ok": model_found,
                "latency_ms": latency,
                "available_models": models_list,
                "model_found": model_found,
                "message": msg
            }
        elif r.status_code == 403:
            return {
                "ok": False,
                "status_code": 403,
                "message": (
                    "❌ Lỗi 403 Forbidden!\n"
                    "Ollama trên Kaggle chặn kết nối từ bên ngoài (CORS / Host header check).\n"
                    "👉 Khắc phục trên Kaggle:\n"
                    "1. os.environ['OLLAMA_ORIGINS'] = '*'\n"
                    "2. Thêm cờ '--http-host-header localhost' vào lệnh chạy cloudflared."
                )
            }
        elif r.status_code == 401:
            return {
                "ok": False,
                "status_code": 401,
                "message": "❌ Lỗi 401 Unauthorized! API Key không hợp lệ hoặc tài khoản bị từ chối."
            }
        elif r.status_code == 404:
            return {
                "ok": False,
                "status_code": 404,
                "message": f"❌ Lỗi 404 Not Found tại URL {models_url}! Hãy kiểm tra lại đường dẫn Base URL."
            }
        else:
            return {
                "ok": False,
                "status_code": r.status_code,
                "message": f"❌ Lỗi HTTP {r.status_code}: {r.text}"
            }
    except requests.exceptions.ConnectionError:
        return {
            "ok": False,
            "message": (
                "❌ Lỗi kết nối (Connection Error)!\n"
                "Không thể kết nối tới URL Cloudflare Tunnel.\n"
                "👉 Nguyên nhân: Notebook trên Kaggle chưa bật, đã bị tắt/ngắt kết nối, hoặc Cloudflare Tunnel đã đổi sang đường link mới."
            )
        }
    except requests.exceptions.Timeout:
        return {
            "ok": False,
            "message": "❌ Lỗi Timeout! Server không phản hồi trong 12 giây. Hãy kiểm tra xem GPU/Ollama trên Kaggle có bị treo không."
        }
    except Exception as e:
        return {
            "ok": False,
            "message": f"❌ Lỗi không xác định: {str(e)}"
        }

class OpenRouterTranslator:
    def __init__(self, api_key: Any, model: Any = "qwen2.5:14b", system_prompt: str = "", base_url: str = "", active_key_index: int = 0):
        if isinstance(api_key, list):
            self.api_keys = [k.strip() for k in api_key if isinstance(k, str) and k.strip()]
        elif isinstance(api_key, str) and api_key.strip():
            self.api_keys = [api_key.strip()]
        else:
            self.api_keys = ["local"]

        if not self.api_keys:
            self.api_keys = ["local"]

        self.current_key_idx = min(max(0, active_key_index), len(self.api_keys) - 1)
        self.api_key = self.api_keys[self.current_key_idx]

        if isinstance(model, list):
            self.models_priority = [m.strip() for m in model if isinstance(m, str) and m.strip()]
        elif isinstance(model, str) and model.strip():
            self.models_priority = [model.strip()]
        else:
            self.models_priority = ["gemini-3.5-flash-lite"]
        if not self.models_priority:
            self.models_priority = ["gemini-3.5-flash-lite"]

        self.model = self.models_priority[0]
        self.base_url = (base_url or "https://openrouter.ai/api/v1").rstrip("/")
        self.api_url = f"{self.base_url}/chat/completions"
        self.system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT

    def translate_batch(self, texts: List[str], on_fallback=None, on_key_rotate=None) -> List[str]:
        """Translates a batch of texts in one API call with two-tiered rotation:
        Level 1: Rotate priority models on error/limit.
        Level 2: Rotate API keys when all models in the current key hit daily limit / fail."""
        if not texts:
            return []

        payload_items = [{"id": i, "text": t} for i, t in enumerate(texts)]

        system_instruction = (
            f"{self.system_prompt}\n"
            "Dưới đây là danh sách các câu thoại dạng JSON: [{\"id\": 0, \"text\": \"...\"}, ...].\n"
            "Hãy trả về JSON array các chuỗi tiếng Việt tương ứng theo đúng id: [\"bản dịch 0\", \"bản dịch 1\", ...].\n"
            "Mỗi chuỗi giữ đúng số dòng (\\n) của câu gốc. Chỉ trả về JSON thuần túy, không dùng markdown."
        )

        TIMEOUT_SECONDS = 30
        last_error = None
        last_rotate_reason = ""
        num_keys = len(self.api_keys)
        keys_tried = 0

        # Level 2: Loop through API keys (circular rotation through all keys)
        while keys_tried < num_keys:
            active_key = self.api_keys[self.current_key_idx]
            self.api_key = active_key

            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anhluong447/Nelir",
                "X-Title": "Nelir Wolf Translator"
            }

            key_exhausted = False
            key_auth_error = False

            # Level 1: Loop through priority models: NV1 is ALWAYS tried first on every batch
            for p_idx, current_model in enumerate(self.models_priority):
                data = {
                    "model": current_model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": json.dumps(payload_items, ensure_ascii=False)}
                    ],
                    "temperature": 0.1
                }

                max_retries = 2
                should_rotate = False
                rotate_reason = ""

                for attempt in range(max_retries):
                    try:
                        response = requests.post(self.api_url, headers=headers, json=data, timeout=TIMEOUT_SECONDS)

                        # Auth error with this specific key -> Skip this key entirely right away!
                        if response.status_code in (401, 403):
                            should_rotate = True
                            key_auth_error = True
                            rotate_reason = f"Key không hợp lệ hoặc bị từ chối ({response.status_code})"
                            break

                        # Model not available on this endpoint
                        if response.status_code == 404:
                            should_rotate = True
                            rotate_reason = f"Model '{current_model}' không tồn tại hoặc không hỗ trợ (404)"
                            break

                        if response.status_code == 200:
                            res_json = response.json()
                            content = res_json['choices'][0]['message']['content'].strip()
                            if content.startswith("```"):
                                lines = content.split("\n")
                                if lines[0].startswith("```"):
                                    lines = lines[1:]
                                if lines and lines[-1].startswith("```"):
                                    lines = lines[:-1]
                                content = "\n".join(lines).strip()

                            try:
                                parsed = json.loads(content)
                                if isinstance(parsed, list) and len(parsed) == len(texts):
                                    return [align_translation_to_raw(raw, clean_translation(str(x))) for raw, x in zip(texts, parsed)]
                                elif isinstance(parsed, dict) and "translations" in parsed:
                                    return [align_translation_to_raw(raw, clean_translation(str(x))) for raw, x in zip(texts, parsed["translations"])]
                            except Exception:
                                pass

                            raw_lines = [clean_translation(l.strip()) for l in content.split("\n") if l.strip()]
                            if len(raw_lines) == len(texts):
                                return [align_translation_to_raw(raw, line) for raw, line in zip(texts, raw_lines)]

                            return [self.translate_single(t) for t in texts]

                        elif response.status_code == 429:
                            should_rotate = True
                            rotate_reason = "Rate Limit / Hết Quota (429)"
                            break

                        elif response.status_code in (500, 502, 503, 504):
                            if attempt == max_retries - 1:
                                should_rotate = True
                                rotate_reason = f"Lỗi máy chủ Google ({response.status_code})"
                                break
                            time.sleep(1)

                        else:
                            should_rotate = True
                            rotate_reason = f"HTTP {response.status_code}"
                            break

                    except requests.exceptions.Timeout:
                        last_error = f"Timeout quá {TIMEOUT_SECONDS}s"
                        if attempt == max_retries - 1:
                            should_rotate = True
                            rotate_reason = f"Timeout quá {TIMEOUT_SECONDS}s"
                            break
                        time.sleep(1)
                    except requests.exceptions.ConnectionError:
                        last_error = "Mất kết nối mạng"
                        if attempt == max_retries - 1:
                            should_rotate = True
                            rotate_reason = "Mất kết nối mạng"
                            break
                        time.sleep(1)
                    except Exception as e:
                        last_error = str(e)
                        if attempt == max_retries - 1:
                            should_rotate = True
                            rotate_reason = f"Lỗi: {str(e)[:50]}"
                            break
                        time.sleep(1)

                if should_rotate:
                    last_rotate_reason = rotate_reason
                    # If this key has an auth failure, do not waste time trying other models with the same broken key
                    if key_auth_error:
                        key_exhausted = True
                        break

                    if p_idx < len(self.models_priority) - 1:
                        next_model = self.models_priority[p_idx + 1]
                        if on_fallback:
                            on_fallback(current_model, next_model, p_idx + 2, rotate_reason)
                        continue # Try next model under current key
                    else:
                        # All models under current key failed / hit limits!
                        key_exhausted = True
                        break

            # If all models in this key failed, rotate to the next key circularly!
            if key_exhausted:
                keys_tried += 1
                if keys_tried < num_keys:
                    old_idx = self.current_key_idx
                    self.current_key_idx = (self.current_key_idx + 1) % num_keys
                    next_key = self.api_keys[self.current_key_idx]
                    self.api_key = next_key
                    k_old = active_key[:6] + "..." + active_key[-4:] if len(active_key) > 10 else "***"
                    k_new = next_key[:6] + "..." + next_key[-4:] if len(next_key) > 10 else "***"
                    if on_key_rotate:
                        on_key_rotate(old_idx + 1, self.current_key_idx + 1, k_old, k_new, last_rotate_reason)
                    continue # Start fresh at NV1 with the new key!
                else:
                    break # All keys exhausted

        raise TranslationAPIError(429, f"Tất cả {num_keys} API Key và {len(self.models_priority)} Model đều đã hết Quota hoặc gặp sự cố ({last_rotate_reason or last_error})!")

    def translate_single(self, text: str) -> str:
        """Translates a single line of text with circular key & model rotation fallback."""
        num_keys = len(self.api_keys)
        keys_tried = 0
        while keys_tried < num_keys:
            active_key = self.api_keys[self.current_key_idx]
            self.api_key = active_key
            headers = {
                "Authorization": f"Bearer {active_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/anhluong447/Nelir",
                "X-Title": "Nelir Wolf Translator"
            }
            key_failed = False
            for p_idx, current_model in enumerate(self.models_priority):
                data = {
                    "model": current_model,
                    "messages": [
                        {"role": "system", "content": self.system_prompt},
                        {"role": "user", "content": f"Dịch đoạn game sau sang tiếng Việt (giữ nguyên số dòng \\n và mã điều khiển):\n{text}"}
                    ],
                    "temperature": 0.1
                }
                try:
                    r = requests.post(self.api_url, headers=headers, json=data, timeout=30)
                    if r.status_code == 200:
                        raw_res = r.json()['choices'][0]['message']['content'].strip()
                        cleaned = clean_translation(raw_res)
                        return align_translation_to_raw(text, cleaned)
                    elif r.status_code in (401, 403):
                        key_failed = True
                        break
                    elif p_idx < len(self.models_priority) - 1:
                        continue
                    else:
                        key_failed = True
                except Exception as e:
                    if p_idx < len(self.models_priority) - 1:
                        continue
                    key_failed = True

            if key_failed:
                keys_tried += 1
                if keys_tried < num_keys:
                    self.current_key_idx = (self.current_key_idx + 1) % num_keys
                    continue
                else:
                    break

        return text
