"""Protocol-level validation tests for the registered EEP implementations.

These tests deliberately use raw ESP2 4BS/RPS payloads.  They document the
wire layout from the EEP tables and catch accidental changes to DB ordering,
scaling, reserved bits, and the public metadata API.
"""

import unittest

from eltakobus.eep import (
    A5_02_01, A5_02_02, A5_02_03, A5_02_04, A5_02_05, A5_02_06,
    A5_02_07, A5_02_08, A5_02_09, A5_02_0A, A5_02_0B, A5_02_10,
    A5_02_11, A5_02_12, A5_02_13, A5_02_14, A5_02_15, A5_02_16,
    A5_02_17, A5_02_18, A5_02_19, A5_02_1A, A5_02_1B, A5_02_20,
    A5_02_30, A5_06_03, A5_07_02, A5_07_03, EEP,
    A5_04_03,
)
from eltakobus.error import WrongOrgError
from eltakobus.message import RPSMessage, Regular4BSMessage


def four_bs(data):
    """Create an incoming ESP2 4BS message with DB3 first in ``data``."""
    return Regular4BSMessage(bytes.fromhex("01020304"), 0, bytes(data))


class TestA502Family(unittest.TestCase):
    """Check every implemented 8-bit and 10-bit A5-02 temperature range."""

    EIGHT_BIT_PROFILES = (
        (A5_02_01, -40.0, 0.0),
        (A5_02_02, -30.0, 10.0),
        (A5_02_03, -20.0, 20.0),
        (A5_02_04, -10.0, 30.0),
        (A5_02_05, 0.0, 40.0),
        (A5_02_06, 10.0, 50.0),
        (A5_02_07, 20.0, 60.0),
        (A5_02_08, 30.0, 70.0),
        (A5_02_09, 40.0, 80.0),
        (A5_02_0A, 50.0, 90.0),
        (A5_02_0B, 60.0, 100.0),
        (A5_02_10, -60.0, 20.0),
        (A5_02_11, -50.0, 30.0),
        (A5_02_12, -40.0, 40.0),
        (A5_02_13, -30.0, 50.0),
        (A5_02_14, -20.0, 60.0),
        (A5_02_15, -10.0, 70.0),
        (A5_02_16, 0.0, 80.0),
        (A5_02_17, 10.0, 90.0),
        (A5_02_18, 20.0, 100.0),
        (A5_02_19, 30.0, 110.0),
        (A5_02_1A, 40.0, 120.0),
        (A5_02_1B, 50.0, 130.0),
    )

    def test_eight_bit_ranges_use_db1_and_have_correct_metadata(self):
        """Raw DB1 boundaries and metadata must agree for every profile."""
        for profile, minimum, maximum in self.EIGHT_BIT_PROFILES:
            with self.subTest(profile=profile.__name__):
                self.assertAlmostEqual(
                    minimum,
                    profile.decode_message(four_bs((0, 0, 255, 1))).current_temperature,
                )
                self.assertAlmostEqual(
                    maximum,
                    profile.decode_message(four_bs((0, 0, 0, 1))).current_temperature,
                )
                field = profile.get_metadata().field("current_temperature")
                self.assertEqual((minimum, maximum), field.value_range)

    def test_eight_bit_round_trip_is_within_one_lsb(self):
        """Encoding a mid-range value must decode back within one wire LSB."""
        for profile, minimum, maximum in self.EIGHT_BIT_PROFILES:
            with self.subTest(profile=profile.__name__):
                value = (minimum + maximum) / 2
                decoded = profile.decode_message(
                    profile(value).encode_message(bytes(4)))
                self.assertLessEqual(
                    abs(decoded.current_temperature - value),
                    (maximum - minimum) / 255 + 0.001,
                )

    def test_ten_bit_ranges_and_wire_position(self):
        """A5-02-20/30 use DB2.1..DB1.0, not the 8-bit DB1 field."""
        for profile, minimum, maximum in (
            (A5_02_20, -10.0, 41.2), (A5_02_30, -40.0, 62.3)
        ):
            with self.subTest(profile=profile.__name__):
                encoded = profile(minimum).encode_message(bytes(4))
                self.assertEqual(0x03, encoded.data[1])
                self.assertEqual(0xFF, encoded.data[2])
                self.assertAlmostEqual(
                    minimum, profile.decode_message(encoded).current_temperature, places=1)
                self.assertAlmostEqual(
                    maximum,
                    profile.decode_message(four_bs((0, 0, 0, 1))).current_temperature,
                    places=1,
                )


class TestOccupancyAndLightLayouts(unittest.TestCase):
    """Check the shared supply-voltage, error, and bit-field conventions."""

    def test_supply_error_codes_are_not_interpreted_as_voltage(self):
        """251..255 are error codes while the exposed voltage is clamped."""
        for profile in (A5_06_03, A5_07_02, A5_07_03):
            with self.subTest(profile=profile.__name__):
                decoded = profile.decode_message(four_bs((255, 0, 0, 0)))
                self.assertEqual(255, decoded.error_code)
                self.assertEqual(5.0, decoded.supply_voltage)

    def test_10_bit_illumination_preserves_both_bytes(self):
        """A5-06-03 uses DB2 as MSBs and DB1 bits 7..6 as LSBs."""
        decoded = A5_06_03.decode_message(four_bs((0, 0x80, 0x40, 0)))
        self.assertEqual(513, decoded.illumination)
        encoded = A5_06_03(1.0, 513).encode_message(bytes(4))
        self.assertEqual((0x80, 0x40), (encoded.data[1], encoded.data[2]))

    def test_a50403_uses_standard_10bit_temperature_layout(self):
        """A5-04-03 stores humidity in DB3 and temperature in DB2/DB1."""
        decoded = A5_04_03.decode_message(four_bs((128, 0x02, 0x00, 0)))
        self.assertAlmostEqual(50.2, decoded.humidity, places=1)
        self.assertAlmostEqual(20.0, decoded.current_temperature, places=1)
        encoded = A5_04_03(20.0, 50.0).encode_message(bytes(4))
        self.assertEqual(127, encoded.data[0])
        self.assertEqual((0x02, 0x00), (encoded.data[1], encoded.data[2]))


class TestEEPContracts(unittest.TestCase):
    """Check contracts shared by all EEP decoders and metadata consumers."""

    def test_wrong_org_is_rejected(self):
        """4BS profiles must not accept an RPS telegram by accident."""
        message = RPSMessage(bytes.fromhex("01020304"), 0, bytes((0,)))
        with self.assertRaises(WrongOrgError):
            A5_02_05.decode_message(message)

    def test_find_returns_registered_profile_and_metadata_is_json_ready(self):
        """Concrete classes remain discoverable through the legacy registry."""
        for profile in (A5_02_01, A5_02_20, A5_02_30, A5_06_03, A5_07_02):
            with self.subTest(profile=profile.__name__):
                self.assertIs(profile, EEP.find(profile.__name__.replace("_", "-")))
                self.assertEqual(profile.__name__.replace("_", "-"), profile.metadata.eep)
                self.assertTrue(profile.metadata.as_dict()["fields"])


if __name__ == "__main__":
    unittest.main()
