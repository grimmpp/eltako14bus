"""Tests for the HA-independent device and EEP catalog."""

import unittest

from eltakobus.device_catalog import (
    DEVICE_CATALOG,
    catalog_eep_references,
    describe_gateway_type,
    devices_for_eep,
    eep_device_mapping,
    entries_for_hw_type,
    find_hw_type,
    normalize_hw_type,
)
from eltakobus.eep import EEP


class DeviceCatalogTest(unittest.TestCase):
    """The catalog must resolve devices without importing Home Assistant."""

    def test_catalog_contains_real_devices_and_eep_references(self):
        """Known products expose the EEP used by their telegrams."""
        self.assertGreaterEqual(len(DEVICE_CATALOG), 80)
        self.assertEqual('A5-10-06', find_hw_type('FUTH')['eep'])
        self.assertEqual('F6-10-00', find_hw_type('ftke')['eep'])
        self.assertEqual('M5-38-08', find_hw_type('FSR14-1x')['eep'])

    def test_name_normalization_supports_common_tool_spellings(self):
        """PCT14 and device-manager spellings resolve to the same product."""
        self.assertEqual('FSR14_4X', normalize_hw_type('FSR14-4x'))
        self.assertEqual(find_hw_type('FSR14_4x'), find_hw_type('FSR14-4x'))

    def test_gateway_mapping_is_independent_of_serial_access(self):
        """Gateway descriptions are static data and do not open hardware."""
        self.assertEqual('FAM14', describe_gateway_type('fam14')['hw_type'])
        self.assertEqual('USB300', describe_gateway_type('enocean-usb300')['hw_type'])
        self.assertIsNone(describe_gateway_type('fam14').get('docs'))

    def test_eep_mapping_contains_only_registered_profiles(self):
        """Every catalog EEP can be resolved through the public EEP registry."""
        mapping = eep_device_mapping(include_sender=True)
        self.assertEqual(set(catalog_eep_references()), set(mapping))
        for eep in mapping:
            with self.subTest(eep=eep):
                self.assertIsNotNone(EEP.find(eep))
                self.assertTrue(devices_for_eep(eep, include_sender=True))

    def test_sender_profiles_are_available_for_actuators(self):
        """Outgoing actuator mappings are queryable separately from sensor EEPs."""
        received = devices_for_eep('H5-3F-7F')
        all_entries = devices_for_eep('H5-3F-7F', include_sender=True)
        self.assertEqual([], received)
        self.assertTrue(any(entry['hw_type'] == 'FSB14' for entry in all_entries))

    def test_multisensors_default_to_d21441_and_expose_d2_alternatives(self):
        """Factory defaults stay first while NFC-selectable D2 profiles remain queryable."""
        for hw_type in ('FMMS44SB', 'FMS55SB', 'FMS55ESB', 'FMS65ESB'):
            with self.subTest(hw_type=hw_type):
                self.assertEqual('D2-14-41', find_hw_type(hw_type)['eep'])
                profiles = [entry['eep'] for entry in entries_for_hw_type(hw_type)]
                self.assertEqual('D2-14-41', profiles[0])
                self.assertIn('D2-14-40', profiles)

        self.assertIn('D2-00-01',
                      [entry['eep'] for entry in entries_for_hw_type('FMMS44SB')])
        for hw_type in ('FMS55SB', 'FMS55ESB', 'FMS65ESB'):
            self.assertNotIn('D2-00-01',
                             [entry['eep'] for entry in entries_for_hw_type(hw_type)])


if __name__ == '__main__':
    unittest.main()
