"""Regression tests for EEP fixes derived from open upstream pull requests."""

import unittest

from eltakobus.eep import (
    A5_02_01, A5_02_05, A5_02_20, A5_02_30, A5_06_02, A5_06_03,
    A5_07_02, A5_07_03, A5_09_05,
    A5_10_03, A5_14_09, A5_14_0A,
    A5_20_04, A5_30_03,
    F6_05_01, F6_05_02, H5_3F_7F,
)
from eltakobus.message import Regular4BSMessage, RPSMessage


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


class TestA50205TemperatureSensor(unittest.TestCase):
    """Verify the official 0..40 °C A5-02-05 profile."""

    def test_decode_boundaries_and_profile_marker(self):
        """DB1 uses inverted 0..40 °C scaling and DB0 carries 0x0F."""
        low = A5_02_05.decode_message(four_bs((0, 0, 255, 0x0F)))
        high = A5_02_05.decode_message(four_bs((0, 0, 0, 0x0F)))

        self.assertEqual(0.0, low.current_temperature)
        self.assertEqual(40.0, high.current_temperature)
        self.assertEqual(0x0F, low.profile_marker)

    def test_encode_boundaries_and_round_trip(self):
        """The encoder uses the same wire scaling as the decoder."""
        low = A5_02_05(0.0).encode_message(bytes.fromhex("01020304"))
        high = A5_02_05(40.0).encode_message(bytes.fromhex("01020304"))

        self.assertEqual(255, low.data[2])
        self.assertEqual(0x0F, low.data[3])
        self.assertEqual(0, high.data[2])
        self.assertAlmostEqual(20.0, A5_02_05.decode_message(
            A5_02_05(20.0, 0).encode_message(bytes(4))).current_temperature, delta=0.1)

    def test_out_of_range_temperature_is_rejected(self):
        """Invalid physical values must not silently wrap into another temperature."""
        with self.assertRaises(ValueError):
            A5_02_05(-0.1).encode_message(bytes(4))
        with self.assertRaises(ValueError):
            A5_02_05(40.1).encode_message(bytes(4))


class TestA50703OccupancySensor(unittest.TestCase):
    """Verify the 10-bit illumination and occupancy bit layout of A5-07-03."""

    def test_decode_values_and_supply_error(self):
        """DB3 is voltage, DB2.7..DB1.6 is illumination, and DB0.7 is motion."""
        message = four_bs((200, 0xFA, 0x00, 0x80))
        decoded = A5_07_03.decode_message(message)
        self.assertEqual(4.0, decoded.supply_voltage)
        self.assertEqual(1000, decoded.illumination)
        self.assertEqual(1, decoded.motion_detected)

        error = A5_07_03.decode_message(four_bs((251, 0, 0, 0)))
        self.assertEqual(251, error.error_code)
        self.assertEqual(5.0, error.supply_voltage)

    def test_encode_round_trip(self):
        """Encoding retains the profile's three measured values."""
        encoded = A5_07_03(2.5, 513, 1).encode_message(bytes(4))
        decoded = A5_07_03.decode_message(encoded)
        self.assertEqual(0x80, encoded.data[3])
        self.assertAlmostEqual(2.5, decoded.supply_voltage, places=2)
        self.assertEqual(513, decoded.illumination)
        self.assertEqual(1, decoded.motion_detected)


class TestAdditionalStandardProfiles(unittest.TestCase):
    """Exercise newly registered profiles from the EEP 2.6.7 tables."""

    def test_a50201_uses_its_declared_temperature_range(self):
        """A5-02-01 maps the same DB1 field to -40..0 °C."""
        decoded = A5_02_01.decode_message(four_bs((0, 0, 255, 0x00)))
        self.assertEqual(-40.0, decoded.current_temperature)
        self.assertEqual(0.0, A5_02_01.decode_message(
            four_bs((0, 0, 0, 0))).current_temperature)

    def test_a50603_uses_db2_as_the_two_most_significant_bits(self):
        """A5-06-03 stores the 10-bit lux value in DB2.7..DB1.6."""
        decoded = A5_06_03.decode_message(four_bs((250, 0xFA, 0x00, 0)))
        self.assertEqual(1000, decoded.illumination)
        self.assertAlmostEqual(5.0, decoded.supply_voltage, places=1)

    def test_a50702_uses_the_db0_motion_bit(self):
        """A5-07-02 has no illumination field and reports motion in DB0.7."""
        decoded = A5_07_02.decode_message(four_bs((200, 0, 0, 0x80)))
        self.assertTrue(decoded.motion_detected)
        self.assertAlmostEqual(4.0, decoded.supply_voltage, places=1)

    def test_a502_10bit_profiles_use_db2_and_db1(self):
        """The two 10-bit temperature profiles use DB2.1..DB1.0."""
        for profile, minimum, maximum in (
            (A5_02_20, -10.0, 41.2),
            (A5_02_30, -40.0, 62.3),
        ):
            low = profile.decode_message(four_bs((0, 0x03, 0xFF, 0)))
            high = profile.decode_message(four_bs((0, 0, 0, 0)))
            self.assertAlmostEqual(minimum, low.current_temperature, places=1)
            self.assertAlmostEqual(maximum, high.current_temperature, places=1)


