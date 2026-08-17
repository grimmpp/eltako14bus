"""Focused tests for the standalone declarative VLD field engine."""

import unittest
from dataclasses import FrozenInstanceError

from eltakobus.vld import (
    VLDField,
    VLDFieldType,
    VLDLayout,
    VLDValueStatus,
)


class TestVLDBitLayout(unittest.TestCase):
    """Verify the EEP document's MSB-first offset convention."""

    def test_cross_byte_field_uses_msb_first_offsets(self):
        field = VLDField.raw("cross", offset=4, width=8)
        payload = bytes.fromhex("0abc")

        self.assertEqual(0xAB, field.extract_raw(payload))
        self.assertEqual(bytes.fromhex("012c"), field.encode_into(payload, 0x12))

    def test_short_payload_and_overlapping_layout_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "too short"):
            VLDField.raw("late", 9, 8).decode(b"\x00\x00")
        with self.assertRaisesRegex(ValueError, "overlap"):
            VLDLayout((VLDField.raw("a", 0, 4), VLDField.raw("b", 3, 2)))

    def test_layout_infers_size_and_rejects_wrong_payload_length(self):
        layout = VLDLayout((VLDField.raw("tail", 12, 4),))
        self.assertEqual(2, layout.payload_size)
        with self.assertRaisesRegex(ValueError, "exactly 2"):
            layout.decode(b"\x00")


class TestVLDConversions(unittest.TestCase):
    """Verify each declarative conversion and strict inverse encoding."""

    def test_linear_scaling_round_trip_and_unit(self):
        temperature = VLDField.linear(
            "temperature", 0, 10,
            raw_range=(0, 1000), value_range=(-40.0, 60.0), unit="°C",
            reserved_values=frozenset(range(1001, 1024)),
        )

        decoded = temperature.decode(bytes.fromhex("8000"))  # raw 512
        self.assertAlmostEqual(11.2, decoded.value)
        self.assertEqual("°C", decoded.unit)
        payload = temperature.encode_into(bytes(2), 10.0)
        self.assertEqual(500, temperature.extract_raw(payload))

    def test_descending_linear_scale_is_supported(self):
        field = VLDField.linear(
            "setpoint", 0, 8,
            raw_range=(0, 255), value_range=(100.0, 0.0), unit="%",
        )
        self.assertEqual(100.0, field.decode(b"\x00").value)
        self.assertEqual(0.0, field.decode(b"\xff").value)

    def test_linear_encode_rejects_range_and_quantization_loss(self):
        field = VLDField.linear(
            "level", 0, 2, raw_range=(0, 3), value_range=(0.0, 1.0),
        )
        with self.assertRaisesRegex(ValueError, "between"):
            field.encode_raw(2.0)
        with self.assertRaisesRegex(ValueError, "not exactly representable"):
            field.encode_raw(0.5)
        with self.assertRaises(TypeError):
            field.encode_raw(True)

    def test_enum_maps_in_both_directions_and_preserves_unknown_raw(self):
        mode = VLDField.enum("mode", 0, 2, {0: "off", 1: "heat", 2: "cool"})

        self.assertEqual("cool", mode.decode(b"\x80").value)
        self.assertEqual(1, mode.encode_raw("heat"))
        unknown = mode.decode(b"\xc0")
        self.assertEqual(VLDValueStatus.UNMAPPED, unknown.status)
        self.assertEqual(3, unknown.raw)
        self.assertIsNone(unknown.value)
        with self.assertRaisesRegex(ValueError, "no enum mapping"):
            mode.encode_raw("automatic")

    def test_boolean_supports_nonstandard_wire_values(self):
        enabled = VLDField.boolean(
            "enabled", 0, 2, false_raw=1, true_raw=2, raw_min=1, raw_max=3,
        )

        self.assertFalse(enabled.decode(b"\x40").value)
        self.assertTrue(enabled.decode(b"\x80").value)
        self.assertEqual(2, enabled.encode_raw(True))
        self.assertEqual(VLDValueStatus.UNMAPPED, enabled.decode(b"\xc0").status)
        with self.assertRaises(TypeError):
            enabled.encode_raw(1)


