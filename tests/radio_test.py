"""Focused tests for the dependency-free native RADIO_ERP1 model.

The tests use only standard-library doubles and the existing ESP2/VLD message
objects.  They verify wire-field preservation, validation, immutability and
explicit handling of conversions that would lose ESP3 metadata.
"""

import unittest
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

from eltakobus.eep import A5_38_08
from eltakobus.message import (
    RPSMessage,
    Regular1BSMessage,
    Regular4BSMessage,
    VLDMessage,
)
from eltakobus.radio import RadioTelegram, TelegramDirection


class TestRadioTelegramValidation(unittest.TestCase):
    """Reject malformed frames before they reach EEP or transport code."""

    def test_model_is_immutable_hashable_and_normalizes_bytes(self):
        telegram = RadioTelegram(
            0xA5, bytearray.fromhex("01020304"), [1, 2, 3, 4], 0,
            "outgoing",
        )

        self.assertEqual(bytes.fromhex("01020304"), telegram.payload)
        self.assertEqual(bytes.fromhex("01020304"), telegram.sender)
        self.assertIs(TelegramDirection.OUTGOING, telegram.direction)
        self.assertIsInstance(hash(telegram), int)
        with self.assertRaises(FrozenInstanceError):
            telegram.status = 1

    def test_validates_core_radio_fields(self):
        valid = dict(rorg=0xD2, payload=b"\x01", sender=bytes(4), status=0)
        invalid = (
            ({**valid, "rorg": 256}, ValueError),
            ({**valid, "payload": b""}, ValueError),
            ({**valid, "payload": bytes(15)}, ValueError),
            ({**valid, "sender": bytes(3)}, ValueError),
            ({**valid, "sender": 4}, TypeError),
            ({**valid, "status": -1}, ValueError),
            ({**valid, "direction": "sideways"}, ValueError),
            ({**valid, "rorg": 0xF6, "payload": bytes(4)}, ValueError),
            ({**valid, "rorg": 0xA5, "payload": bytes(1)}, ValueError),
        )

        for values, exception in invalid:
            with self.subTest(values=values):
                with self.assertRaises(exception):
                    RadioTelegram(**values)

    def test_optional_metadata_is_all_or_nothing(self):
        with self.assertRaisesRegex(ValueError, "supplied completely"):
            RadioTelegram(
                0xD2, b"\x01", bytes(4), 0,
                destination=bytes.fromhex("ffffffff"),
            )

    def test_validates_optional_metadata_ranges(self):
        base = dict(
            rorg=0xD2,
            payload=b"\x01",
            sender=bytes(4),
            status=0,
            destination=bytes.fromhex("ffffffff"),
            subtelegram_count=0,
            rssi_dbm=-70,
            security_level=0,
        )
        for name, value in (
            ("subtelegram_count", 256),
            ("rssi_dbm", 1),
            ("security_level", 5),
        ):
            with self.subTest(field=name):
                with self.assertRaises(ValueError):
                    RadioTelegram(**{**base, name: value})

    def test_raw_optional_data_derives_and_checks_metadata(self):
        optional = bytes.fromhex("02ffffffff4604")
        telegram = RadioTelegram(
            0xD2, b"\x01", bytes.fromhex("01020304"), 0,
            raw_optional_data=optional,
        )

        self.assertEqual(2, telegram.subtelegram_count)
        self.assertEqual(bytes.fromhex("ffffffff"), telegram.destination)
        self.assertEqual(-70, telegram.rssi_dbm)
        self.assertEqual(4, telegram.security_level)
        with self.assertRaisesRegex(ValueError, "conflicts"):
            RadioTelegram(
                0xD2, b"\x01", bytes(4), 0,
                rssi_dbm=-60,
                raw_optional_data=optional,
            )

        with self.assertRaisesRegex(ValueError, "exactly 7 bytes"):
            RadioTelegram(
                0xD2, b"\x01", bytes(4), 0,
                raw_optional_data=b"\x00",
            )


class TestLegacyMessageAdapters(unittest.TestCase):
    """Keep existing radio objects usable without changing their classes."""

    def test_supported_legacy_messages_round_trip_core_fields(self):
        messages = (
            RPSMessage(bytes.fromhex("01020304"), 0x30, b"\x10", True),
            Regular1BSMessage(bytes.fromhex("11223344"), 0, b"\x09"),
            Regular4BSMessage(
                bytes.fromhex("aabbccdd"), 0x80,
                bytes.fromhex("01020308"), True,
            ),
            VLDMessage(bytes.fromhex("deadbeef"), 1, bytes(range(14))),
        )

        for message in messages:
            with self.subTest(message=type(message).__name__):
                telegram = RadioTelegram.from_legacy_message(message)
                restored = telegram.to_legacy_message()
                self.assertEqual(bytes(message.data), restored.data)
                self.assertEqual(bytes(message.address), restored.address)
                self.assertEqual(message.status, restored.status)
                self.assertEqual(
                    bool(getattr(message, "outgoing", False)),
                    restored.outgoing,
                )

    def test_legacy_aliases_make_native_telegram_eep_compatible(self):
        telegram = RadioTelegram(
            0xA5,
            bytes.fromhex("01020309"),
            bytes.fromhex("01020304"),
            0x20,
            TelegramDirection.OUTGOING,
        )

        self.assertEqual(0x07, telegram.org)
        self.assertEqual(telegram.payload, telegram.data)
        self.assertEqual(telegram.sender, telegram.address)
        self.assertTrue(telegram.outgoing)

        decoded = A5_38_08.decode_message(telegram)
        self.assertEqual(1, decoded.command)
        self.assertEqual(1, decoded.switching.switching_command)

    def test_unsupported_legacy_shapes_and_unknown_rorg_are_explicit(self):
        with self.assertRaises(TypeError):
            RadioTelegram.from_legacy_message(object())
        with self.assertRaisesRegex(ValueError, "no existing"):
            RadioTelegram(0xC5, b"\x01", bytes(4), 0).to_legacy_message()

    def test_legacy_conversion_requires_explicit_metadata_loss(self):
        telegram = RadioTelegram(
            0xD2,
            b"\x01\x02",
            bytes.fromhex("01020304"),
            0,
            destination=bytes.fromhex("ffffffff"),
            subtelegram_count=1,
            rssi_dbm=-80,
            security_level=0,
        )

        with self.assertRaisesRegex(ValueError, "allow_metadata_loss"):
            telegram.to_legacy_message()
        restored = telegram.to_legacy_message(allow_metadata_loss=True)
        self.assertIsInstance(restored, VLDMessage)
        self.assertEqual(telegram.payload, restored.data)