class TestF60502SmokeDetector(unittest.TestCase):
    """Verify FRW smoke alarm, normal, and low-battery RPS states."""

    def test_decode_statuses(self):
        for raw, alarm, low_battery in ((0x00, False, False), (0x10, True, False), (0x30, False, True)):
            decoded = F6_05_02.decode_message(RPSMessage(bytes.fromhex("01020304"), 0x30, bytes((raw,))))
            self.assertEqual(alarm, decoded.smoke_alarm)
            self.assertEqual(low_battery, decoded.low_battery)

    def test_encode_preserves_raw_status(self):
        """The generic encoder can replay a captured status byte unchanged."""
        self.assertEqual(0x10, F6_05_02(0x10).encode_message(bytes(4)).data[0])


class TestEltakoCatalogProfiles(unittest.TestCase):
    """Verify the additional telegram definitions documented by Eltako."""

    def test_fhd65sb_a50602(self):
        """Eltako's FHD65SB variant uses voltage, light, and DB0 marker 0x0F."""
        decoded = A5_06_02.decode_message(four_bs((255, 128, 0, 0x0F)))
        self.assertAlmostEqual(5.1, decoded.supply_voltage, places=2)
        self.assertAlmostEqual(512.0, decoded.illumination, places=0)
        self.assertEqual(0x0F, decoded.profile_marker)

    def test_flt58_a50905(self):
        """The Eltako VOC telegram carries a 16-bit 0..500 value and fixed markers."""
        decoded = A5_09_05.decode_message(four_bs((0x80, 0x00, 0x1B, 0x0A)))
        self.assertAlmostEqual(250.0, decoded.concentration, places=1)
        self.assertEqual((0x1B, 0x0A), (decoded.profile_marker, decoded.profile_type))

    def test_fksh_a52004(self):
        """The valve profile decodes the 0x08 supply-temperature variant."""
        decoded = A5_20_04.decode_message(four_bs((128, 128, 0, 0x08)))
        self.assertAlmostEqual(50.2, decoded.valve_position, places=0)
        self.assertAlmostEqual(50.1, decoded.temperature, places=0)
        self.assertFalse(decoded.battery_empty)

    def test_fws81_water_status(self):
        """Eltako's FWS81 uses 0x30 for water and 0x20 for no water."""
        water = F6_05_01.decode_message(RPSMessage(bytes(4), 0x30, bytes((0x30,))))
        dry = F6_05_01.decode_message(RPSMessage(bytes(4), 0x30, bytes((0x20,))))
        self.assertTrue(water.water_detected)
        self.assertFalse(dry.water_detected)

    def test_fhmb_a53003_eltako_alarm_layout(self):
        """FHMB/FRWB use inverted temperature scaling and 0x0F/0x1F alarm markers."""
        alarm = A5_30_03.decode_message(four_bs((0x08, 0x00, 0x0F, 0x00)))
        clear = A5_30_03.decode_message(four_bs((0x08, 0xFF, 0x1F, 0x00)))
        self.assertTrue(alarm.alarm)
        self.assertFalse(clear.alarm)
        self.assertEqual(40.0, alarm.temperature)
        self.assertEqual(0.0, clear.temperature)

    def test_window_contact_status_and_alarm(self):
        """FFGB/mTronic use 0x08 closed, 0x0A tilted, 0x0E open and bit 0 for alarm."""
        decoded = A5_14_0A.decode_message(four_bs((125, 0, 0, 0x0B)))
        self.assertAlmostEqual(2.5, decoded.supply_voltage, places=2)
        self.assertEqual(0x0A, decoded.window_state)
        self.assertTrue(decoded.alarm)
        encoded = A5_14_09(2.5, A5_14_09.OPEN, 0).encode_message(bytes(4))
        self.assertEqual(0x0E, encoded.data[3])


if __name__ == "__main__":
    unittest.main()
