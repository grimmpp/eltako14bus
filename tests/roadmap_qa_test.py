"""Independent regression checks for the parser-focused roadmap work.

This suite deliberately tests public compatibility boundaries rather than
implementation details.  It supplements the focused parser and transport
tests: ESP2 callers must continue to receive the same 14-byte wire format and
the legacy asyncio interface must retain its historical generic
``ESP2Message`` delivery behaviour.
"""

import asyncio
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import eltakobus
from eltakobus.esp2_frame import ESP2FrameParser
from eltakobus.message import ESP2Message, EltakoDiscoveryReply
from eltakobus.serial import RS485SerialInterface


def discovery_reply():
    """Return a real, checksummed ESP2 frame used by legacy callers."""
    return EltakoDiscoveryReply(
        reported_address=1,
        reported_size=1,
        memory_size=127,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    ).serialize()


class _LegacyTransport:
    """Minimal asyncio transport used to exercise the legacy receive loop."""

    def __init__(self):
        self.writes = []

    def write(self, data):
        self.writes.append(bytes(data))


class RoadmapESP2CompatibilityTest(unittest.TestCase):
    """Independent QA checks for ESP2 parser integration and old APIs."""

    def test_package_exports_keep_legacy_message_api_and_add_parser(self):
        """The frame parser is additive; old package-level message imports work."""
        self.assertIs(ESP2Message, eltakobus.ESP2Message)
        self.assertIs(ESP2FrameParser, eltakobus.ESP2FrameParser)

        body = bytes(range(11))
        message = eltakobus.ESP2Message(body)
        self.assertEqual(body, message.body)
        self.assertEqual(message.serialize(), eltakobus.ESP2Message.parse(
            message.serialize()
        ).serialize())

    def test_wildcard_import_keeps_core_esp2_symbols_dependency_free(self):
        """A minimal core installation may use its historic wildcard import."""
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        script = (
            "namespace = {}; exec('from eltakobus import *', namespace); "
            "assert 'ESP2Message' in namespace; "
            "assert 'ESP2FrameParser' in namespace"
        )
        result = subprocess.run(
            [sys.executable, "-S", "-c", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_explicit_lazy_serial_exports_remain_compatible_when_installed(self):
        """Direct historic package imports retain their lazy serial boundary."""
        try:
            from eltakobus.serial import RS485SerialInterfaceV2
        except ImportError:
            self.skipTest("serial extra is not installed")
        self.assertIs(RS485SerialInterfaceV2, eltakobus.RS485SerialInterfaceV2)
        self.assertIn("RS485SerialInterfaceV2", dir(eltakobus))

    def test_legacy_serial_class_remains_in_wildcard_import_with_serial_extra(self):
        """Wildcard imports retain both historical serial class names."""
        try:
            from eltakobus.serial import RS485SerialInterface
        except ImportError:
            self.skipTest("serial extra is not installed")
        namespace = {}
        exec("from eltakobus import *", namespace)
        self.assertIs(RS485SerialInterface, namespace["RS485SerialInterface"])

    def test_parser_recovers_when_bad_frame_contains_next_valid_preamble(self):
        """CRC recovery must not discard a valid frame starting inside bad data."""
        valid = discovery_reply()
        # Start with a syntactically valid preamble and place a full valid
        # frame two bytes later.  The outer candidate has an invalid checksum,
        # so recovery must advance and rescan for the overlapping frame.
        stream = b"\xA5\x5A" + valid
        parser = ESP2FrameParser()

        self.assertEqual([valid], parser.feed(stream))
        self.assertEqual(1, len(parser.pop_errors()))
        self.assertEqual(b"", parser.buffered_bytes)

    def test_parser_accepts_memoryview_and_preserves_multiple_frame_order(self):
        """Existing byte-oriented callers may use buffer-protocol objects."""
        first = discovery_reply()
        second = EltakoDiscoveryReply(
            reported_address=2,
            reported_size=1,
            memory_size=127,
            model=bytes.fromhex("04044200"),
            is_fam=False,
        ).serialize()
        parser = ESP2FrameParser()

        self.assertEqual([first, second], parser.feed(memoryview(first + second)))
        self.assertEqual((), parser.errors)

    def test_legacy_asyncio_interface_uses_parser_without_changing_message_type(self):
        """Legacy receive keeps generic ESP2Message results after resyncing."""
        async def scenario():
            bus = RS485SerialInterface("fake://legacy", suppress_echo=False)
            ready = asyncio.get_running_loop().create_future()
            transport = _LegacyTransport()

            async def create_connection(_loop, protocol_factory, **_kwargs):
                protocol = protocol_factory()
                protocol.connection_made(transport)
                return transport, protocol

            with patch(
                "eltakobus.serial.serial_asyncio.create_serial_connection",
                side_effect=create_connection,
            ):
                worker = asyncio.create_task(
                    bus.run(asyncio.get_running_loop(), conn_made=ready)
                )
                await asyncio.wait_for(ready, 0.2)

                valid = discovery_reply()
                invalid = bytearray(valid)
                invalid[-1] ^= 0xFF
                # Feed arbitrary boundaries with noise and a corrupted frame.
                bus.data_received(b"noise" + invalid + valid[:4])
                bus.data_received(valid[4:])

                message = await asyncio.wait_for(bus.received.get(), 0.2)
                self.assertIs(type(message), ESP2Message)
                self.assertEqual(valid, message.serialize())

                worker.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await worker

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
