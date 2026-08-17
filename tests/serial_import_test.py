"""Tests for the optional serial dependency boundary."""

import subprocess
import sys
import unittest
import os
from pathlib import Path


class SerialImportBoundaryTest(unittest.TestCase):
    """The core package must not require serial libraries until a serial transport is used."""

    ROOT = Path(__file__).resolve().parents[1]

    def _run_without_site_packages(self, script):
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, "-S", "-c", script],
            cwd=self.ROOT,
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )

    def test_core_import_does_not_require_serial_dependencies(self):
        """A minimal installation can use EEP/message APIs without pyserial."""
        result = self._run_without_site_packages(
            "import eltakobus; from eltakobus import EEP; assert EEP"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_new_core_apis_do_not_pull_in_optional_transports(self):
        """New schema, memory and diagnostics APIs retain the core-only boundary.

        The package root currently re-exports these additive APIs for
        compatibility with historic ``from eltakobus import ...`` usage.  This
        process deliberately has no site packages, so the assertion catches an
        accidental import of serial, CoAP, YAML or Home Assistant code.
        """
        result = self._run_without_site_packages(
            "from eltakobus import (D2_00_01_SCHEMA, MemorySession, "
            "snapshot_gateway); "
            "assert D2_00_01_SCHEMA and MemorySession and snapshot_gateway"
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_explicit_serial_import_has_actionable_error(self):
        """Using a serial transport explains how to install the optional extra."""
        result = self._run_without_site_packages("import eltakobus.serial")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("eltako14bus[serial]", result.stderr)
        self.assertIn("optional serial dependencies", result.stderr)

    def test_package_level_serial_name_remains_lazy(self):
        """The legacy package-level class name resolves only when its extra is installed."""
        result = self._run_without_site_packages("from eltakobus import RS485SerialInterfaceV2")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("eltako14bus[serial]", result.stderr)


if __name__ == "__main__":
    unittest.main()
