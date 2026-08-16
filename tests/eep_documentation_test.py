"""Tests for the short in-code documentation of registered EEPs."""

import unittest

from eltakobus.eep import A5_38_08, CentralCommandSwitching, EEP
from eltakobus.message import Regular4BSMessage


class TestEEPDocumentation(unittest.TestCase):
    """Ensure every registered profile remains self-describing."""

    def test_every_registered_eep_has_a_short_metadata_summary(self):
        """Names and descriptions are available without decoding a telegram."""
        registry = EEP._EEP__sublasses_by_string
        self.assertGreaterEqual(len(registry), 71)
        for eep, profile in registry.items():
            with self.subTest(eep=eep):
                self.assertTrue(profile.get_metadata().name)
                self.assertTrue(profile.get_metadata().description)

    def test_central_switch_lock_is_a_command_bit(self):
        """DB0.2 is exposed as lock and survives a decode/encode round trip."""
        message = Regular4BSMessage(bytes(4), 0, bytes((1, 0, 10, 0x05)))
        decoded = A5_38_08.decode_message(message)
        self.assertTrue(decoded.switching.lock)
        self.assertIn("actuator lock", CentralCommandSwitching.__doc__)
        encoded = decoded.encode_message(bytes(4))
        self.assertEqual(1, (encoded.data[3] >> 2) & 1)


if __name__ == "__main__":
    unittest.main()
