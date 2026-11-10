"""Single source of truth for paths, defaults and shared constants."""
import os
import re

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(ROOT_DIR, "bin")
WOLFTL_PATH = os.path.join(BIN_DIR, "WolfTL.exe")
# Where projects/ and global_settings.db live (override for tests / portable setups).
DATA_DIR = os.environ.get("NELIR_DATA_DIR") or ROOT_DIR
PROJECTS_DIR = os.path.join(DATA_DIR, "projects")
STATIC_DIR = os.path.join(ROOT_DIR, "static")
GLOBAL_DB_PATH = os.path.join(DATA_DIR, "global_settings.db")

HOST = "127.0.0.1"
PORT = 8765
# Host headers the local server accepts. Anything else (e.g. a DNS-rebinding page
# resolving its own domain to 127.0.0.1) is rejected. "testserver" is Starlette's TestClient.
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "[::1]", "testserver"]

# ---------------------------------------------------------------------------
# Row status semantics (translation_rows.status)
# ---------------------------------------------------------------------------
STATUS_EMPTY = 0      # no translation yet
STATUS_MTL = 1        # machine translated, not reviewed
STATUS_REVIEWED = 2   # edited / confirmed by a human
STATUS_QA = 3         # machine output failed QA, needs review

# ---------------------------------------------------------------------------
# Row type rules
# ---------------------------------------------------------------------------
# Types whose text is shown to the player and may be translated.
TRANSLATABLE_TYPES = frozenset({
    "Message", "Choice", "SetString", "Picture", "DBName", "DBField", "GameTitle",
})
# Translatable types that can also act as a *key* (compared / looked up by other
# commands). They get locked when another command references the same string.
KEY_CAPABLE_TYPES = frozenset({"SetString", "DBName", "DBField"})
# Commands whose string args are references (lookups, comparisons, labels).
REFERENCE_TYPES = frozenset({
    "Database", "StringCondition", "CommonEventByName", "CommonEvent", "SetLabel", "JumpLabel",
})
# Files that must never be extracted or patched (engine runtime memory).
EXCLUDED_FILES = frozenset({"CDataBase.json"})

PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9_\-]{1,80}$")

# ---------------------------------------------------------------------------
# AI defaults
# ---------------------------------------------------------------------------
DEFAULT_SYSTEM_PROMPT = (
    "Bạn là một chuyên gia bản địa hóa game từ tiếng Nhật sang tiếng Việt.\n"
    "YÊU CẦU BẮT BUỘC:\n"
    "1. Dịch 100% sang tiếng Việt tự nhiên, phù hợp văn phong hội thoại game. Xác định đúng chủ ngữ theo ngữ cảnh (không tự nhận là 'Tôi' khi mô tả đồ vật/kỹ năng).\n"
    "2. Giữ nguyên số dòng (ngắt bởi \\n), phân bổ câu chữ cân đối giữa các dòng, không dồn chữ làm một dòng quá dài.\n"
    "3. Giữ nguyên vẹn mã điều khiển (\\s[...], \\c[...], \\f[...], \\cself[...], <C>, <R>, @1, dấu ・・・, ngoặc 「」, \"\") ở đúng dòng tương ứng.\n"
    "4. Không để sót chữ Nhật/Hán. Chỉ xuất duy nhất bản dịch, tuyệt đối không thêm lời chào, giải thích hay ghi chú."
)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
GEMINI_DEFAULT_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3-flash-preview",
    "gemini-2.5-flash",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash-lite",
]
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash-1017"
KAGGLE_DEFAULT_MODEL = "qwen2.5:32b"

REQUEST_TIMEOUT = 60

# Flat key -> default value for every global setting.
DEFAULT_SETTINGS = {
    "active_project_id": "",
    "active_provider": "gemini",
    "batch_size": "15",
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "qa_max_line_chars": "56",
    "gemini_base_url": GEMINI_BASE_URL,
    "gemini_keys": "[]",
    "gemini_key": "",
    "gemini_active_key_index": "0",
    **{f"gemini_model_{i + 1}": m for i, m in enumerate(GEMINI_DEFAULT_MODELS)},
    "kaggle_base_url": "",
    "kaggle_key": "local",
    "kaggle_model": KAGGLE_DEFAULT_MODEL,
    "openrouter_base_url": OPENROUTER_BASE_URL,
    "openrouter_key": "",
    "openrouter_model": OPENROUTER_DEFAULT_MODEL,
}

# Obsolete settings keys that are no longer read anywhere.
OBSOLETE_SETTINGS = ("base_url", "model")


def is_valid_project_id(project_id) -> bool:
    return isinstance(project_id, str) and bool(PROJECT_ID_RE.match(project_id)) and project_id not in (".", "..")
