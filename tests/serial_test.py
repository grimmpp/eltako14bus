"""Unit tests for both serial transport implementations.

The V2 tests use a thread-safe fake serial port but transport real serialized
ESP2 frames. This exercises worker-thread parsing, asyncio consumers,
request/response transactions, concurrent callers, shutdown, and reconnects
without hardware. The legacy tests focus on asyncio protocol buffer waiting
and connection-loss behavior.
"""

import asyncio
import logging
import queue
import serial
import threading
import time
import unittest
from unittest.mock import patch

from eltakobus.message import (
    EltakoDiscoveryReply,
    EltakoDiscoveryRequest,
    Regular4BSMessage,
)
from eltakobus.serial import RS485SerialInterface, RS485SerialInterfaceV2
from eltakobus.transport_metrics import TransportMetrics


class FakeSerialPort:
    """Thread-safe serial double that transports real ESP2 bytes."""

    def __init__(self, on_write=None):
        self._incoming = bytearray()
        self._lock = threading.Lock()
        self._on_write = on_write
        self.fail_reads = threading.Event()
        self.writes = []
        self.closed = False

    def feed(self, data):
        """Make serialized bytes available to the worker's next read."""
        with self._lock:
            self._incoming.extend(data)

    def read_all(self):
        """Return pending bytes, or simulate an unplugged adapter once."""
        if self.fail_reads.is_set():
            self.fail_reads.clear()
            raise serial.SerialException("simulated serial interface disappearance")
        with self._lock:
            data = bytes(self._incoming)
            self._incoming.clear()
            return data

    def write(self, data):
        """Record a write and optionally generate a simulated bus response."""
        self.writes.append(bytes(data))
        if self._on_write is not None:
            self._on_write(bytes(data))
        return len(data)

    def read_until(self, expected):
        return b""

    def close(self):
        """Record that the transport was closed during shutdown/reconnect."""
        self.closed = True


def discovery_reply(address=1):
    return EltakoDiscoveryReply(
        reported_address=address,
        reported_size=1,
        memory_size=127,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    )


def regular_4bs(address=bytes.fromhex("01020304")):
    return Regular4BSMessage(
        address=address,
        status=0,
        data=bytes((1, 2, 3, 8)),
    )


