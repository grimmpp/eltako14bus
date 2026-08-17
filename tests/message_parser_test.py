"""Tests for deterministic ESP2 message classification and compatibility."""

import unittest

from eltakobus.message import (
    EltakoBusLock,
    EltakoBusUnlock,
    EltakoDiscoveryReply,
    EltakoDiscoveryRequest,
    EltakoMemoryRequest,
    EltakoMemoryResponse,
    EltakoMessage,
    EltakoPoll,
    EltakoPollForced,
    EltakoTimeout,
    EltakoWrapped1BS,
    EltakoWrapped4BS,
    EltakoWrappedRPS,
    RPSMessage,
    Regular1BSMessage,
    Regular4BSMessage,
    TeachIn4BSMessage2,
    ESP2Message,
    classify_message,
    prettify,
)


ADDRESS = bytes.fromhex("01020304")


class MessageParserTest(unittest.TestCase):
    """Classification chooses one decoder without exception probing."""

    def test_wire_markers_select_all_supported_message_families(self):
        messages = (
            (EltakoBusLock(), EltakoBusLock),
            (EltakoBusUnlock(), EltakoBusUnlock),
            (EltakoPoll(2), EltakoPoll),
            (EltakoPollForced(2), EltakoPollForced),
            (EltakoDiscoveryRequest(2), EltakoDiscoveryRequest),
            (EltakoDiscoveryReply(2, 1, 127, b"\x04\x04\x42\x00", False), EltakoDiscoveryReply),
            (EltakoMemoryRequest(2, 7), EltakoMemoryRequest),
            (EltakoMemoryResponse(7, bytes(range(8))), EltakoMemoryResponse),
            (EltakoTimeout(), EltakoTimeout),
            (EltakoWrappedRPS(ADDRESS, 0x30, b"\x10"), EltakoWrappedRPS),
            (EltakoWrapped1BS(ADDRESS, 0x30, b"\x09"), EltakoWrapped1BS),
            (EltakoWrapped4BS(ADDRESS, 0x30, bytes(range(4))), EltakoWrapped4BS),
            (RPSMessage(ADDRESS, 0x30, b"\x10"), RPSMessage),
            (Regular1BSMessage(ADDRESS, 0, b"\x09"), Regular1BSMessage),
            (Regular4BSMessage(ADDRESS, 0, b"\x01\x02\x03\x08"), Regular4BSMessage),
            (TeachIn4BSMessage2(ADDRESS, 0, b"\x00\x00\x00\x80"), TeachIn4BSMessage2),
            (EltakoMessage(0x42, 2), EltakoMessage),
        )
        for message, expected in messages:
            with self.subTest(message=type(message).__name__):
                self.assertIs(expected, classify_message(message.serialize()))
                self.assertIsInstance(prettify(message), expected)

    def test_invalid_or_unsupported_frames_return_none_or_base_message(self):
        self.assertIsNone(classify_message(b""))
        self.assertIsNone(classify_message(b"\xa5\x5a" + bytes(11)))
        unknown = ESP2Message(bytes((0x22, 0x99)) + bytes(9))
        self.assertIs(ESP2Message, classify_message(unknown.serialize()))
        self.assertIsInstance(prettify(unknown), ESP2Message)

    def test_semantic_errors_are_not_used_for_type_selection(self):
        malformed = bytearray(RPSMessage(ADDRESS, 0x30, b"\x10").serialize())
        malformed[5] = 0xFF
        malformed[-1] = sum(malformed[2:13]) % 256
        self.assertIs(RPSMessage, classify_message(bytes(malformed)))
        # The selected parser rejects the invalid reserved bytes, while
        # prettify remains lossless and does not probe all other decoders.
        self.assertIsInstance(prettify(ESP2Message(bytes(malformed[2:13]))), ESP2Message)


if __name__ == "__main__":
    unittest.main()
