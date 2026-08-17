"""Offline tests for robust ESP3 conversion.

The packet double models only the fields used by the adapter.  This keeps the
tests independent of the optional ``enocean`` package while covering the
wire-level conversion and the failure behavior observed in the upstream
issues.
"""

import logging
import unittest
from unittest.mock import Mock

from eltakobus.esp3 import ESP3MessageAdapter
from eltakobus.message import Regular4BSMessage


class PacketDouble:
    def __init__(self, data=None, optional=None, rorg=None, response=None,
                 response_data=None):
        self.data = data or []
        self.optional = optional or []
        self.rorg = rorg
        self.response = response
        self.response_data = response_data or []


class TestESP3MessageAdapter(unittest.TestCase):
    def setUp(self):
        self.adapter = ESP3MessageAdapter(logging.getLogger("test.esp3"))

    def test_radio_conversion_includes_security_level(self):
        packets = []

        def factory(data, optional):
            packet = PacketDouble(data, optional)
            packets.append(packet)
            return packet

        message = Regular4BSMessage(
            address=bytes.fromhex("ffe5c647"), status=0,
            data=bytes.fromhex("01000009"), outgoing=True,
        )
        packet = self.adapter.convert_esp2_to_esp3(message, factory)

        self.assertIs(packet, packets[0])
        self.assertEqual(len(packet.optional), 7)
        self.assertEqual(packet.optional[-1], 0)

    def test_default_conversion_is_native_and_does_not_need_enocean(self):
        """The historic packet attributes remain available without the old dependency."""
        message = Regular4BSMessage(
            address=bytes.fromhex("ffe5c647"), status=0,
            data=bytes.fromhex("01000009"), outgoing=False,
        )
        packet = self.adapter.convert_esp2_to_esp3(message)

        self.assertEqual(packet.packet_type, 1)
        self.assertEqual(packet.rorg, 0xA5)
        self.assertEqual(packet.data, [0xA5, 1, 0, 0, 9, 0xFF, 0xE5, 0xC6, 0x47, 0])
        self.assertEqual(packet.optional, [0, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0])

    def test_legacy_factory_is_explicit(self):
        """Legacy enocean packet construction remains an application opt-in."""
        packets = []

        def factory(data, optional):
            packet = PacketDouble(data, optional)
            packets.append(packet)
            return packet

        message = Regular4BSMessage(
            address=bytes.fromhex("ffe5c647"), status=0,
            data=bytes.fromhex("01000009"), outgoing=False,
        )
        packet = self.adapter.convert_esp2_to_esp3(message, factory)
        self.assertIs(packet, packets[0])
        self.assertEqual(packet.packet_type, 1)

    def test_malformed_radio_packet_is_logged_and_ignored(self):
        packet = PacketDouble(data=[0xF6], rorg=0xF6)
        with self.assertLogs("test.esp3", level="WARNING"):
            self.assertIsNone(self.adapter.convert_esp3_to_esp2(packet))

    def test_wrong_param_response_does_not_escape_conversion(self):
        packet = PacketDouble(response=3, response_data=[])
        with self.assertLogs("test.esp3", level="WARNING"):
            self.assertIsNone(self.adapter.convert_esp3_to_esp2(packet))

    def test_callback_is_not_called_for_bad_packet(self):
        callback = Mock()
        packet = PacketDouble(data=[0xA5], rorg=0xA5)
        self.assertIsNone(self.adapter.handle_packet(packet, callback))
        callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
