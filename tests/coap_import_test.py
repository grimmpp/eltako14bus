"""Regression tests for optional CoAP dependency loading."""

import subprocess
import sys
import unittest
from pathlib import Path


class CoAPImportTest(unittest.TestCase):
    """Importing the core library must not execute the optional CoAP package."""

    def test_coap_dependency_is_loaded_lazily(self):
        """A core import remains usable when aiocoap is not imported yet."""
        script = (
            "import sys\n"
            "from eltakobus.coap import CoAPInterface\n"
            "assert CoAPInterface\n"
            "assert 'aiocoap' not in sys.modules\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == "__main__":
    unittest.main()
