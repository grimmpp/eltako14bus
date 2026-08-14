"""Tests that the source package exposes the intended release metadata."""

import ast
import unittest
from pathlib import Path


class TestPackageMetadata(unittest.TestCase):
    """Keep the build version, changelog and release documentation aligned."""

    def test_setup_version_is_1_0_1(self):
        """The packaging source of truth must identify release 1.0.1."""
        setup_file = Path(__file__).parents[1] / "setup.py"
        tree = ast.parse(setup_file.read_text())
        setup_call = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.Call)
                          and getattr(node.func, "attr", None) == "setup")
        version = next(keyword.value.value for keyword in setup_call.keywords
                       if keyword.arg == "version")
        self.assertEqual("1.0.1", version)

    def test_release_docs_name_the_same_version(self):
        """Release notes and the release guide must mention the same version."""
        root = Path(__file__).parents[1]
        self.assertIn("## 1.0.1", (root / "CHANGES.md").read_text())
        self.assertIn("v1.0.1", (root / "docs" / "RELEASING.md").read_text())


if __name__ == "__main__":
    unittest.main()
