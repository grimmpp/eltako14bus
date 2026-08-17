"""Tests for dependency-free ESP3 framing and streaming recovery."""

import unittest
from dataclasses import FrozenInstanceError

from eltakobus.esp3_frame import (
    ESP3DataCRCError,
    ESP3Frame,
    ESP3FrameParser,
    ESP3FrameSizeError,
    ESP3HeaderCRCError,
    ESP3ParseError,
    ESP3_PACKET_RADIO_ERP1,
    crc8,
)


class TestESP3Frame(unittest.TestCase):
    """Encoding and strict one-frame decoding retain every section byte."""

    def test_crc8_matches_standard_check_value(self):
        self.assertEqual(0xF4, crc8(b"123456789"))

    def test_round_trip_is_immutable_and_preserves_sections(self):
        frame = ESP3Frame(
            0x01, bytearray.fromhex("a501020304050607"),
            [3, 255, 255, 255, 255, 90, 4],
        )
        restored = ESP3Frame.from_bytes(bytes(frame))

        self.assertEqual(frame, restored)
        self.assertEqual(bytes(frame), restored.to_bytes())
        with self.assertRaises(FrozenInstanceError):
            frame.packet_type = 2

    def test_strict_decoder_reports_clear_errors(self):
        frame = ESP3Frame(2, b"\x01", b"\x02")
        raw = bytearray(bytes(frame))
        raw[5] ^= 1
        with self.assertRaises(ESP3HeaderCRCError):
            ESP3Frame.from_bytes(raw)

        raw = bytearray(bytes(frame))
        raw[-1] ^= 1
        with self.assertRaises(ESP3DataCRCError):
            ESP3Frame.from_bytes(raw)
        with self.assertRaisesRegex(ESP3ParseError, "sync byte"):
            ESP3Frame.from_bytes(b"\x00" + bytes(frame)[1:])

        with self.assertRaises(TypeError):
            ESP3Frame.from_bytes(3)

    def test_radio_erp1_sections_keep_data_and_optional_data_verbatim(self):
        data = bytes.fromhex("d201020304aabbccdd80")
        optional = bytes.fromhex("03ffffffff5004dead")
        frame = ESP3Frame(ESP3_PACKET_RADIO_ERP1, data, optional)
        radio = frame.radio_erp1

        self.assertEqual(0xD2, radio.rorg)
        self.assertEqual(bytes.fromhex("01020304"), radio.payload)
        self.assertEqual(bytes.fromhex("aabbccdd"), radio.sender)
        self.assertEqual(0x80, radio.status)
        self.assertEqual(optional, radio.optional)
        with self.assertRaisesRegex(ValueError, "not an ESP3 RADIO_ERP1"):
            ESP3Frame(2, data).radio_erp1
        with self.assertRaises(ESP3ParseError):
            ESP3Frame(ESP3_PACKET_RADIO_ERP1, b"\xd2").radio_erp1


class TestESP3FrameParser(unittest.TestCase):
    """The parser must survive arbitrary serial/TCP chunk boundaries."""

    def test_byte_by_byte_input_emits_one_frame_only_when_complete(self):
        frame = ESP3Frame(2, b"\x01\x02", b"\x03")
        parser = ESP3FrameParser()
        received = []
        for value in bytes(frame):
            received.extend(parser.feed(bytes((value,))))

        self.assertEqual([frame], received)
        self.assertEqual(b"", parser.buffered_bytes)
        self.assertFalse(parser.errors)

    def test_noise_and_multiple_frames_are_resynchronized(self):
        first = ESP3Frame(2, b"\x01")
        second = ESP3Frame(4, b"\x02\x03", b"\x04")
        parser = ESP3FrameParser()

        self.assertEqual(
            [first, second],
            parser.feed(b"noise\x00" + bytes(first) + bytes(second)),
        )
        self.assertEqual(len(b"noise\x00"), parser.discarded_bytes)

    def test_bad_header_and_data_crc_do_not_hide_following_frames(self):
        valid = ESP3Frame(2, b"\x10")
        invalid_header = bytearray(bytes(ESP3Frame(3, b"\x20")))
        invalid_header[5] ^= 0xFF
        invalid_data = bytearray(bytes(ESP3Frame(4, b"\x30")))
        invalid_data[-1] ^= 0xFF
        parser = ESP3FrameParser()

        self.assertEqual(
            [valid], parser.feed(invalid_header + invalid_data + bytes(valid))
        )
        self.assertEqual(2, len(parser.errors))
        self.assertIsInstance(parser.errors[0], ESP3HeaderCRCError)
        self.assertIsInstance(parser.errors[1], ESP3DataCRCError)

    def test_partial_frame_is_retained_without_an_error(self):
        frame = ESP3Frame(2, b"\x01\x02")
        encoded = bytes(frame)
        parser = ESP3FrameParser()

        self.assertEqual([], parser.feed(encoded[:-1]))
        self.assertEqual(encoded[:-1], parser.buffered_bytes)
        self.assertFalse(parser.errors)
        self.assertEqual([frame], parser.feed(encoded[-1:]))

    def test_parser_rejects_declared_length_above_its_configured_bound(self):
        header = bytes.fromhex("5500100002")
        malformed = header + bytes((crc8(header[1:]),))
        valid = ESP3Frame(2, b"\x01")
        parser = ESP3FrameParser(max_data_length=8)

        self.assertEqual([valid], parser.feed(malformed + bytes(valid)))
        self.assertIsInstance(parser.errors[0], ESP3FrameSizeError)


if __name__ == "__main__":
    unittest.main()
