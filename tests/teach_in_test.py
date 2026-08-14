"""Tests for Eltako teach-in payloads and catalog associations."""

import unittest

from eltakobus.eep import A5_10_06, A5_10_12, A5_38_08, H5_3F_7F
from eltakobus.teach_in import (
    build_teach_in_message,
    get_teach_in_payload,
    teach_in_button_eep_names,
    teach_in_devices,
    teach_in_profiles_for_device,
    supports_teach_in_button,
)


class TeachInTest(unittest.TestCase):
    """The Eltako teach-in table must stay aligned with device mappings."""

    def test_known_payloads_are_exact(self):
        """The four documented Eltako sender payloads remain byte-for-byte stable."""
        expected = {
            A5_10_06: bytes.fromhex("40 30 0D 85"),
            A5_10_12: bytes.fromhex("40 90 0D 80"),
            A5_38_08: bytes.fromhex("E0 40 0D 80"),
            H5_3F_7F: bytes.fromhex("FF F8 0D 80"),
        }
        for profile, payload in expected.items():
            with self.subTest(profile=profile.eep_string):
                self.assertTrue(supports_teach_in_button(profile))
                self.assertEqual(payload, get_teach_in_payload(profile.eep_string))

    def test_message_has_eltako_outgoing_fields(self):
        """The helper creates the same outgoing 4BS message as the integration."""
        message = build_teach_in_message(bytes.fromhex("01020304"), "A5_38_08")
        self.assertEqual(0x07, message.org)
        self.assertTrue(message.outgoing)
        self.assertEqual(0x80, message.status)
        self.assertEqual(bytes.fromhex("E0 40 0D 80"), message.data)

    def test_unknown_profiles_are_safe(self):
        """Unknown or non-teachable profiles do not get guessed payloads."""
        self.assertFalse(supports_teach_in_button("F6-02-01"))
        self.assertIsNone(get_teach_in_payload("F6-02-01"))
        with self.assertRaises(ValueError):
            build_teach_in_message(bytes(4), "F6-02-01")

    def test_teach_in_profiles_are_linked_to_catalog_devices(self):
        """Catalog sender mappings expose FSB14 and climate devices correctly."""
        fsb = teach_in_profiles_for_device("FSB14")
        self.assertTrue(any(entry.get("sender_eep") == "H5-3F-7F" for entry in fsb))
        climate = teach_in_profiles_for_device("FHK14")
        self.assertTrue(any(entry.get("sender_eep") == "A5-10-06" for entry in climate))
        self.assertIn("A5-10-06", teach_in_button_eep_names())
        self.assertTrue(teach_in_devices("H5-3F-7F"))


if __name__ == "__main__":
    unittest.main()
