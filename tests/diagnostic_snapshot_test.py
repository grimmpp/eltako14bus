"""Tests for side-effect-free, JSON-serializable diagnostics snapshots."""

import asyncio
import json
import unittest

from eltakobus.diagnostic_snapshot import (
    DIAGNOSTICS_SCHEMA_VERSION,
    snapshot_dispatcher,
    snapshot_gateway,
    snapshot_parser,
    snapshot_transport,
)
from eltakobus.esp2_frame import ESP2FrameParser
from eltakobus.esp2_gateway import ESP2TCPSerialInterface
from eltakobus.esp3_dispatcher import ESP3Dispatcher
from eltakobus.esp3_frame import ESP3Frame, ESP3FrameParser
from eltakobus.message import EltakoDiscoveryReply
from eltakobus.transport_metrics import TransportMetrics


class FrameTransport:
    def __init__(self):
        self.received = asyncio.Queue()
        self.sent = []

    async def send(self, frame):
        self.sent.append(frame)


class PassiveOnlyParser:
    """Expose the parser snapshot protocol while rejecting destructive access."""

    buffered_bytes = b"\xa5"
    errors = ()
    discarded_bytes = 3
    max_errors = 2

    def pop_errors(self):
        raise AssertionError("snapshot must not consume parser errors")

    def reset(self):
        raise AssertionError("snapshot must not reset parser state")


class DiagnosticSnapshotTest(unittest.TestCase):
    """Snapshots expose metrics without consuming errors or queue entries."""

    def setUp(self):
        self.esp2_frame = EltakoDiscoveryReply(
            reported_address=1,
            reported_size=1,
            memory_size=127,
            model=bytes.fromhex("04044200"),
            is_fam=False,
        ).serialize()

    def test_esp2_parser_snapshot_is_non_destructive_and_serializable(self):
        parser = ESP2FrameParser(max_errors=2)
        broken = bytearray(self.esp2_frame)
        broken[-1] ^= 0xFF
        parser.feed(b"noise" + broken + b"\xA5")

        snapshot = snapshot_parser(parser)
        encoded = json.loads(snapshot.to_json())

        self.assertEqual("esp2", snapshot.protocol)
        self.assertEqual(1, snapshot.buffered_bytes)
        self.assertEqual("a5", snapshot.buffered_hex)
        self.assertGreaterEqual(snapshot.discarded_bytes, 6)
        self.assertEqual(1, len(snapshot.retained_errors))
        self.assertEqual(1, len(parser.errors), "snapshot must not pop parser errors")
        self.assertEqual("ParseError", encoded["retained_errors"][0]["error_type"])
        self.assertEqual([["ParseError", 1]], encoded["error_counts"])

    def test_esp3_parser_snapshot_preserves_partial_frame_and_errors(self):
        parser = ESP3FrameParser(max_errors=3)
        frame = bytes(ESP3Frame(4, b"\x04\x01"))
        damaged = bytearray(frame)
        damaged[5] ^= 0x01
        parser.feed(damaged + frame[:3])

        snapshot = snapshot_parser(parser)

        self.assertEqual("esp3", snapshot.protocol)
        self.assertEqual(3, snapshot.buffered_bytes)
        self.assertEqual(frame[:3].hex(), snapshot.buffered_hex)
        self.assertEqual((('ESP3HeaderCRCError', 1),), snapshot.error_counts)
        self.assertEqual(1, len(parser.errors))

    def test_parser_snapshot_uses_only_passive_parser_accessors(self):
        """Snapshot creation must never call a destructive parser method."""
        snapshot = snapshot_parser(PassiveOnlyParser(), protocol="esp2")

        self.assertEqual("esp2", snapshot.protocol)
        self.assertEqual("a5", snapshot.buffered_hex)
        self.assertEqual(3, snapshot.discarded_bytes)

    def test_transport_snapshot_reads_endpoint_queues_and_parser(self):
        gateway = ESP2TCPSerialInterface("127.0.0.1", 5000)
        gateway.transmit.put((0, object()))
        gateway.receive.put(object())
        gateway._frame_parser.feed(b"junk")

        snapshot = snapshot_transport(gateway)
        queues = {queue.name: queue for queue in snapshot.queues}

        self.assertEqual("ESP2TCPSerialInterface", snapshot.transport_type)
        self.assertEqual("127.0.0.1:5000", snapshot.endpoint)
        self.assertFalse(snapshot.active)
        self.assertFalse(snapshot.worker_alive)
        self.assertTrue(snapshot.auto_reconnect)
        self.assertEqual(1, queues["transmit"].depth)
        self.assertEqual(1, queues["receive"].depth)
        self.assertEqual(4, snapshot.parser.discarded_bytes)
        self.assertEqual(1, gateway.transmit.qsize())
        self.assertEqual(1, gateway.receive.qsize())

    def test_transport_snapshot_includes_opt_in_metrics_without_consuming_state(self):
        """Gateway reports expose cumulative metrics when explicitly enabled."""
        gateway = ESP2TCPSerialInterface("gateway.local", 5000, metrics=TransportMetrics())
        gateway.metrics.record_message("received", 2)
        gateway.metrics.record_connection(True, reason="test")

        snapshot = snapshot_transport(gateway)

        self.assertIsNotNone(snapshot.metrics)
        self.assertEqual(2, snapshot.metrics.messages_received)
        self.assertEqual(1, snapshot.metrics.connection_events)
        self.assertEqual(2, gateway.metrics.snapshot().messages_received)

    def test_dispatcher_snapshot_normalizes_counters_and_queue_depths(self):
        async def scenario():
            transport = FrameTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                await transport.received.put(ESP3Frame(4, b"\x04\x01"))
                await asyncio.wait_for(dispatcher.events.get(), 0.1)
                return snapshot_dispatcher(dispatcher)

        snapshot = asyncio.run(scenario())
        counters = dict(snapshot.counters)
        queues = {queue.name: queue.depth for queue in snapshot.queues}

        self.assertEqual(1, counters["received_frames"])
        self.assertEqual(1, counters["event_packets"])
        self.assertEqual(1, queues["packets"])
        self.assertEqual(0, queues["events"])
        self.assertFalse(snapshot.closed)

    def test_gateway_snapshot_has_stable_schema_and_json_safe_metadata(self):
        gateway = ESP2TCPSerialInterface("gateway.local", 5000)
        ports = [1, 2]
        snapshot = snapshot_gateway(
            gateway,
            identity={"base_id": "FF-AA-00-01", "raw": b"\x01\x02"},
            metadata={"site": "lab", "ports": ports},
            captured_at="2026-08-18T12:00:00Z",
        )
        ports.append(3)
        report = json.loads(snapshot.to_json(indent=2))

        self.assertEqual(DIAGNOSTICS_SCHEMA_VERSION, report["schema_version"])
        self.assertEqual("2026-08-18T12:00:00Z", report["captured_at"])
        self.assertEqual("0102", report["identity"]["raw"])
        self.assertEqual([1, 2], report["metadata"]["ports"])
        self.assertEqual("gateway.local:5000", report["transport"]["endpoint"])
        self.assertIsNone(report["dispatcher"])
        with self.assertRaises(TypeError):
            snapshot.identity["base_id"] = "changed"

    def test_invalid_sources_are_rejected(self):
        with self.assertRaises(TypeError):
            snapshot_parser(None)
        with self.assertRaises(TypeError):
            snapshot_transport(None)
        with self.assertRaises(TypeError):
            snapshot_gateway(None)


if __name__ == "__main__":
    unittest.main()
