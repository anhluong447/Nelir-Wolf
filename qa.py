"""Post-translation quality checks shared by the pipeline, the API and the validator."""
import re
from collections import Counter

# Kana excluding prolonged-sound mark / middle dot (used as punctuation in VI text too).
_KANA_RE = re.compile(r"[\u3041-\u3096\u30a1-\u30fa]")
_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")
_JP_ANY_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
# WOLF control codes: \c[2], \f[36], \cself[10], \E, <C>, <R>, @1 ...
# A code with an argument has a letter name (\cself[3]); a code without argument is a
# single letter (\E). Text may follow directly ("\EMarika"), so never be greedy there.
_CODE_RE = re.compile(r"\\([a-zA-Z]+)\[([^\]]*)\]|\\([a-zA-Z])|<([A-Z])>|(@\d+)")
_STRIP_CODES_RE = re.compile(r"\\[a-zA-Z]+\[[^\]]*\]|\\[a-zA-Z]|<[A-Z]>|@\d+")

# Flags that make machine output unusable without review (status -> STATUS_QA).
BLOCKING_FLAGS = ("empty", "untranslated", "jp_residue", "line_count", "missing_code")
# Flags that are only warnings.
WARNING_FLAGS = ("too_long",)
LENGTH_CHECKED_TYPES = ("Message", "Choice")


def has_japanese(text: str) -> bool:
    return bool(text) and bool(_JP_ANY_RE.search(text))


def control_codes(text: str) -> Counter:
    """Multiset of control codes. Bracket content is compared only when it is ASCII
    (e.g. \\c[2]); non-ASCII content such as ruby text may legitimately change."""
    codes = Counter()
    for name, arg, single, align, at in _CODE_RE.findall(text or ""):
        if name:
            key = "\\" + name
            if arg.isascii():
                key += f"[{arg.replace(' ', '')}]"
            codes[key] += 1
        elif single:
            codes["\\" + single] += 1
        elif align:
            codes[f"<{align}>"] += 1
        elif at:
            codes[at] += 1
    return codes


def qa_flags(raw: str, text: str, row_type: str = "", max_line_chars: int = 0) -> list:
    if not text or not text.strip():
        return ["empty"]
    flags = []
    if text == raw and has_japanese(raw):
        flags.append("untranslated")
    elif _KANA_RE.search(text) or _CJK_RE.search(text):
        flags.append("jp_residue")
    if raw.count("\n") != text.count("\n"):
        flags.append("line_count")
    missing = control_codes(raw) - control_codes(text)
    if missing:
        flags.append("missing_code")
    if max_line_chars and row_type in LENGTH_CHECKED_TYPES:
        for line in text.split("\n"):
            if len(_STRIP_CODES_RE.sub("", line)) > max_line_chars:
                flags.append("too_long")
                break
    return flags


def is_blocking(flags) -> bool:
    return any(f in BLOCKING_FLAGS for f in flags)


FLAG_LABELS = {
    "empty": "Bản dịch rỗng",
    "untranslated": "Bản dịch giống hệt câu gốc (chưa dịch)",
    "jp_residue": "Còn sót chữ Nhật/Hán",
    "line_count": "Số dòng (\\n) khác câu gốc",
    "missing_code": "Thiếu mã điều khiển so với câu gốc",
    "too_long": "Có dòng quá dài so với khung thoại",
}