class TestRS485SerialInterfaceV2(unittest.TestCase):
    """Exercise V2's worker thread and its asynchronous public interface."""

    def test_worker_reads_real_frames_and_stops_without_hanging(self):
        """A valid incoming frame is delivered and the worker stops cleanly."""
        fake = FakeSerialPort()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))
            fake.feed(discovery_reply().serialize())

            async def receive_one():
                return await asyncio.wait_for(bus.received.get(), 1)

            message = asyncio.run(receive_one())
            self.assertIsInstance(message, EltakoDiscoveryReply)
            bus.stop()
            bus.join(1)

        self.assertFalse(bus.is_alive())
        self.assertTrue(fake.closed)

    def test_optional_metrics_cover_successful_io_and_status(self):
        """Metrics are opt-in and count only successful fake-port handoffs."""
        fake = FakeSerialPort()
        metrics = TransportMetrics()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False,
                metrics=metrics,
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))
            bus._send(discovery_reply())
            fake.feed(discovery_reply(2).serialize())
            message = asyncio.run(asyncio.wait_for(bus.received.get(), 1))
            self.assertIsInstance(message, EltakoDiscoveryReply)
            bus.stop()
            bus.join(1)

        snapshot = metrics.snapshot()
        self.assertEqual(1, snapshot.messages_sent)
        self.assertEqual(1, snapshot.messages_received)
        self.assertGreaterEqual(snapshot.connection_events, 2)

    def test_metrics_none_preserves_default_constructor_behavior(self):
        """The default remains uninstrumented and keeps the old public shape."""
        bus = RS485SerialInterfaceV2("fake://bus", disabled_echotest=True)
        self.assertIsNone(bus.metrics)

    def test_worker_handles_many_frames_while_consumers_run_concurrently(self):
        """Many concurrent readers receive all frames without queue deadlock."""
        fake = FakeSerialPort()
        frames = [regular_4bs(bytes((0, 0, 0, address))) for address in range(1, 33)]
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))

            async def consume_all():
                consumers = [
                    asyncio.create_task(
                        asyncio.wait_for(bus.received.get(), timeout=1)
                    )
                    for _ in frames
                ]
                fake.feed(b"".join(frame.serialize() for frame in frames))
                return await asyncio.gather(*consumers)

            received = asyncio.run(consume_all())
            bus.stop()
            bus.join(1)

        self.assertEqual(len(frames), len(received))
        self.assertEqual(
            {message.address for message in received},
            {bytes((0, 0, 0, address)) for address in range(1, 33)},
        )
        self.assertFalse(bus.is_alive())

    def test_exchange_gets_a_bus_reply_and_does_not_leave_worker_running(self):
        """A request finds its typed reply while unrelated traffic is tolerated."""
        reply = discovery_reply()
        unrelated = regular_4bs()

        def answer(data):
            self.assertEqual(EltakoDiscoveryRequest(1).serialize(), data)
            fake.feed(unrelated.serialize() + reply.serialize())

        fake = FakeSerialPort(on_write=answer)
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))

            async def exchange_once():
                return await asyncio.wait_for(
                    bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply),
                    1,
                )

            response = asyncio.run(exchange_once())
            bus.stop()
            bus.join(1)

        self.assertEqual(1, response.reported_address)
        self.assertFalse(bus.is_alive())

    def test_exchange_serializes_concurrent_callers_instead_of_hanging(self):
        """Concurrent transactions finish independently instead of corrupting state."""
        fake = FakeSerialPort()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))

            async def concurrent_exchange():
                first = asyncio.create_task(
                    bus.exchange(
                        EltakoDiscoveryRequest(1), EltakoDiscoveryReply,
                        retries=1, timeout=0.05,
                    )
                )
                second = asyncio.create_task(
                    bus.exchange(
                        EltakoDiscoveryRequest(1), EltakoDiscoveryReply,
                        retries=1, timeout=0.05,
                    )
                )
                # Both transactions have no response, but must finish within
                # their own timeouts rather than consuming each other's state.
                return await asyncio.wait_for(
                    asyncio.gather(first, second), 1
                )

            self.assertEqual([None, None], asyncio.run(concurrent_exchange()))
            bus.stop()
            bus.join(1)

        self.assertFalse(bus.is_alive())

    def test_auto_reconnects_after_serial_interface_disappears(self):
        """A failed port is closed, replaced, and able to receive again."""
        first_port = FakeSerialPort()
        second_port = FakeSerialPort()
        second_port.feed(discovery_reply().serialize())
        ports = [first_port, second_port]
        factory_calls = []

        def serial_factory(*args, **kwargs):
            factory_calls.append(args[0])
            return ports[min(len(factory_calls) - 1, len(ports) - 1)]

        status_changes = []
        test_log = logging.getLogger("eltakobus.serial.reconnect_test")
        test_log.propagate = False
        test_log.addHandler(logging.NullHandler())
        with patch("eltakobus.serial.serial.serial_for_url", side_effect=serial_factory):
            bus = RS485SerialInterfaceV2(
                "fake://disappearing-bus",
                log=test_log,
                disabled_echotest=True,
                auto_reconnect=True,
                reconnection_timeout=0.01,
            )
            bus.set_status_changed_handler(status_changes.append)
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))

            # Simulate unplugging the active adapter. The worker must close
            # it, clear the connected event and establish a new port.
            first_port.fail_reads.set()

            async def receive_after_reconnect():
                return await asyncio.wait_for(bus.received.get(), 1)

            message = asyncio.run(receive_after_reconnect())
            bus.stop()
            bus.join(1)

        self.assertIsInstance(message, EltakoDiscoveryReply)
        self.assertGreaterEqual(len(factory_calls), 2)
        self.assertTrue(first_port.closed)
        self.assertTrue(second_port.closed)
        self.assertIn(False, status_changes)
        self.assertGreaterEqual(status_changes.count(True), 2)
        self.assertFalse(bus.is_alive())

    def test_receiver_queue_is_async_and_cancellable(self):
        """Queue reads yield to the event loop and respond to cancellation."""
        receive = queue.Queue()
        receiver = RS485SerialInterfaceV2.ReceiverQueue(
            receive, threading.Lock()
        )

        async def scenario():
            pending = asyncio.create_task(receiver.get())
            await asyncio.sleep(0.02)
            self.assertFalse(pending.done())

            receive.put("message")
            self.assertEqual("message", await asyncio.wait_for(pending, 1))

            cancelled = asyncio.create_task(receiver.get())
            await asyncio.sleep(0)
            cancelled.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await cancelled

        asyncio.run(scenario())

    def test_echo_is_consumed_without_hiding_unrelated_frames(self):
        """Only a matching transmitted echo is suppressed from received traffic."""
        bus = RS485SerialInterfaceV2("loop://", disabled_echotest=True)
        bus.suppress_echo = True
        request = EltakoDiscoveryRequest(1)
        bus._suppress.append((time.time(), request.serialize()))

        self.assertTrue(bus._consume_echo(request.serialize()))
        self.assertFalse(bus._consume_echo(request.serialize()))

    def test_switching_to_callback_completes_dropped_queue_tasks(self):
        """Switching to callback mode drains queued sends without unfinished work."""
        bus = RS485SerialInterfaceV2("loop://", disabled_echotest=True)
        bus._send(EltakoDiscoveryRequest(1))
        self.assertEqual(1, bus.transmit.unfinished_tasks)

        bus.set_callback(lambda message: None)
        self.assertEqual(0, bus.transmit.unfinished_tasks)

    def test_reentrant_receive_callback_does_not_deadlock_worker(self):
        """A receive callback may reconfigure the bus without blocking its worker."""
        fake = FakeSerialPort()
        callback_finished = threading.Event()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )

            def callback(_message):
                bus.set_callback(None)
                callback_finished.set()

            bus.set_callback(callback)
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))
            fake.feed(discovery_reply().serialize())
            self.assertTrue(callback_finished.wait(1))
            bus.stop()
            bus.join(1)

        self.assertFalse(bus.is_alive())

    def test_reentrant_status_callback_does_not_deadlock_worker(self):
        """A connected-status handler may call the transport API safely."""
        fake = FakeSerialPort()
        connected_callback_finished = threading.Event()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )

            def status_handler(connected):
                if connected:
                    bus.set_callback(None)
                    connected_callback_finished.set()

            bus.set_status_changed_handler(status_handler)
            bus.start()
            self.assertTrue(connected_callback_finished.wait(1))
            bus.stop()
            bus.join(1)

        self.assertFalse(bus.is_alive())

    def test_exchange_before_start_returns_without_queue_hang(self):
        """An exchange before start() remains bounded and does not queue a send."""
        bus = RS485SerialInterfaceV2("fake://bus", disabled_echotest=True)

        async def exchange_before_start():
            return await asyncio.wait_for(
                bus.exchange(EltakoDiscoveryRequest(1), timeout=0.01), 0.1
            )

        self.assertIsNone(asyncio.run(exchange_before_start()))
        self.assertEqual(0, bus.transmit.unfinished_tasks)

    def test_exchange_after_stop_returns_without_queue_hang(self):
        """An exchange after stop() remains bounded and does not queue a send."""
        fake = FakeSerialPort()
        with patch("eltakobus.serial.serial.serial_for_url", return_value=fake):
            bus = RS485SerialInterfaceV2(
                "fake://bus", disabled_echotest=True, auto_reconnect=False
            )
            bus.start()
            self.assertTrue(bus.is_serial_connected.wait(1))
            bus.stop()
            bus.join(1)

        async def exchange_after_stop():
            return await asyncio.wait_for(
                bus.exchange(EltakoDiscoveryRequest(1), timeout=0.01), 0.1
            )

        self.assertIsNone(asyncio.run(exchange_after_stop()))
        self.assertEqual(0, bus.transmit.unfinished_tasks)


