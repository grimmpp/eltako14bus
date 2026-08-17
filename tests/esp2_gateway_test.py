"""Tests for the ESP2-over-TCP gateway adapter.

These tests use a fake socket and real serialized ESP2 frames.  They verify
that the adapter can receive unsolicited bus traffic, complete an asynchronous
request/response exchange, and reconnect after a gateway disconnects.  No
network device or physical bus is required.
"""

import asyncio
import json
import socket
import threading
import time
import unittest
from pathlib import Path

from eltakobus.error import TimeoutError
from eltakobus.esp2_gateway import ESP2TCPSerialInterface
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest
from eltakobus.transport_metrics import TransportMetrics


def reply(address=1):
    return EltakoDiscoveryReply(
        reported_address=address,
        reported_size=1,
        memory_size=127,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    )


class FakeSocket:
    def __init__(self, on_send=None):
        self.on_send = on_send
        self.incoming = []
        self.condition = threading.Condition()
        self.closed = False

    def settimeout(self, timeout):
        self.timeout = timeout

    def connect(self, address):
        self.address = address

    def sendall(self, data):
        if self.on_send:
            self.on_send(self, bytes(data))

    def feed(self, data):
        with self.condition:
            self.incoming.append(bytes(data))
            self.condition.notify()

    def recv(self, size):
        with self.condition:
            if not self.incoming:
                self.condition.wait(getattr(self, "timeout", 0.1))
            if self.closed:
                return b""
            if not self.incoming:
                raise socket.timeout()
            return self.incoming.pop(0)[:size]

    def close(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()


class TestESP2TCPSerialInterface(unittest.TestCase):
    def test_replays_all_recorded_passive_frames(self):
        """Every captured hardware frame passes through the TCP adapter parser."""
        report_path = Path(__file__).parent / "resources" / "hardware_test_AQ028YCS_passive_report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        samples = report["devices"][report["ports"][0]]["sample_frames"]
        bus = ESP2TCPSerialInterface("recorded", auto_reconnect=False)

        for sample in samples:
            raw = bytes.fromhex(sample["hex"])
            # Exercise the stream parser with the same kind of fragmentation
            # that a TCP recv() can produce.
            bus._process_bytes(raw[:5])
            bus._process_bytes(raw[5:])

        parsed = [bus.receive.get_nowait() for _ in samples]
        self.assertEqual(len(samples), len(parsed))
        self.assertEqual([sample["hex"] for sample in samples],
                         [message.serialize().hex() for message in parsed])

    def test_receives_and_exchanges_esp2_frames(self):
        sockets = []

        def factory(*args):
            sock = FakeSocket(
                on_send=lambda current, data: current.feed(reply().serialize())
            )
            sockets.append(sock)
            return sock

        bus = ESP2TCPSerialInterface(
            "gateway", 5000, socket_factory=factory,
            reconnection_timeout=0.01, delay_message=0,
        )
        bus.start()
        self.assertTrue(bus.is_serial_connected.wait(1))

        async def run_exchange():
            return await asyncio.wait_for(
                bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply,
                             retries=1, timeout=0.5), 1
            )

        result = asyncio.run(run_exchange())
        self.assertEqual(result.reported_address, 1)
        bus.stop()
        bus.join(1)
        self.assertFalse(bus.is_alive())

    def test_optional_metrics_cover_successful_io_and_connection_status(self):
        """Fake TCP traffic updates metrics without changing the adapter API."""
        metrics = TransportMetrics()
        sockets = []

        def factory(*args):
            sock = FakeSocket(
                on_send=lambda current, data: current.feed(reply(3).serialize())
            )
            sockets.append(sock)
            return sock

        bus = ESP2TCPSerialInterface(
            "gateway", socket_factory=factory, delay_message=0,
            reconnection_timeout=0.01, metrics=metrics,
        )
        bus.start()
        self.assertTrue(bus.is_serial_connected.wait(1))
        async def run_exchange():
            return await asyncio.wait_for(
                bus.exchange(EltakoDiscoveryRequest(3), EltakoDiscoveryReply,
                             retries=1, timeout=0.5), 1
            )
        self.assertEqual(3, asyncio.run(run_exchange()).reported_address)
        bus.stop()
        bus.join(1)
        snapshot = metrics.snapshot()
        self.assertEqual(1, snapshot.messages_sent)
        self.assertEqual(1, snapshot.messages_received)
        self.assertGreaterEqual(snapshot.connection_events, 2)

    def test_reconnects_after_gateway_disappears(self):
        sockets = []

        def factory(*args):
            sock = FakeSocket()
            sockets.append(sock)
            return sock

        bus = ESP2TCPSerialInterface(
            "gateway", socket_factory=factory,
            reconnection_timeout=0.01, delay_message=0,
        )
        bus.start()
        self.assertTrue(bus.is_serial_connected.wait(1))
        sockets[0].close()
        self.assertTrue(
            self._wait_until(lambda: len(sockets) >= 2 and bus.is_active()),
            "adapter did not reconnect after socket disappearance",
        )
        bus.stop()
        bus.join(1)
        self.assertFalse(bus.is_alive())

    def test_exchange_without_worker_raises_timeout_without_queue_hang(self):
        """TCP exchanges before start() or after stop() fail without queueing."""
        bus = ESP2TCPSerialInterface(
            "gateway", auto_reconnect=False,
            socket_factory=lambda *_args: FakeSocket(),
        )

        async def exchange_before_start():
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(
                    bus.exchange(EltakoDiscoveryRequest(1), timeout=0.01), 0.1
                )

        asyncio.run(exchange_before_start())
        self.assertEqual(0, bus.transmit.unfinished_tasks)

        bus.start()
        self.assertTrue(bus.is_serial_connected.wait(1))
        bus.stop()
        bus.join(1)

        async def exchange_after_stop():
            with self.assertRaises(TimeoutError):
                await asyncio.wait_for(
                    bus.exchange(EltakoDiscoveryRequest(1), timeout=0.01), 0.1
                )

        asyncio.run(exchange_after_stop())
        self.assertEqual(0, bus.transmit.unfinished_tasks)

    @staticmethod
    def _wait_until(predicate, timeout=1):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return predicate()


if __name__ == "__main__":
    unittest.main()
