"""Compatibility checks for the public eltakobus API used by home-assistant-eltako.

The test intentionally does not import Home Assistant.  It verifies the library
side of the integration contract: names, EEP identifiers, constructors,
properties, and common outgoing telegrams.
"""

import unittest
import ast
from pathlib import Path
import subprocess
import sys

from eltakobus.eep import (
    A5_04_01, A5_04_02, A5_04_03, A5_06_01, A5_07_01, A5_08_01,
    A5_09_0C, A5_10_03, A5_10_06, A5_10_12, A5_12_01, A5_12_02,
    A5_12_03, A5_13_01, A5_30_01, A5_30_03, A5_38_08,
    CentralCommandDimming, CentralCommandSwitching, D5_00_01, EEP,
    F6_01_01, F6_02_01, F6_02_02, F6_10_00, G5_3F_7F, H5_3F_7F,
    M5_38_08, VOC_SubstancesType, WindowHandlePosition,
)


ADDRESS = bytes.fromhex("01020304")


class HomeAssistantCompatibilityTest(unittest.TestCase):
    """Protect the API consumed by the integration without an HA dependency."""

    IMPORTED_EEPS = (
        A5_04_01, A5_04_02, A5_04_03, A5_06_01, A5_07_01, A5_08_01,
        A5_09_0C, A5_10_03, A5_10_06, A5_10_12, A5_12_01, A5_12_02,
        A5_12_03, A5_13_01, A5_30_01, A5_30_03, A5_38_08, D5_00_01,
        F6_01_01, F6_02_01, F6_02_02, F6_10_00, G5_3F_7F, H5_3F_7F,
        M5_38_08,
    )

    def test_all_integration_imports_are_registered(self):
        """Every EEP imported by the integration keeps its public identifier."""
        for profile in self.IMPORTED_EEPS:
            with self.subTest(profile=profile.__name__):
                self.assertIs(EEP.find(profile.eep_string), profile)

    def test_sensor_constructor_contracts_remain_usable(self):
        """Common sensor constructors used by integration configuration remain valid."""
        values = (
            A5_04_01(20, 50, 1, 1), A5_04_02(20, 50, 1),
            A5_04_03(20, 50, 1, 1), A5_06_01(1, 300, 300),
            A5_07_01(0, 0, 0, 1, 1), A5_08_01(1, 2, 20, 1, 0, 0),
            A5_09_0C(100, VOC_SubstancesType.VOCT_TOTAL),
            A5_10_03(20, 20), A5_10_12(20, 20, 50),
            A5_30_01(255, 0, 1), A5_30_03(20, 0x1F, 0x08),
        )
        self.assertEqual(len(values), 11)

    def test_integration_outgoing_commands_keep_wire_types(self):
        """Switch, dimmer, climate, and cover calls still produce ESP2 messages."""
        switching = CentralCommandSwitching(0, 1, 0, 0, 1)
        dimming = CentralCommandDimming(50, 0, 1, 0, 0, 1)
        messages = (
            A5_38_08(command=1, switching=switching).encode_message(ADDRESS),
            A5_38_08(command=2, dimming=dimming).encode_message(ADDRESS),
            A5_10_06(A5_10_06.HeaterMode.NORMAL, 20, current_temp=20,
                     priority=A5_10_06.ControllerPriority.AUTO).encode_message(ADDRESS),
            F6_02_01(1, 1, 0, 0).encode_message(ADDRESS),
            F6_02_02(1, 0, 0, 0).encode_message(ADDRESS),
            H5_3F_7F(12, 1, 1).encode_message(ADDRESS),
            M5_38_08(1).encode_message(ADDRESS),
        )
        self.assertEqual([message.org for message in messages], [7, 7, 7, 5, 5, 7, 5])

    def test_integration_read_only_profiles_are_explicit(self):
        """A5-09-0C and weather profiles remain usable for decoding."""
        self.assertTrue(hasattr(A5_09_0C, 'decode_message'))
        self.assertTrue(hasattr(A5_13_01, 'decode_message'))
        self.assertEqual(WindowHandlePosition.OPEN, WindowHandlePosition.get_position(0xC))
        self.assertEqual(F6_10_00.eep_string, 'F6-10-00')

    def test_library_has_no_home_assistant_import_dependency(self):
        """The compatibility contract must not turn HA into a library dependency."""
        package_root = Path(__file__).resolve().parents[1] / 'eltakobus'
        forbidden = {'homeassistant', 'custom_components'}
        for source_file in package_root.rglob('*.py'):
            source = source_file.read_text(encoding='utf-8')
            self.assertNotIn('custom_components', source)
            self.assertNotIn('home-assistant-eltako', source)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported = [alias.name.split('.')[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported = [node.module.split('.')[0]]
                else:
                    continue
                self.assertTrue(
                    forbidden.isdisjoint(imported),
                    f'{source_file} imports an integration-only module: {imported}',
                )

    def test_public_compatibility_api_loads_in_an_isolated_process(self):
        """EEP and catalog imports work without HA installed or imported."""
        script = (
            'from eltakobus.eep import A5_10_06, EEP\n'
            'from eltakobus.device_catalog import find_hw_type\n'
            'assert EEP.find("A5-10-06") is A5_10_06\n'
            'assert find_hw_type("FSR14-4x")["eep"] == "M5-38-08"\n'
        )
        result = subprocess.run(
            [sys.executable, '-c', script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)


if __name__ == '__main__':
    unittest.main()
