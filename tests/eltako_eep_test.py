"""Tests for Eltako-specific telegram variants documented in the catalogue.

These are intentionally separate from the generic EEP tests.  Eltako devices
reuse standard EEP numbers but sometimes add fixed markers or device-specific
status meanings; changing those bytes can make a telegram look valid while
silently changing its meaning.
"""

import unittest

from eltakobus.eep import (
    A5_02_05,
    A5_06_02,
    A5_09_05,
    A5_14_09,
    A5_14_0A,
    A5_20_04,
    A5_30_03,
    F6_05_01,
    F6_05_02,
    G5_3F_7F,
    H5_3F_7F,
    M5_38_08,
)
from eltakobus.message import RPSMessage, Regular4BSMessage


ADDRESS = bytes.fromhex("01020304")


def four_bs(data):
    """Build an incoming ESP2 4BS telegram with DB3 first."""
    return Regular4BSMessage(ADDRESS, 0, bytes(data))


def rps(data, status=0x30):
    """Build an incoming RPS telegram with the Eltako status byte."""
    return RPSMessage(ADDRESS, status, bytes((data,)))


class TestEltakoTemperatureAndLightMarkers(unittest.TestCase):
    """Verify fixed marker bytes from FTF65S and FHD65SB telegrams."""

    def test_ftf65s_a50205_uses_eltako_db0_marker(self):
        """FTF65S uses DB0=0x0F and the inverted 0..40 °C DB1 value."""
        decoded = A5_02_05.decode_message(four_bs((0, 0, 255, 0x0F)))
        self.assertEqual(0.0, decoded.current_temperature)
        self.assertEqual(0x0F, decoded.profile_marker)
        encoded = A5_02_05(40.0).encode_message(ADDRESS)
        self.assertEqual((0, 0, 0, 0x0F), tuple(encoded.data))

    def test_fhd65sb_a50602_uses_voltage_light_and_marker(self):
        """FHD65SB sends voltage in DB3, light in DB2, and marker 0x0F in DB0."""
        decoded = A5_06_02.decode_message(four_bs((255, 255, 0, 0x0F)))
        self.assertAlmostEqual(5.1, decoded.supply_voltage, places=2)
        self.assertAlmostEqual(1020.0, decoded.illumination, places=1)
        self.assertEqual(0x0F, decoded.profile_marker)
        encoded = A5_06_02(0.0, 0.0).encode_message(ADDRESS)
        self.assertEqual(0x0F, encoded.data[3])


class TestEltakoStatusMarkers(unittest.TestCase):
    """Verify Eltako status-dependent fields and alarm markers."""

    def test_flt58_a50905_has_fixed_profile_bytes(self):
        """FLT58 uses DB1=0x1B and DB0=0x0A around its 16-bit VOC value."""
        decoded = A5_09_05.decode_message(four_bs((0xFF, 0xFF, 0x1B, 0x0A)))
        self.assertAlmostEqual(500.0, decoded.concentration, places=2)
        self.assertEqual((0x1B, 0x0A), (decoded.profile_marker, decoded.profile_type))
        encoded = A5_09_05(0.0).encode_message(ADDRESS)
        self.assertEqual((0, 0, 0x1B, 0x0A), tuple(encoded.data))

    def test_fksh_a52004_selects_temperature_by_db0_status(self):
        """FKS-H distinguishes supply and target temperature with DB0."""
        supply = A5_20_04.decode_message(four_bs((255, 255, 0, 0x08)))
        target = A5_20_04.decode_message(four_bs((255, 255, 0, 0x0A)))
        battery = A5_20_04.decode_message(four_bs((0, 0x12, 0, 0x09)))
        self.assertAlmostEqual(80.0, supply.temperature, places=1)
        self.assertAlmostEqual(30.0, target.temperature, places=1)
        self.assertTrue(battery.battery_empty)
        self.assertEqual(0x09, battery.status)

    def test_fhmb_a53003_uses_eltako_alarm_markers(self):
        """FHMB/FRWB use 0x0F for alarm and 0x1F for no alarm in DB1."""
        alarm = A5_30_03.decode_message(four_bs((0x08, 0, 0x0F, 0x00)))
        clear = A5_30_03.decode_message(four_bs((0x08, 255, 0x1F, 0x00)))
        self.assertTrue(alarm.alarm)
        self.assertFalse(clear.alarm)
        self.assertEqual(0x0F, alarm.alarm_status)
        self.assertEqual(0x1F, clear.alarm_status)
        encoded = A5_30_03(20.0, 0x0F, 0x08).encode_message(ADDRESS)
        self.assertEqual((0x00, 0x7F, 0x0F, 0x08), tuple(encoded.data))

    def test_ffgb_and_mtronic_window_statuses_are_distinct(self):
        """Eltako window contacts use 0x08 closed, 0x0A tilt, 0x0E open."""
        for raw, expected in ((0x08, A5_14_09.CLOSED),
                              (0x0A, A5_14_09.TILTED),
                              (0x0E, A5_14_09.OPEN)):
            with self.subTest(raw=hex(raw)):
                decoded = A5_14_09.decode_message(four_bs((125, 0, 0, raw)))
                self.assertEqual(expected, decoded.window_state)
                self.assertFalse(decoded.alarm)

        tamper = A5_14_0A.decode_message(four_bs((125, 0, 0, 0x0B)))
        self.assertEqual(A5_14_0A.TILTED, tamper.window_state)
        self.assertTrue(tamper.alarm)


class TestEltakoRpsAndShutterVariants(unittest.TestCase):
    """Verify Eltako RPS markers and the combined shutter status profiles."""

    def test_fws81_and_frw_status_bytes_round_trip(self):
        """Water and smoke detectors use Eltako-specific RPS status values."""
        water = F6_05_01.decode_message(rps(0x30))
        dry = F6_05_01.decode_message(rps(0x20))
        smoke = F6_05_02.decode_message(rps(0x10))
        low_battery = F6_05_02.decode_message(rps(0x30))
        self.assertTrue(water.water_detected)
        self.assertFalse(dry.water_detected)
        self.assertTrue(smoke.smoke_alarm)
        self.assertTrue(low_battery.low_battery)
        self.assertEqual(0x30, F6_05_01(0x30).encode_message(ADDRESS).data[0])

    def test_gateway_switching_uses_rps_data_bit_and_status(self):
        """M5-38-08 uses DB0.BIT5 for the state and status 0x30."""
        on = M5_38_08.decode_message(rps(0x70))
        off = M5_38_08.decode_message(rps(0x50))
        self.assertTrue(on.state)
        self.assertFalse(off.state)
        encoded = M5_38_08(True).encode_message(ADDRESS)
        self.assertEqual((0x70, 0x30), (encoded.data[0], encoded.status))

    def test_shutter_status_and_command_keep_eltako_markers(self):
        """G5/H5 use different telegram directions and the H5 time flag."""
        status = G5_3F_7F.decode_message(four_bs((0x00, 0x0A, 0x01, 0x0A)))
        self.assertEqual(10, status.time)
        self.assertEqual(1, status.direction)
        self.assertEqual((0, 10, 1, 0x0A), tuple(status.encode_message(ADDRESS).data))

        command = H5_3F_7F(12.3, 2, 1, send_time_in_seconds=False)
        encoded = command.encode_message(ADDRESS)
        self.assertEqual((0x00, 123, 2, 0x0A), tuple(encoded.data))


if __name__ == "__main__":
    unittest.main()
