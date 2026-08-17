"""Tests that the source package exposes the intended release metadata."""

import ast
import unittest
from pathlib import Path


class TestPackageMetadata(unittest.TestCase):
    """Keep the build version, changelog and release documentation aligned."""

    def test_setup_version_is_2_0_0_rc1(self):
        """The packaging source of truth must identify the v2 release candidate."""
        setup_file = Path(__file__).parents[1] / "setup.py"
        tree = ast.parse(setup_file.read_text())
        setup_call = next(node for node in ast.walk(tree)
                          if isinstance(node, ast.Call)
                          and getattr(node.func, "attr", None) == "setup")
        version = next(keyword.value.value for keyword in setup_call.keywords
                       if keyword.arg == "version")
        self.assertEqual("2.0.0rc1", version)

    def test_release_docs_name_the_same_version(self):
        """Release notes and the release guide must mention the same version."""
        root = Path(__file__).parents[1]
        self.assertIn("## 2.0.0rc1", (root / "CHANGES.md").read_text())
        self.assertIn("v2.0.0rc1", (root / "docs" / "RELEASING.md").read_text())

    def test_retired_esp3_dependencies_are_not_declared(self):
        """Native ESP3 support must not pull in retired third-party packages."""
        root = Path(__file__).parents[1]
        requirements = (root / "requirements.txt").read_text().lower()
        setup = (root / "setup.py").read_text().lower()
        workflows = "\n".join(path.read_text().lower()
                                  for path in (root / ".github" / "workflows").glob("*.yml"))
        self.assertNotIn("enocean", requirements)
        self.assertNotIn("enocean", setup)
        self.assertIn("zeroconf", requirements)
        self.assertIn("'discovery': ['zeroconf", setup)
        self.assertNotIn("'esp3'", setup)


if __name__ == "__main__":
    unittest.main()
