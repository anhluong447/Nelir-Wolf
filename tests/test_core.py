"""Core regression tests. Run:  python -m unittest discover -s tests -v"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pipeline  # noqa: E402
from db import connect, init_project_db, status_counts  # noqa: E402
from extractor import (ensure_original_dump, get_by_path, is_translatable, refresh_locks,  # noqa: E402
                       set_by_path, sync_rows)
from openrouter import (OpenRouterTranslator, TranslationAPIError, _AttemptFailed,  # noqa: E402
                        align_translation_to_raw, clean_translation, glossary_block)
from qa import control_codes, qa_flags  # noqa: E402
from validator import check_dump  # noqa: E402


def wj(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def rj(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def cmd(code, *args):
    return {"codeStr": code, "stringArgs": list(args), "intArgs": []}


def make_dump(root):
    """Tiny WolfTL-like dump: a common event sets a name, compares it, shows a message."""
    os.makedirs(os.path.join(root, "common"))
    os.makedirs(os.path.join(root, "mps"))
    os.makedirs(os.path.join(root, "db"))
    common = {"commands": [
        cmd("SetString", "マリーカ"),                 # key: compared below
        cmd("StringCondition", "マリーカ"),
        cmd("SetString", "ただの表示文字"),            # free text
        cmd("Message", "\\Eマリーカ\n「こんにちは」"),
        cmd("SetLabel", "ラベル"),
        cmd("JumpLabel", "ラベル"),
        cmd("Database", "", "アイテム", "薬草"),
    ]}
    wj(os.path.join(root, "common", "0_test.json"), common)
    mps = {"events": [{"pages": [{"list": [cmd("Message", "地図の台詞"), cmd("Choices", "はい")]}]}]}
    wj(os.path.join(root, "mps", "Map001.json"), mps)
    db = {"types": [{"name": "アイテム", "data": [{"name": "薬草", "data": [{"value": "体力を回復する"}]}]}]}
    wj(os.path.join(root, "db", "DataBase.json"), db)
    wj(os.path.join(root, "db", "CDataBase.json"), {"types": []})


class FakeTranslator:
    on_key_rotate = None

    def __init__(self):
        self.calls = []

    def translate_batch(self, texts, on_fallback=None, on_key_rotate=None):
        self.calls.append(list(texts))
        return [t.replace("マリーカ", "Marika").replace("こんにちは", "Xin chào")
                .replace("地図の台詞", "Lời thoại").replace("はい", "Vâng")
                .replace("ただの表示文字", "Chữ hiển thị").replace("体力を回復する", "Hồi máu")
                .replace("薬草", "Thảo dược") for t in texts]


class ProjectFixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.dump = os.path.join(self.tmp, "dump_original")
        make_dump(self.dump)
        self.db = os.path.join(self.tmp, "translation.db")
        init_project_db(self.db)
        sync_rows(self.db, self.dump)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def rows(self):
        with connect(self.db) as conn:
            return {r[0]: r for r in conn.execute(
                "SELECT raw, row_type, locked, status, translated, mtl FROM translation_rows")}


class TestExtraction(ProjectFixture):
    def test_is_translatable(self):
        self.assertTrue(is_translatable("こんにちは"))
        self.assertFalse(is_translatable("Picture/立ち絵.png"))
        self.assertFalse(is_translatable("abc"))
        self.assertFalse(is_translatable("  "))

    def test_cdatabase_never_extracted(self):
        with connect(self.db) as conn:
            files = {r[0] for r in conn.execute("SELECT file FROM translation_rows")}
        self.assertFalse(any("CDataBase" in f for f in files))

    def test_key_strings_are_locked(self):
        rows = self.rows()
        # SetString compared by StringCondition -> locked; free SetString -> translatable
        with connect(self.db) as conn:
            set_rows = dict(conn.execute(
                "SELECT raw, locked FROM translation_rows WHERE row_type = 'SetString'").fetchall())
        self.assertEqual(set_rows["マリーカ"], 1)
        self.assertEqual(set_rows["ただの表示文字"], 0)
        # DB name looked up by a Database command -> locked; its description is free
        self.assertEqual(rows["薬草"][2], 1)
        self.assertEqual(rows["体力を回復する"][2], 0)
        # logic commands are always locked
        self.assertEqual(rows["ラベル"][2], 1)

    def test_resync_keeps_translations(self):
        with connect(self.db) as conn:
            conn.execute("UPDATE translation_rows SET translated = 'Vâng', status = 2 WHERE raw = 'はい'")
        stats = sync_rows(self.db, self.dump)
        self.assertEqual((stats["changed"], stats["deleted"], stats["inserted"]), (0, 0, 0))
        self.assertEqual(self.rows()["はい"][4], "Vâng")

    def test_resync_resets_changed_raw(self):
        path = os.path.join(self.dump, "mps", "Map001.json")
        data = rj(path)
        with connect(self.db) as conn:
            conn.execute("UPDATE translation_rows SET translated = 'Vâng', status = 2 WHERE raw = 'はい'")
        data["events"][0]["pages"][0]["list"][1]["stringArgs"][0] = "いいえ"
        wj(path, data)
        stats = sync_rows(self.db, self.dump)
        self.assertEqual(stats["changed"], 1)
        self.assertEqual(self.rows()["いいえ"][3], 0)

    def test_original_dump_rebuilt_from_patched_dump(self):
        proj = os.path.join(self.tmp, "proj")
        os.makedirs(proj)
        shutil.copytree(self.dump, os.path.join(proj, "dump"))
        path = os.path.join(proj, "dump", "mps", "Map001.json")
        data = rj(path)
        data["events"][0]["pages"][0]["list"][1]["stringArgs"][0] = "Vâng"  # previously patched
        wj(path, data)
        original = ensure_original_dump(proj, self.db, "")
        restored = rj(os.path.join(original, "mps", "Map001.json"))
        self.assertEqual(restored["events"][0]["pages"][0]["list"][1]["stringArgs"][0], "はい")

    def test_path_helpers(self):
        d = {"a": [{"b": ["x", "y"]}]}
        set_by_path(d, "a[0].b[1]", "z")
        self.assertEqual(get_by_path(d, "a[0].b[1]"), "z")


class TestQA(unittest.TestCase):
    def test_flags(self):
        self.assertEqual(qa_flags("あ", ""), ["empty"])
        self.assertIn("untranslated", qa_flags("こんにちは", "こんにちは"))
        self.assertIn("jp_residue", qa_flags("こんにちは", "Xin こんにちは"))
        self.assertIn("line_count", qa_flags("あ\nい", "A"))
        self.assertIn("missing_code", qa_flags("\\c[2]あ", "A"))
        self.assertEqual(qa_flags("\\c[2]あ\nい", "\\c[2]A\nB"), [])

    def test_single_letter_code_followed_by_text(self):
        # "\EMarika" must be read as code \E + text, not as a code named "EMarika"
        self.assertEqual(control_codes("\\Eマリーカ"), control_codes("\\EMarika"))
        self.assertEqual(qa_flags("\\Eマリーカ\n「あ」", "\\EMarika\n「A」"), [])

    def test_too_long_is_warning_only(self):
        flags = qa_flags("あ", "A" * 80, "Message", 56)
        self.assertEqual(flags, ["too_long"])
        self.assertEqual(pipeline.machine_status("あ", "A" * 80, "Message", 56)[0], 1)


class TestTranslatorText(unittest.TestCase):
    def test_align_keeps_line_count(self):
        self.assertEqual(align_translation_to_raw("あ\nい", "A B C D").count("\n"), 1)
        self.assertEqual(align_translation_to_raw("あ", "A\nB\nC").count("\n"), 0)

    def test_align_does_not_append_tags(self):
        self.assertEqual(align_translation_to_raw("\\c[2]あ", "A"), "A")

    def test_align_fixes_escaped_newline(self):
        self.assertEqual(align_translation_to_raw("あ\nい", "A\\nB"), "A\nB")

    def test_clean(self):
        self.assertEqual(clean_translation("Bản dịch: Xin chào\nLưu ý: abc"), "Xin chào")

    def test_glossary_block_only_matching_terms(self):
        block = glossary_block([("マリーカ", "Marika"), ("プシカ", "Pushika")], ["マリーカです"])
        self.assertIn("Marika", block)
        self.assertNotIn("Pushika", block)

    def test_failure_raises_instead_of_returning_source(self):
        tr = OpenRouterTranslator(["k1", "k2"], ["m1", "m2"])
        tr._post = lambda key, model, messages: (_ for _ in ()).throw(_AttemptFailed("429"))
        rotations = []
        tr.on_key_rotate = lambda *a: rotations.append(a)
        with self.assertRaises(TranslationAPIError):
            tr.translate_single("こんにちは")
        self.assertEqual(len(rotations), 1)  # rotated once and persisted via callback

    def test_batch_bad_json_falls_back_to_single(self):
        tr = OpenRouterTranslator(["k"], ["m"])
        answers = iter(["not json", "A", "B"])
        tr._post = lambda key, model, messages: next(answers)
        self.assertEqual(tr.translate_batch(["あ", "い"]), ["A", "B"])


class TestPipeline(ProjectFixture):
    def test_memory_and_dedup_and_locks(self):
        tr = FakeTranslator()
        rows = pipeline.select_rows(self.db)
        raws = {r[2] for r in rows}
        self.assertNotIn("マリーカ", raws)          # locked key never sent
        self.assertNotIn("ラベル", raws)
        events = list(pipeline.run_translation(self.db, rows, tr, batch_size=10))
        self.assertEqual(events[-1]["type"], "complete")
        sent = [t for call in tr.calls for t in call]
        self.assertEqual(len(sent), len(set(sent)))  # dedup
        rows_after = self.rows()
        self.assertEqual(rows_after["はい"][3], 1)  # machine -> status 1
        self.assertEqual(rows_after["マリーカ"][4], "")  # locked stays empty
        with connect(self.db) as conn:
            counts = status_counts(conn)
        self.assertEqual(counts["empty"], 0)

    def test_error_leaves_rows_untouched(self):
        class Failing(FakeTranslator):
            def translate_batch(self, texts, **kw):
                raise TranslationAPIError(429, "quota")
        rows = pipeline.select_rows(self.db)
        events = list(pipeline.run_translation(self.db, rows, Failing(), batch_size=10))
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(self.rows()["はい"][3], 0)

    def test_status_migration(self):
        with connect(self.db) as conn:
            conn.execute("UPDATE translation_rows SET mtl = 'Vâng', translated = 'Vâng', status = 2 WHERE raw = 'はい'")
            conn.execute("UPDATE translation_rows SET mtl = 'X', translated = 'Đã sửa', status = 2 "
                         "WHERE raw = '地図の台詞'")
            conn.execute("UPDATE translation_rows SET mtl = 'こんにちは', translated = 'こんにちは', status = 2 "
                         "WHERE raw LIKE '%こんにちは%'")
        pipeline.migrate_status_semantics(self.db)
        rows = self.rows()
        self.assertEqual(rows["はい"][3], 1)        # unedited AI -> machine
        self.assertEqual(rows["地図の台詞"][3], 2)  # human edit stays reviewed
        self.assertEqual(rows["\\Eマリーカ\n「こんにちは」"][3], 3)  # garbage -> QA

    def test_validator_detects_new_label_errors(self):
        files = {"common/0_test.json": rj(os.path.join(self.dump, "common", "0_test.json")),
                 "db/DataBase.json": rj(os.path.join(self.dump, "db", "DataBase.json"))}
        base = check_dump(files)
        files["common/0_test.json"]["commands"][5]["stringArgs"][0] = "Nhãn"
        files["db/DataBase.json"]["types"][0]["data"][0]["name"] = "Thảo dược"
        new = check_dump(files) - base
        self.assertTrue(any("[LABEL]" in e for e in new))
        self.assertTrue(any("[DB]" in e for e in new))


if __name__ == "__main__":
    unittest.main()