class TestRS485SerialInterfaceLegacy(unittest.TestCase):
    """Cover buffer and connection lifecycle behavior of the legacy protocol."""

    def test_buffer_wait_returns_when_data_already_exists(self):
        """Waiting returns immediately when data arrived before the waiter."""
        async def scenario():
            bus = RS485SerialInterface("fake://bus", suppress_echo=False)
            bus.data_received(b"x" * 14)
            await asyncio.wait_for(bus.await_bufferlevel(14), 0.1)

        asyncio.run(scenario())

    def test_optional_metrics_cover_connection_and_successful_send(self):
        """The legacy protocol reports status and writes without hardware."""
        class FakeTransport:
            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(bytes(data))

        async def scenario():
            metrics = TransportMetrics()
            bus = RS485SerialInterface("fake://bus", suppress_echo=False,
                                       metrics=metrics)
            bus.transport = asyncio.get_running_loop().create_future()
            fake = FakeTransport()
            bus.connection_made(fake)
            bus.transport = fake
            await bus.send(discovery_reply())
            bus.connection_lost(None)
            snapshot = metrics.snapshot()
            self.assertEqual(1, snapshot.messages_sent)
            self.assertEqual(2, snapshot.connection_events)
            self.assertEqual([discovery_reply().serialize()], fake.writes)

        asyncio.run(scenario())

    def test_connection_lost_wakes_waiting_reader(self):
        """Connection loss wakes a blocked reader instead of leaving it hanging."""
        async def scenario():
            bus = RS485SerialInterface("fake://bus", suppress_echo=False)
            waiting = asyncio.create_task(bus.await_bufferlevel(14))
            await asyncio.sleep(0)
            bus.connection_lost(None)
            with self.assertRaises(EOFError):
                await asyncio.wait_for(waiting, 0.1)

        asyncio.run(scenario())

    def test_simultaneous_buffer_waiters_are_rejected(self):
        """Only one legacy buffer waiter is allowed and cancellation is safe."""
        async def scenario():
            bus = RS485SerialInterface("fake://bus", suppress_echo=False)
            first = asyncio.create_task(bus.await_bufferlevel(14))
            await asyncio.sleep(0)
            with self.assertRaises(RuntimeError):
                await bus.await_bufferlevel(14)
            first.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await first

        asyncio.run(scenario())
