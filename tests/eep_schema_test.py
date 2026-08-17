"""Parity checks for the opt-in declarative D2 EEP migration seam.

These tests intentionally compare against the established public EEP classes.
They prevent the schema work from silently changing existing decoded values,
while keeping the old APIs fully operational during the gradual migration.
"""

import unittest

import eltakobus
from eltakobus.eep import D2_00_01, D2_06_01, D2_14_40, D2_14_41
from eltakobus.eep_schema import (
    D2_00_01_SCHEMA,
    D2_00_01_VARIANT_A,
    D2_00_01_VARIANT_B,
    D2_00_01_VARIANT_C,
    D2_00_01_VARIANT_D,
    D2_00_01_VARIANT_E,
    D2_06_01_SCHEMA,
    D2_14_40_SCHEMA,
    D2_14_41_SCHEMA,
    d2_compatibility_adapter,
)
from eltakobus.error import NotImplementedError as EEPNotImplementedError
from eltakobus.error import WrongOrgError
from eltakobus.message import VLDMessage
from eltakobus.vld import VLDValueStatus


def vld_payload(fields, size):
    """Build an MSB-first VLD payload using EEP document bit offsets."""

    data = bytearray(size)
    for offset, width, value in fields:
        for bit in range(width):
            absolute = offset + width - bit - 1
            if value & (1 << bit):
                data[absolute // 8] |= 1 << (7 - absolute % 8)
    return bytes(data)


class TestD2SchemaParity(unittest.TestCase):
    """Verify declarative values are compatible with existing D2 APIs."""

    def test_d20601_schema_matches_legacy_values_and_allows_extensions(self):
        payload = vld_payload(((0, 8, 0), (8, 4, 1), (16, 4, 3),
                               (40, 8, 125), (48, 8, 100), (56, 16, 1234),
                               (72, 5, 20)), 10) + b"\xaa"
        message = VLDMessage(bytes(4), 0, payload)

        adapter = d2_compatibility_adapter("D2-06-01")
        legacy, declarative = adapter.decode(message)

        self.assertIsInstance(legacy, D2_06_01)
        self.assertEqual((), adapter.compatibility_errors(message))
        self.assertAlmostEqual(20.0, declarative.value("temperature"))
        self.assertEqual(100.0, declarative.value("battery_state"))

    def test_d20601_special_values_match_legacy_none_semantics(self):
        payload = vld_payload(((0, 8, 0), (40, 8, 251), (48, 8, 201),
                               (56, 16, 60001), (72, 5, 21)), 10)
        message = VLDMessage(bytes(4), 0, payload)
        adapter = d2_compatibility_adapter("D2-06-01")
        _, declarative = adapter.decode(message)

        self.assertEqual((), adapter.compatibility_errors(message))
        self.assertIsNone(declarative["temperature"].value)
        self.assertEqual(VLDValueStatus.RESERVED,
                         declarative["temperature"].status)
        self.assertEqual(VLDValueStatus.UNMAPPED,
                         declarative["illumination"].status)

    def test_d20601_schema_rejects_unsupported_message_types_like_legacy(self):
        message = VLDMessage(bytes(4), 0, bytes((0x10,)) + bytes(9))

        with self.assertRaises(EEPNotImplementedError):
            D2_06_01_SCHEMA.decode_message(message)
        with self.assertRaises(EEPNotImplementedError):
            D2_06_01.decode_message(message)

    def test_d214_schemas_match_legacy_profiles_including_contact(self):
        payload = vld_payload(((0, 10, 500), (10, 8, 100), (18, 17, 60000),
                               (35, 2, 1), (37, 10, 0), (47, 10, 500),
                               (57, 10, 1000), (67, 1, 1)), 9)
        message = VLDMessage(bytes(4), 0, payload)

        first = d2_compatibility_adapter("D2-14-40")
        second = d2_compatibility_adapter("D2-14-41")
        legacy_first, fields_first = first.decode(message)
        legacy_second, fields_second = second.decode(message)

        self.assertIsInstance(legacy_first, D2_14_40)
        self.assertIsInstance(legacy_second, D2_14_41)
        self.assertEqual((), first.compatibility_errors(message))
        self.assertEqual((), second.compatibility_errors(message))
        self.assertAlmostEqual(-2.5, fields_first.value("acceleration_x"))
        self.assertTrue(fields_second.value("contact"))

    def test_schema_registry_includes_selected_d20001_variants(self):
        """D2-00-01 selects five explicit direction-specific codecs."""

        self.assertEqual(10, D2_06_01_SCHEMA.layout.payload_size)
        self.assertEqual(9, D2_14_40_SCHEMA.layout.payload_size)
        self.assertEqual(9, D2_14_41_SCHEMA.layout.payload_size)
        self.assertEqual({1, 2, 3, 4, 5}, set(D2_00_01_SCHEMA.variants))
        self.assertEqual((2, 5, 4, 3, 6), tuple(
            variant.payload_size for variant in (
                D2_00_01_VARIANT_A, D2_00_01_VARIANT_B,
                D2_00_01_VARIANT_C, D2_00_01_VARIANT_D,
                D2_00_01_VARIANT_E)))

        decoded = D2_00_01.decode_message(VLDMessage(bytes(4), 0, b"\x01\x81"))
        self.assertEqual((1, "A", True),
                         (decoded.message_id, decoded.message_type, decoded.config_valid))

    def test_d20001_all_variants_match_legacy_decoder(self):
        """Nominal A-E vectors retain every established public value."""

        messages = (
            VLDMessage(bytes(4), 0, b"\x01\x81"),
            VLDMessage(bytes(4), 0, b"\xba\x45\xd2\x04\x1b"),
            VLDMessage(bytes(4), 0, b"\x53\x25\x83\xff"),
            VLDMessage(bytes(4), 0, b"\x04\xd2\x04"),
            VLDMessage(bytes(4), 0, b"\x0d\x19\x05\xc0\x70\x52"),
        )
        adapter = d2_compatibility_adapter("D2-00-01")
        for expected_type, message in zip("ABCDE", messages):
            with self.subTest(variant=expected_type):
                legacy, declarative = adapter.decode(message)
                self.assertIsInstance(legacy, D2_00_01)
                self.assertEqual(expected_type, declarative.value("message_type"))
                self.assertEqual((), adapter.compatibility_errors(message))

        display = D2_00_01_SCHEMA.decode_message(messages[1])
        self.assertEqual(1234, display.value("figure_value_raw"))
        self.assertEqual(12.34, display.value("figure_value"))
        repeated = D2_00_01_SCHEMA.decode_message(messages[2])
        self.assertEqual(-125, repeated.value("setpoint_raw"))
        self.assertEqual(-1.25, repeated.value("setpoint"))

    def test_d20001_schema_and_legacy_decoder_ignore_vendor_extensions_alike(self):
        """All variants retain the legacy acceptance of trailing VLD bytes."""

        payloads = (
            b"\x01\x81", b"\xba\x45\xd2\x04\x1b", b"\x53\x25\x83\xff",
            b"\x04\xd2\x04", b"\x0d\x19\x05\xc0\x70\x52",
        )
        adapter = d2_compatibility_adapter("D2-00-01")
        for expected_type, payload in zip("ABCDE", payloads):
            with self.subTest(variant=expected_type):
                message = VLDMessage(bytes(4), 0, payload + b"\xaa\xbb")
                legacy, declarative = adapter.decode(message)
                self.assertIsInstance(legacy, D2_00_01)
                self.assertEqual(expected_type, declarative.value("message_type"))
                self.assertEqual((), adapter.compatibility_errors(message))

    def test_d20001_codec_round_trips_documented_wire_fields(self):
        """Encoding is variant-specific and preserves little-endian fields."""

        vectors = {
            "A": ({"config_valid": True, "user_action": 1}, b"\x01\x81"),
            "B": ({"fan_manual": True, "fan_speed": 3, "more_data": True,
                   "presence": 2, "figure_type": 5, "figure_value_raw": 1234,
                   "user_notification": True, "window_open": True,
                   "no_dew_point_warning": False, "cooling": True,
                   "heating": True}, b"\xba\x45\xd2\x04\x1b"),
            "C": ({"fan_speed": 5, "presence": 1, "setpoint_type": 5,
                   "setpoint_raw": -125}, b"\x53\x25\x83\xff"),
            "D": ({"channel_type": 0, "measurement_raw": 1234},
                  b"\x04\xd2\x04"),
            "E": ({"more_data": True, "setpoint_range_raw": 25,
                   "setpoint_steps": 5, "measurement_interval_raw": 12,
                   "presence_levels": 3, "fan_levels": 4,
                   "significant_temperature_difference_raw": 5,
                   "keep_alive_measurements_raw": 2},
                  b"\x0d\x19\x05\xc0\x70\x52"),
        }
        for variant, (values, expected) in vectors.items():
            with self.subTest(variant=variant):
                encoded = D2_00_01_SCHEMA.encode_variant(variant, values)
                self.assertEqual(expected, encoded)
                self.assertEqual(variant,
                                 D2_00_01_SCHEMA.decode_payload(encoded).value("message_type"))

    def test_d20001_schema_matches_legacy_error_boundaries(self):
        """Undefined IDs, short frames and documented reserved bits fail alike."""

        adapter = d2_compatibility_adapter("D2-00-01")
        for payload in (b"\x00", b"\x02", b"\x81\x00", b"\x83\x00\x00\x00",
                        b"\x05\x80\x00\x00\x00\x00"):
            message = VLDMessage(bytes(4), 0, payload)
            with self.subTest(payload=payload.hex()):
                with self.assertRaises((EEPNotImplementedError, ValueError)):
                    D2_00_01.decode_message(message)
                with self.assertRaises((EEPNotImplementedError, ValueError)):
                    adapter.schema.decode_message(message)

    def test_d20001_conditional_physical_values_match_legacy_none(self):
        """Conditional scaling remains absent outside documented states."""

        payloads = (
            b"\x03\x00\x01\x00",       # C: setpoint type is not 5
            b"\x04\xa1\x1f",           # D: non-temperature channel
            b"\x05\x00\x00\x00\x00\x00",  # E: disabled range/interval
        )
        adapter = d2_compatibility_adapter("D2-00-01")
        expected_absent = ("setpoint", "measurement", "setpoint_range")
        for payload, field_name in zip(payloads, expected_absent):
            message = VLDMessage(bytes(4), 0, payload)
            with self.subTest(field=field_name):
                legacy, declarative = adapter.decode(message)
                self.assertIsNone(getattr(legacy, field_name))
                self.assertIsNone(declarative[field_name].value)
                self.assertEqual(VLDValueStatus.UNMAPPED,
                                 declarative[field_name].status)
                self.assertEqual((), adapter.compatibility_errors(message))

    def test_d20001_encoder_is_strict_about_fields_and_signed_range(self):
        """Derived names, missing fields and overflowing signed values fail."""

        with self.assertRaisesRegex(ValueError, "derived"):
            D2_00_01_SCHEMA.encode_variant(
                "D", {"measurement": 12.34}, require_all=False)
        with self.assertRaisesRegex(ValueError, "missing"):
            D2_00_01_SCHEMA.encode_variant("A", {"config_valid": True})
        with self.assertRaisesRegex(ValueError, "signed bits"):
            D2_00_01_SCHEMA.encode_variant(
                "C", {"setpoint_raw": 32768}, require_all=False)

    def test_d20001_preserves_extensions_and_legacy_ignored_bits(self):
        """The codec does not assign meaning to B's undocumented high status bits."""

        base = b"\x02\x00\x00\x00\xe0\xaa"
        encoded = D2_00_01_SCHEMA.encode_variant(
            "B", {"figure_value_raw": 0x1234}, base_payload=base,
            require_all=False)
        self.assertEqual(b"\x02\x00\x34\x12\xe0\xaa", encoded)
        decoded = D2_00_01_SCHEMA.decode_payload(encoded)
        self.assertEqual(0x1234, decoded.value("figure_value_raw"))

    def test_schema_rejects_wrong_org_and_short_payload_like_legacy_decoder(self):
        adapter = d2_compatibility_adapter("D2-14-40")
        with self.assertRaises(ValueError):
            D2_14_40_SCHEMA.decode_payload(b"\x00" * 8)
        with self.assertRaises(WrongOrgError):
            adapter.schema.decode_message(object())
        with self.assertRaises(TypeError):
            D2_14_40_SCHEMA.decode_payload(9)

    def test_package_import_keeps_existing_eep_module_and_registry_usable(self):
        """Importing the additive schema module must not alter EEP discovery."""

        self.assertIs(eltakobus.eep.D2_06_01, D2_06_01)
        self.assertIs(D2_14_41, eltakobus.eep.EEP.find("D2-14-41"))
        decoded = D2_14_40.decode_message(VLDMessage(bytes(4), 0, bytes(9)))
        self.assertEqual(0, decoded.temperature_raw)


if __name__ == "__main__":
    unittest.main()
