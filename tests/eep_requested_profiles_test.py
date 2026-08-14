"""Regression tests for the Eltako profiles added in version 1.0.1.

The tests use raw 4BS and VLD payloads.  They are intentionally independent
of Home Assistant and hardware, and document the byte/bit layout used by the
EEP decoders.
"""

import unittest
from types import SimpleNamespace

from eltakobus.eep import (
    A5_13_02, A5_13_04, A5_14_01, A5_14_03, A5_14_05,
    A5_14_07, A5_14_08, D2_00_01, D2_14_40, D2_14_41, EEP,
)
from eltakobus.message import Regular4BSMessage, VLDMessage
from eltakobus.esp3 import ESP3MessageAdapter


def four_bs(data):
    return Regular4BSMessage(bytes.fromhex("01020304"), 0, bytes(data))


def vld_payload(fields, size=10):
    data = bytearray(size)
    for offset, width, value in fields:
        for bit in range(width):
            absolute = offset + width - bit - 1
            if value & (1 << bit):
                data[absolute // 8] |= 1 << (7 - absolute % 8)
    return bytes(data)


class TestRequestedA5Profiles(unittest.TestCase):
    """Verify Eltako's special A5 layouts and LRN/identifier bits."""

    def test_sun_position_profile_uses_directional_klx_values(self):
        """A5-13-02 stores west/south/east values in DB3/DB2/DB1."""
        decoded = A5_13_02.decode_message(four_bs((255, 128, 0, 0x2C)))
        self.assertAlmostEqual(150.0, decoded.sun_west)
        self.assertAlmostEqual(128 / 255 * 150.0, decoded.sun_south)
        self.assertEqual(0.0, decoded.sun_east)
        self.assertEqual(1, decoded.hemisphere)
        encoded = A5_13_02(sun_west=150, sun_south=75, sun_east=0,
                           hemisphere=1, learn_button=1, identifier=2).encode_message(bytes(4))
        self.assertEqual((255, 127, 0, 0x2C), tuple(encoded.data))

    def test_clock_profile_round_trip(self):
        """A5-13-04 keeps weekday/hour/minute/second in the documented fields."""
        profile = A5_13_04(weekday=7, hour=23, minute=59, second=58,
                           learn_button=1, time_format=1, am_pm=1)
        decoded = A5_13_04.decode_message(profile.encode_message(bytes(4)))
        self.assertEqual((7, 23, 59, 58, 1, 1, 1),
                         (decoded.weekday, decoded.hour, decoded.minute,
                          decoded.second, decoded.time_format, decoded.am_pm,
                          decoded.learn_button))

    def test_contact_variants_decode_distinct_db0_bits(self):
        """A5-14 variants expose their contact/vibration bits separately."""
        raw = four_bs((125, 0, 0, 0x0F))
        self.assertEqual(1, A5_14_01.decode_message(raw).contact)
        contact = A5_14_03.decode_message(raw)
        self.assertEqual((1, 1), (contact.contact, contact.vibration))
        self.assertEqual(1, A5_14_05.decode_message(raw).vibration)
        door = A5_14_07.decode_message(raw)
        self.assertEqual((1, 1), (door.door_contact, door.lock_contact))
        door_vibration = A5_14_08.decode_message(raw)
        self.assertEqual((1, 1, 1), (door_vibration.door_contact,
                                     door_vibration.lock_contact,
                                     door_vibration.vibration))

    def test_supply_voltage_error_codes_are_preserved(self):
        """Raw supply values 251..255 are error codes, not voltages."""
        decoded = A5_14_01.decode_message(four_bs((255, 0, 0, 0x08)))
        self.assertEqual(255, decoded.error_code)
        self.assertEqual(5.0, decoded.supply_voltage)


class TestRequestedD2Profiles(unittest.TestCase):
    """Verify MSB-first VLD fields and special-value handling."""

    def test_d20001_decodes_environment_and_handle_fields(self):
        """D2-00-01 starts with message type and uses 4-bit status fields."""
        payload = vld_payload(((0, 8, 0), (8, 4, 1), (16, 4, 3),
                               (40, 8, 125), (48, 8, 100), (56, 16, 1234),
                               (72, 5, 20)))
        decoded = D2_00_01.decode_message(VLDMessage(bytes(4), 0, payload))
        self.assertEqual((1, 3), (decoded.burglary_alarm, decoded.handle_position))
        self.assertAlmostEqual(20.0, decoded.temperature)
        self.assertEqual(50.0, decoded.humidity)
        self.assertEqual(1234.0, decoded.illumination)
        self.assertEqual(100, decoded.battery_state)

    def test_d214_profiles_decode_acceleration_and_contact(self):
        """D2-14-40/41 share sensor fields; -41 adds the contact bit."""
        fields = ((0, 10, 500), (10, 8, 100), (18, 17, 60000),
                  (35, 2, 1), (37, 10, 0), (47, 10, 500), (57, 10, 1000),
                  (67, 1, 1))
        payload = vld_payload(fields, 9)
        first = D2_14_40.decode_message(VLDMessage(bytes(4), 0, payload))
        second = D2_14_41.decode_message(VLDMessage(bytes(4), 0, payload))
        self.assertAlmostEqual(10.0, first.temperature)
        self.assertEqual(50.0, first.humidity)
        self.assertAlmostEqual(-2.5, first.acceleration_x)
        self.assertAlmostEqual(0.0, first.acceleration_y)
        self.assertAlmostEqual(2.5, first.acceleration_z)
        self.assertTrue(second.contact)

    def test_d2_error_codes_are_exposed_as_none_with_raw_value(self):
        """Reserved/error encodings do not become plausible physical values."""
        payload = vld_payload(((0, 10, 1023), (10, 8, 255), (18, 17, 131071)), 9)
        decoded = D2_14_40.decode_message(VLDMessage(bytes(4), 0, payload))
        self.assertIsNone(decoded.temperature)
        self.assertIsNone(decoded.humidity)
        self.assertIsNone(decoded.illumination)
        self.assertEqual((1023, 255, 131071),
                         (decoded.temperature_raw, decoded.humidity_raw,
                          decoded.illumination_raw))

    def test_profiles_are_registered(self):
        """All requested identifiers remain available through the legacy API."""
        for eep in ('A5-13-02', 'A5-13-04', 'A5-14-01', 'A5-14-03',
                    'A5-14-05', 'A5-14-07', 'A5-14-08', 'D2-00-01',
                    'D2-14-40', 'D2-14-41'):
            with self.subTest(eep=eep):
                self.assertEqual(eep, EEP.find(eep).get_metadata().eep)

    def test_esp3_adapter_keeps_vld_payload_for_eep_decoders(self):
        """ESP3 RORG D2 packets are exposed without lossy ESP2 truncation."""
        payload = bytes(range(9))
        packet = SimpleNamespace(rorg=0xD2, data=bytes((0xD2,)) + payload + bytes.fromhex("01020304") + bytes((0,)), optional=[0])
        message = ESP3MessageAdapter().convert_esp3_to_esp2(packet)
        self.assertIsInstance(message, VLDMessage)
        self.assertEqual(payload, message.data)
        self.assertEqual(bytes.fromhex("01020304"), message.address)


if __name__ == '__main__':
    unittest.main()