class TestESP3FieldAdapters(unittest.TestCase):
    """Preserve native RADIO_ERP1 data without importing ``enocean``."""

    def test_minimum_and_maximum_payloads_round_trip_losslessly(self):
        optional = bytes.fromhex("01aabbccdd5503")
        for rorg, payload in ((0xC5, b"\x01"), (0xD2, bytes(range(14)))):
            with self.subTest(payload_length=len(payload)):
                data = bytes((rorg,)) + payload + bytes.fromhex("01020304") + b"\x80"
                telegram = RadioTelegram.from_esp3_fields(
                    data,
                    optional,
                    direction=TelegramDirection.OUTGOING,
                )
                self.assertEqual((data, optional), telegram.to_esp3_fields())
                self.assertEqual(rorg, telegram.rorg)
                self.assertEqual(payload, telegram.payload)
                self.assertTrue(telegram.outgoing)

    def test_packet_without_optional_section_remains_without_metadata(self):
        data = bytes.fromhex("d201020102030400")
        telegram = RadioTelegram.from_esp3_fields(data)

        self.assertEqual((data, b""), telegram.to_esp3_fields())
        self.assertIsNone(telegram.destination)
        self.assertIsNone(telegram.rssi_dbm)

    def test_every_defined_security_level_is_preserved(self):
        data = bytes.fromhex("d2010102030400")
        for security_level in range(5):
            optional = bytes.fromhex("00ffffffff32") + bytes((security_level,))
            with self.subTest(security_level=security_level):
                telegram = RadioTelegram.from_esp3_fields(data, optional)
                self.assertEqual(security_level, telegram.security_level)
                self.assertEqual(optional, telegram.raw_optional_data)

    def test_packet_adapter_validates_type_and_rorg(self):
        data = bytes.fromhex("f6100102030400")
        optional = bytes.fromhex("00ffffffff5000")
        packet = SimpleNamespace(
            packet_type=1,
            rorg=0xF6,
            data=data,
            optional=optional,
        )
        telegram = RadioTelegram.from_esp3_packet(packet)
        self.assertEqual((data, optional), telegram.to_esp3_fields())

        packet.packet_type = 2
        with self.assertRaisesRegex(ValueError, "not ESP3 RADIO_ERP1"):
            RadioTelegram.from_esp3_packet(packet)
        packet.packet_type = 1
        packet.rorg = 0xA5
        with self.assertRaisesRegex(ValueError, "does not match"):
            RadioTelegram.from_esp3_packet(packet)

    def test_direction_is_explicit_not_inferred_from_subtelegram_count(self):
        data = bytes.fromhex("f6100102030400")
        optional = bytes.fromhex("03ffffffff5000")
        incoming = RadioTelegram.from_esp3_fields(data, optional)
        outgoing = RadioTelegram.from_esp3_fields(
            data, optional, direction="outgoing",
        )

        self.assertFalse(incoming.outgoing)
        self.assertTrue(outgoing.outgoing)
        self.assertEqual(3, incoming.subtelegram_count)

    def test_subtelegram_count_preserves_the_complete_wire_byte(self):
        """Incoming ESP3 captures may report any value representable by a byte."""

        data = bytes.fromhex("f6100102030400")
        optional = bytes.fromhex("ffffffffffff00")
        telegram = RadioTelegram.from_esp3_fields(data, optional)

        self.assertEqual(0xFF, telegram.subtelegram_count)
        self.assertEqual((data, optional), telegram.to_esp3_fields())

    def test_packet_factory_receives_exact_wire_sections(self):
        data = bytes.fromhex("d201020102030400")
        optional = bytes.fromhex("00ffffffff4600")
        telegram = RadioTelegram.from_esp3_fields(data, optional)
        packet = telegram.to_esp3_packet(
            lambda packet_data, packet_optional: (packet_data, packet_optional)
        )
        self.assertEqual((data, optional), packet)

    def test_outbound_packet_requires_complete_optional_data_by_default(self):
        """Incomplete captures stay inspectable but need explicit send opt-in."""

        data = bytes.fromhex("d201020102030400")
        telegram = RadioTelegram.from_esp3_fields(data)

        self.assertEqual((data, b""), telegram.to_esp3_fields())
        with self.assertRaisesRegex(ValueError, "require seven bytes"):
            telegram.to_esp3_packet(lambda packet_data, packet_optional: None)
        packet = telegram.to_esp3_packet(
            lambda packet_data, packet_optional: (packet_data, packet_optional),
            allow_incomplete_optional_data=True,
        )
        self.assertEqual((data, b""), packet)


if __name__ == "__main__":
    unittest.main()
