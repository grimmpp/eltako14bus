"""Tests for dependency-free semantic ESP3 packet models."""

import unittest
from dataclasses import FrozenInstanceError

import eltakobus

from eltakobus.esp3_frame import ESP3Frame, ESP3PacketType
from eltakobus.esp3_packet import (
    ESP3Command,
    ESP3Event,
    ESP3EventCode,
    ESP3PacketError,
    ESP3Response,
    ESP3ReturnCode,
    UnknownESP3Packet,
    decode_esp3_packet,
)
from eltakobus.radio import RadioTelegram


class TestESP3SemanticPackets(unittest.TestCase):
    """Semantic decoding must retain all raw data and future numeric codes."""

    def test_response_round_trip_and_unknown_return_code(self):
        """Known and unknown return codes remain numeric and lossless."""

        frame = ESP3Frame(ESP3PacketType.RESPONSE, b"\x00\xaa\xbb", b"\x10")
        response = decode_esp3_packet(frame)

        self.assertIsInstance(response, ESP3Response)
        self.assertEqual(ESP3ReturnCode.OK, response.known_return_code)
        self.assertTrue(response.successful)
        self.assertEqual(b"\xaa\xbb", response.data)
        self.assertEqual(frame, response.raw_frame)
        self.assertEqual(frame, response.to_frame())

        unknown = decode_esp3_packet(ESP3Frame(2, b"\xfe"))
        self.assertEqual(0xFE, unknown.return_code)
        self.assertIsNone(unknown.known_return_code)

    def test_event_and_command_round_trip(self):
        """Event and common-command code bytes are separated from parameters."""

        event_frame = ESP3Frame(4, b"\x04\x01\x02", b"\x03")
        event = decode_esp3_packet(event_frame)
        self.assertIsInstance(event, ESP3Event)
        self.assertEqual(ESP3EventCode.READY, event.known_event_code)
        self.assertEqual(b"\x01\x02", event.data)
        self.assertEqual(event_frame, event.to_frame())

        command_frame = ESP3Frame(5, b"\x08\x99", b"\x42")
        command = decode_esp3_packet(command_frame)
        self.assertIsInstance(command, ESP3Command)
        self.assertEqual(8, command.command_code)
        self.assertEqual(b"\x99", command.data)
        self.assertEqual(command_frame, command.to_frame())

    def test_radio_and_unknown_packet_types_are_preserved(self):
        """RADIO_ERP1 uses RadioTelegram while unknown types remain raw frames."""

        radio_frame = ESP3Frame(
            1,
            bytes.fromhex("f6700102030430"),
            bytes.fromhex("03ffffffff5000"),
        )
        radio = decode_esp3_packet(radio_frame)
        self.assertIsInstance(radio, RadioTelegram)
        self.assertEqual(bytes.fromhex("01020304"), radio.sender)

        raw = ESP3Frame(0x7F, b"\x01\x02", b"\x03")
        unknown = decode_esp3_packet(raw)
        self.assertIsInstance(unknown, UnknownESP3Packet)
        self.assertEqual(raw, unknown.to_frame())

    def test_empty_typed_packets_are_rejected_without_hiding_unknown_types(self):
        """Known packet types require their semantic leading code byte."""

        for packet_type in (2, 4, 5):
            with self.subTest(packet_type=packet_type):
                with self.assertRaises(ESP3PacketError):
                    decode_esp3_packet(ESP3Frame(packet_type))
        self.assertIsInstance(
            decode_esp3_packet(ESP3Frame(0x7F)), UnknownESP3Packet
        )

    def test_models_are_immutable_and_validate_command_packet_type(self):
        """Public packets cannot mutate after they have entered a dispatcher."""

        command = ESP3Command(0x08, b"\x01")
        with self.assertRaises(FrozenInstanceError):
            command.command_code = 0x09
        with self.assertRaises(ValueError):
            ESP3Command(1, packet_type=ESP3PacketType.RESPONSE)

    def test_raw_frame_cannot_disagree_with_semantic_fields(self):
        """A retained raw frame must describe the same response or event."""

        with self.assertRaisesRegex(ValueError, "does not match"):
            ESP3Response(0, b"\x01", raw_frame=ESP3Frame(2, b"\x00\x02"))
        with self.assertRaisesRegex(ValueError, "does not match"):
            ESP3Event(4, b"\x01", raw_frame=ESP3Frame(4, b"\x04\x02"))
        with self.assertRaises(TypeError):
            UnknownESP3Packet(object())

    def test_integrated_package_exports_are_available(self):
        """Wildcard integration exposes the new native API without aliases."""

        self.assertIs(ESP3Command, eltakobus.ESP3Command)
        self.assertIs(ESP3Response, eltakobus.ESP3Response)
        self.assertIs(decode_esp3_packet, eltakobus.decode_esp3_packet)
        self.assertIs(ESP3PacketType, eltakobus.ESP3PacketType)


if __name__ == "__main__":
    unittest.main()