class TestVLDSpecialValues(unittest.TestCase):
    """Ensure reserved and protocol error values never become measurements."""

    def setUp(self):
        self.field = VLDField.linear(
            "humidity", 0, 8,
            raw_range=(0, 200), value_range=(0.0, 100.0), unit="%",
            reserved_values=frozenset({201, 202}),
            error_values={254: "sensor failure", 255: "not available"},
        )

    def test_reserved_and_error_values_keep_raw_value_and_reason(self):
        reserved = self.field.decode(bytes((201,)))
        error = self.field.decode(bytes((254,)))

        self.assertEqual((201, None, VLDValueStatus.RESERVED),
                         (reserved.raw, reserved.value, reserved.status))
        self.assertEqual((254, None, VLDValueStatus.ERROR, "sensor failure"),
                         (error.raw, error.value, error.status, error.reason))

    def test_unclassified_out_of_range_value_is_unmapped(self):
        decoded = self.field.decode(bytes((220,)))
        self.assertEqual(VLDValueStatus.UNMAPPED, decoded.status)
        self.assertIn("operational range", decoded.reason)

    def test_invalid_special_definitions_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "both reserved and an error"):
            VLDField.raw("bad", 0, 2, reserved_values={3}, error_values={3: "bad"})
        with self.assertRaisesRegex(ValueError, "cannot also be reserved"):
            VLDField.enum("bad", 0, 2, {0: "off"}, reserved_values={0})


class TestVLDLayout(unittest.TestCase):
    """Exercise immutable message-level decode and strict encode behavior."""

    def setUp(self):
        self.layout = VLDLayout((
            VLDField.enum("mode", 0, 2, {0: "off", 1: "heat", 2: "cool"}),
            VLDField.boolean("contact", 2),
            VLDField.linear(
                "level", 8, 8, raw_range=(0, 100), value_range=(0.0, 100.0),
                unit="%", error_values={255: "not available"},
            ),
        ), payload_size=2, name="example")

    def test_layout_round_trip_and_value_accessor(self):
        payload = self.layout.encode({"mode": "heat", "contact": True, "level": 75})
        self.assertEqual(bytes.fromhex("604b"), payload)
        decoded = self.layout.decode(payload)

        self.assertEqual("heat", decoded.value("mode"))
        self.assertTrue(decoded.value("contact"))
        self.assertEqual(75.0, decoded.value("level"))
        self.assertEqual(75, decoded["level"].raw)

    def test_layout_rejects_missing_and_unknown_fields(self):
        with self.assertRaisesRegex(ValueError, "missing VLD fields"):
            self.layout.encode({"mode": "off"})
        with self.assertRaisesRegex(ValueError, "unknown VLD fields"):
            self.layout.encode({
                "mode": "off", "contact": False, "level": 0, "extra": 1,
            })

    def test_partial_encode_preserves_other_and_unused_bits(self):
        payload = self.layout.encode(
            {"contact": False}, base_payload=bytes.fromhex("ffff"),
            require_all=False,
        )
        self.assertEqual(bytes.fromhex("dfff"), payload)

    def test_value_accessor_rejects_error_value(self):
        decoded = self.layout.decode(bytes.fromhex("00ff"))
        with self.assertRaisesRegex(ValueError, "error.*raw 255"):
            decoded.value("level")

    def test_definitions_results_and_mappings_are_immutable(self):
        field = self.layout.fields[0]
        decoded = self.layout.decode(bytes(2))

        with self.assertRaises(FrozenInstanceError):
            field.width = 3
        with self.assertRaises(TypeError):
            field.enum_values[3] = "auto"
        with self.assertRaises(TypeError):
            decoded.fields["mode"] = decoded["mode"]
        self.assertIsInstance(hash(field), int)
        self.assertIsInstance(hash(decoded), int)
        self.assertIs(VLDFieldType.ENUM, field.field_type)

    def test_definition_copies_input_mappings_and_hash_ignores_order(self):
        values = {0: "off", 1: "on"}
        first = VLDField.enum("mode", 0, 2, values, error_values={3: "error"})
        second = VLDField.enum(
            "mode", 0, 2, {1: "on", 0: "off"}, error_values={3: "error"},
        )
        values[2] = "automatic"

        self.assertNotIn(2, first.enum_values)
        self.assertEqual(first, second)
        self.assertEqual(hash(first), hash(second))

    def test_integer_is_not_accepted_as_a_payload(self):
        with self.assertRaises(TypeError):
            self.layout.decode(2)


if __name__ == "__main__":
    unittest.main()
