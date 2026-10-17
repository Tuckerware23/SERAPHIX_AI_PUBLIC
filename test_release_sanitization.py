"""Synthetic offline checks for the sanitized source-review package."""
import ast
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

import seraphix_config as config
import seraphix_canon_intelligence as canon
import seraphix_book_guard_v284 as guard
import seraphix_manuscript_library as library
import seraphix_narrative_engine as narrative
import seraphix_tools_v281 as tools

BASE = Path(__file__).resolve().parent


class ReleaseTests(unittest.TestCase):
    def test_all_python_compiles_and_local_import_symbols_exist(self):
        trees = {p.stem: ast.parse(p.read_text(encoding="utf-8")) for p in BASE.glob("*.py")}
        for module, tree in trees.items():
            with self.subTest(module=module):
                compile(tree, module, "exec")
                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("seraphix_"):
                        self.assertIn(node.module, trees)
                        exports = {
                            n.name for n in trees[node.module].body
                            if isinstance(n, (ast.FunctionDef, ast.ClassDef))
                        }
                        exports.update(n.id for n in ast.walk(trees[node.module])
                                       if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
                        exports.update(a.asname or a.name
                                       for n in ast.walk(trees[node.module])
                                       if isinstance(n, (ast.ImportFrom, ast.Import)) for a in n.names)
                        self.assertTrue(all(alias.name in exports for alias in node.names))

    def test_example_config_has_no_active_story_rules(self):
        settings = config.load_settings(BASE / "Config/config.example.json")
        self.assertEqual(settings, config.DEFAULTS)
        self.assertTrue(all(not value for value in settings.values()))

    def test_bad_configuration_fails_explicitly(self):
        cases = [[], {"unknown": True}, {"entities": "not-list"},
                 {"identity_rules": [{}]}, {"unsupported_patterns": ["["]}]
        with tempfile.TemporaryDirectory(prefix="seraphix_synthetic_") as folder:
            target = Path(folder) / "synthetic.json"
            for data in cases:
                with self.subTest(data=data):
                    target.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises((ValueError, TypeError, re.error)):
                        config.load_settings(target)

    def test_configured_identity_requires_source_match(self):
        settings = dict(config.DEFAULTS)
        settings["identity_rules"] = [{
            "question_terms": ["who", "Alex"],
            "source_pattern": r"Alex is the station pilot\.",
            "answer": "Alex is the station pilot. (Synthetic configured example)",
        }]
        chunks = [{"id": 1, "text": "Alex is the station pilot.", "start": {"paragraph": 1}}]
        with patch.object(canon, "SETTINGS", settings), patch.object(canon, "load", return_value=chunks):
            self.assertTrue(canon.is_identity_question("Who is Alex?"))
            self.assertIn("[Book chunk 1]", canon.known_identity_answer("unused"))
            self.assertFalse(canon.is_identity_question("Who is Blair?"))
        with patch.object(canon, "SETTINGS", settings), patch.object(canon, "load", return_value=[]):
            self.assertIsNone(canon.known_identity_answer("unused"))

    def test_unconfigured_identity_does_not_invent_answer(self):
        with patch.object(canon, "SETTINGS", config.DEFAULTS), patch.object(canon, "load", return_value=[]):
            self.assertFalse(canon.is_identity_question("Who is Alex?"))
            self.assertIsNone(canon.known_identity_answer("unused"))

    def test_configured_legacy_retrieval_contract(self):
        settings = dict(config.DEFAULTS)
        settings["retrieval_rules"] = [{
            "question_terms": ["pilot"], "source_pattern": "station pilot"}]
        chunks = [{"id": 1, "text": "Alex is the station pilot.", "start": {"paragraph": 1}},
                  {"id": 2, "text": "Blair waits by the hatch.", "start": {"paragraph": 2}}]
        with patch.object(canon, "SETTINGS", settings), patch.object(canon, "load", return_value=chunks):
            text, selected = canon.build_evidence("pilot", "unused")
        self.assertEqual([ch["id"] for ch in selected], [1, 2])
        self.assertIn("[Book chunk 1;", text)

    def test_generic_guard_preserves_citation_checks(self):
        answer = "Alex waited beside the station hatch. [Book chunk 1]"
        self.assertTrue(guard.inspect(answer, ["1"])[0])
        self.assertFalse(guard.inspect(answer, ["2"])[0])
        messages = guard.make_messages("Synthetic question", "Synthetic source")
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertIn("[Book chunk N]", messages[0]["content"])

    def test_generic_legacy_index_names_agree(self):
        import seraphix_book_qa as qa
        self.assertEqual(canon.INDEX, qa.INDEX_REL)
        tree = ast.parse((BASE / "seraphix_book_reader.py").read_text(encoding="utf-8"))
        names = [n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        self.assertIn(canon.INDEX.name, names)

    def test_entities_are_optional_configuration_in_both_retrievers(self):
        for module in (library, narrative):
            source = (BASE / (module.__name__ + ".py")).read_text(encoding="utf-8")
            self.assertIn('SETTINGS["entities"]', source)
        self.assertEqual(config.DEFAULTS["entities"], [])

    def test_workspace_read_denies_escape_and_secrets(self):
        with tempfile.TemporaryDirectory(prefix="seraphix_synthetic_") as folder:
            root = Path(folder)
            workspace = root / "workspace"
            workspace.mkdir()
            (workspace / "sample.txt").write_text("Synthetic harmless note.", encoding="utf-8")
            (root / "outside.txt").write_text("Synthetic outside note.", encoding="utf-8")
            (workspace / "credentials.json").write_text("{}", encoding="utf-8")
            with patch.object(tools, "DRIVE", workspace):
                self.assertIn("Synthetic harmless note.", tools.read_drive("sample.txt"))
                self.assertIn("Access denied", tools.read_drive("../outside.txt"))
                self.assertIn("Access denied", tools.read_drive(str(root / "outside.txt")))
                self.assertIn("Access denied", tools.read_drive("credentials.json"))

    def test_workspace_search_and_natural_language_use_configured_root(self):
        with tempfile.TemporaryDirectory(prefix="seraphix_synthetic_") as folder:
            workspace = Path(folder)
            (workspace / "sample.txt").write_text("Synthetic note.", encoding="utf-8")
            with patch.object(tools, "DRIVE", workspace):
                self.assertIn("sample.txt", tools.search_drive("sample"))
                result = tools.handle_assistant_request("find files named sample in workspace", BASE)
                self.assertIn("sample.txt", result)

    def test_environment_paths_resolve_relative_to_release(self):
        with patch.dict("os.environ", {"SERAPHIX_SYNTHETIC_PATH": "Assistant_Workspace/synthetic"}):
            self.assertEqual(config.configured_path("SERAPHIX_SYNTHETIC_PATH", "unused"),
                             (BASE / "Assistant_Workspace/synthetic").resolve())

    def test_voice_demo_import_does_not_load_optional_models_or_write(self):
        spec = importlib.util.spec_from_file_location("synthetic_voice_demo", BASE / "test_kokoro_voices.py")
        module = importlib.util.module_from_spec(spec)
        with patch.object(Path, "mkdir", side_effect=AssertionError("Unexpected write")):
            spec.loader.exec_module(module)
        self.assertTrue(callable(module.main))
        self.assertNotIn("KPipeline", vars(module))


if __name__ == "__main__":
    unittest.main()
