"""static/js/codes.js must flag exactly like qa.py (live QA in the editor == server QA)."""
import json
import os
import shutil
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from qa import qa_flags  # noqa: E402

CASES = [
    ("あ", "", "Message"),
    ("こんにちは", "こんにちは", "Message"),
    ("こんにちは", "Xin こんにちは", "Message"),
    ("あ\nい", "A", "Message"),
    ("\\c[2]あ", "A", "Message"),
    ("\\c[2]あ\nい", "\\c[2]A\nB", "Message"),
    ("\\Eマリーカ\n「あ」", "\\EMarika\n「A」", "Message"),
    ("\\s[7]あ\\s[7]", "A\\s[7]", "Message"),
    ("<C>連れて行く", "Dẫn đi", "Choice"),
    ("@1 あ", "@1 A", "Message"),
    ("\\r[漢字,かんじ]", "\\r[Hán tự,hanji]", "Message"),
    ("あ", "A" * 80, "Message"),
    ("あ", "A" * 80, "DBField"),
    ("体力", "Thể lực 体", "DBField"),
]


@unittest.skipUnless(shutil.which("node"), "node not installed")
class TestCodesParity(unittest.TestCase):
    def test_js_matches_python(self):
        module = "file:///" + os.path.join(ROOT, "static", "js", "codes.js").replace("\\", "/")
        script = (
            f"import {{ qaFlags }} from '{module}';"
            f"const cases = {json.dumps(CASES, ensure_ascii=False)};"
            "process.stdout.write(JSON.stringify(cases.map(([r, t, ty]) => qaFlags(r, t, ty, 56))));"
        )
        out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout
        js = json.loads(out)
        for (raw, text, rt), js_flags in zip(CASES, js):
            with self.subTest(raw=raw, text=text):
                self.assertEqual(js_flags, qa_flags(raw, text, rt, 56))


if __name__ == "__main__":
    unittest.main()
