"""Regression tests for EEP fixes derived from open upstream pull requests."""

import unittest

from eltakobus.eep import A5_10_03, H5_3F_7F
from eltakobus.message import Regular4BSMessage


def four_bs(data):
    """Build an incoming 4BS telegram for an EEP decoder."""
    return Regular4BSMessage(bytes.fromhex("01020304"), 0, bytes(data))


class TestA51003SetPointRange(unittest.TestCase):
    """Protect the documented 8..30 °C A5-10-03 set-point range."""

    def test_decode_adds_the_lower_temperature_bound(self):
        """Raw 0 and 255 map to 8 °C and 30 °C rather than 0 °C and 22 °C."""
        low = A5_10_03.decode_message(four_bs((0, 0, 0, 0)))
        high = A5_10_03.decode_message(four_bs((0, 255, 0, 0)))

        self.assertEqual(8.0, low.target_temperature)
        self.assertEqual(30.0, high.target_temperature)

    def test_encode_uses_the_same_offset_as_decode(self):
        """Encoding the documented boundaries produces the matching raw bytes."""
        low = A5_10_03(8.0, 20.0).encode_message(bytes.fromhex("01020304"))
        high = A5_10_03(30.0, 20.0).encode_message(bytes.fromhex("01020304"))

        self.assertEqual(0, low.data[1])
        self.assertEqual(255, high.data[1])


class TestH53F7FTimeResolution(unittest.TestCase):
    """Verify compatible whole-second and precise 100-ms shutter commands."""

    def test_existing_whole_second_constructor_remains_compatible(self):
        """The original three-argument API still encodes seconds unchanged."""
        command = H5_3F_7F(12, 1, 0)
        encoded = command.encode_message(bytes.fromhex("01020304"))
        decoded = H5_3F_7F.decode_message(encoded)

        self.assertTrue(command.send_time_in_seconds)
        self.assertEqual(12, encoded.data[1])
        self.assertEqual(12, decoded.time)
        self.assertTrue(decoded.send_time_in_seconds)

    def test_100ms_mode_round_trips_seconds_and_sets_the_flag(self):
        """A fractional duration is encoded in 100-ms units and decoded symmetrically."""
        command = H5_3F_7F(12.3, 2, 1, send_time_in_seconds=False)
        encoded = command.encode_message(bytes.fromhex("01020304"))
        decoded = H5_3F_7F.decode_message(encoded)

        self.assertEqual(123, (encoded.data[0] << 8) | encoded.data[1])
        self.assertEqual(0x0A, encoded.data[3])
        self.assertAlmostEqual(12.3, decoded.time)
        self.assertFalse(decoded.send_time_in_seconds)

    def test_time_ranges_are_rejected_before_encoding(self):
        """Invalid second and 100-ms values fail before malformed telegrams are sent."""
        with self.assertRaises(ValueError):
            H5_3F_7F(256, 1, 0).encode_message(bytes(4))
        with self.assertRaises(ValueError):
            H5_3F_7F(6553.6, 1, 0, send_time_in_seconds=False).encode_message(bytes(4))


if __name__ == "__main__":
    unittest.main()
