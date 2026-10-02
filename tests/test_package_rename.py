"""Check model compatibility and both entry points after package relocation."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from embryo_analyser.classifiers import load_bundle, save_bundle, ModelBundle
from embryo_analyser.workflow import DEFAULT_MODEL_FILE

class PackageRenameTests(unittest.TestCase):
    def test_legacy_bundle_loads_and_new_bundle_uses_current_namespace(self):
        original = DEFAULT_MODEL_FILE.read_bytes()
        bundle = load_bundle(DEFAULT_MODEL_FILE)
        self.assertIsInstance(bundle, ModelBundle)
        self.assertEqual(set(bundle.models), {"rf", "svm"})
        self.assertEqual(bundle.metadata["training_embryos"], 14)
        self.assertEqual(type(bundle).__module__, "embryo_analyser.classifiers")
        with tempfile.TemporaryDirectory() as temporary:
            saved = save_bundle(bundle, Path(temporary) / "model.joblib")
            loaded = load_bundle(saved)
            self.assertEqual(loaded.selected_columns, bundle.selected_columns)
            self.assertEqual(type(loaded.preprocessing).__module__, "embryo_analyser.preprocessing")
        self.assertEqual(DEFAULT_MODEL_FILE.read_bytes(), original)

    def test_script_and_module_entry_points(self):
        root = Path(__file__).resolve().parents[1]
        for args in ([str(root / "embryo_analyser/workflow.py")],
                     ["-m", "embryo_analyser.workflow"]):
            with self.subTest(args=args):
                completed = subprocess.run([sys.executable, *args, "--help"], cwd=root,
                                           capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn("classify", completed.stdout)
