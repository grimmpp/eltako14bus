"""Concurrency and lifecycle tests for the native ESP3 dispatcher."""

import asyncio
import unittest

from eltakobus.esp3_dispatcher import (
    ESP3CommandTimeout,
    ESP3Dispatcher,
    ESP3DispatcherClosed,
)
from eltakobus.esp3_frame import ESP3Frame
from eltakobus.esp3_packet import ESP3Command, ESP3Event, ESP3Response


class FrameTransport:
    """Small asynchronous frame transport used without serial hardware."""

    def __init__(self):
        self.received = asyncio.Queue()
        self.sent = []

    async def send(self, frame):
        self.sent.append(frame)


async def wait_for_count(items, count):
    while len(items) < count:
        await asyncio.sleep(0)


class TestESP3Dispatcher(unittest.TestCase):
    """Commands remain correlated while unsolicited traffic keeps flowing."""

    def test_command_response_does_not_consume_radio_or_event(self):
        """Interleaved traffic reaches dedicated queues during a command wait."""

        async def scenario():
            transport = FrameTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                task = asyncio.create_task(dispatcher.execute(ESP3Command(8)))
                await wait_for_count(transport.sent, 1)
                await transport.received.put(
                    ESP3Frame(1, bytes.fromhex("f6700102030430"),
                              bytes.fromhex("03ffffffff5000"))
                )
                await transport.received.put(ESP3Frame(4, b"\x04\xaa"))
                await transport.received.put(ESP3Frame(2, b"\x00\x10"))
                return (
                    await task,
                    await dispatcher.receive_radio(),
                    await dispatcher.receive_event(),
                    dispatcher.diagnostics,
                )

        response, radio, event, diagnostics = asyncio.run(scenario())
        self.assertEqual(b"\x10", response.data)
        self.assertEqual(bytes.fromhex("01020304"), radio.sender)
        self.assertEqual(b"\xaa", event.data)
        self.assertEqual(3, diagnostics.received_frames)
        self.assertEqual(1, diagnostics.command_responses)

    def test_concurrent_callers_are_serialized(self):
        """A second command is not sent until the first response is assigned."""

        async def scenario():
            transport = FrameTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                first = asyncio.create_task(dispatcher.execute(ESP3Command(1)))
                second = asyncio.create_task(dispatcher.execute(ESP3Command(2)))
                await wait_for_count(transport.sent, 1)
                sent_before_response = len(transport.sent)
                await transport.received.put(ESP3Frame(2, b"\x00\x01"))
                await wait_for_count(transport.sent, 2)
                await transport.received.put(ESP3Frame(2, b"\x00\x02"))
                return sent_before_response, await first, await second, transport.sent

        before, first, second, sent = asyncio.run(scenario())
        self.assertEqual(1, before)
        self.assertEqual([1, 2], [frame.data[0] for frame in sent])
        self.assertEqual(b"\x01", first.data)
        self.assertEqual(b"\x02", second.data)

    def test_timeout_makes_late_response_unsolicited(self):
        """A timed-out response cannot satisfy a later command."""

        async def scenario():
            transport = FrameTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                with self.assertRaises(ESP3CommandTimeout):
                    await dispatcher.execute(ESP3Command(1), timeout=0.001)
                await transport.received.put(ESP3Frame(2, b"\x00\x99"))
                response = await asyncio.wait_for(dispatcher.responses.get(), 0.1)
                return response, dispatcher.diagnostics

        response, diagnostics = asyncio.run(scenario())
        self.assertEqual(b"\x99", response.data)
        self.assertEqual(1, diagnostics.unsolicited_responses)

    def test_decode_error_is_reported_and_receiver_continues(self):
        """Malformed semantic frames do not terminate following packet delivery."""

        async def scenario():
            transport = FrameTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                await transport.received.put(ESP3Frame(4))
                await transport.received.put(ESP3Frame(4, b"\x04\x01"))
                frame, error = await asyncio.wait_for(dispatcher.errors.get(), 0.1)
                event = await asyncio.wait_for(dispatcher.receive_event(), 0.1)
                return frame, error, event, dispatcher.diagnostics

        frame, error, event, diagnostics = asyncio.run(scenario())
        self.assertEqual(4, frame.packet_type)
        self.assertIn("no event code", str(error))
        self.assertIsInstance(event, ESP3Event)
        self.assertEqual(1, diagnostics.decode_errors)

    def test_transport_failure_fails_active_command_and_close_is_safe(self):
        """A receive disconnect wakes the command instead of waiting for timeout."""

        class FailingTransport(FrameTransport):
            def __init__(self):
                super().__init__()
                self.fail = asyncio.Event()

            async def receive(self):
                await self.fail.wait()
                raise ConnectionError("ESP3 disconnected")

        async def scenario():
            transport = FailingTransport()
            dispatcher = ESP3Dispatcher(transport)
            task = asyncio.create_task(
                dispatcher.execute(ESP3Command(1), timeout=1.0)
            )
            await wait_for_count(transport.sent, 1)
            transport.fail.set()
            with self.assertRaisesRegex(ConnectionError, "disconnected"):
                await asyncio.wait_for(task, 0.1)
            await dispatcher.aclose()

        asyncio.run(scenario())

    def test_close_fails_pending_command(self):
        """Explicit shutdown has a distinct lifecycle exception."""

        async def scenario():
            transport = FrameTransport()
            dispatcher = ESP3Dispatcher(transport)
            task = asyncio.create_task(dispatcher.execute(ESP3Command(1)))
            await wait_for_count(transport.sent, 1)
            await dispatcher.aclose()
            with self.assertRaises(ESP3DispatcherClosed):
                await task

        asyncio.run(scenario())

    def test_timeout_bounds_blocked_transport_send(self):
        """The command timeout covers transmission as well as its response."""

        class BlockingSendTransport(FrameTransport):
            def __init__(self):
                super().__init__()
                self.send_started = asyncio.Event()
                self.send_cancelled = asyncio.Event()

            async def send(self, frame):
                self.send_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
                    raise

        async def scenario():
            transport = BlockingSendTransport()
            async with ESP3Dispatcher(transport) as dispatcher:
                with self.assertRaises(ESP3CommandTimeout):
                    await asyncio.wait_for(
                        dispatcher.execute(ESP3Command(1), timeout=0.001), 0.1
                    )
                return transport.send_cancelled.is_set()

        self.assertTrue(asyncio.run(scenario()))

    def test_close_cancels_blocked_send_and_fails_command(self):
        """Shutdown cannot leave a command stuck inside transport.send()."""

        class BlockingSendTransport(FrameTransport):
            def __init__(self):
                super().__init__()
                self.send_started = asyncio.Event()
                self.send_cancelled = asyncio.Event()

            async def send(self, frame):
                self.send_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
                    raise

        async def scenario():
            transport = BlockingSendTransport()
            dispatcher = ESP3Dispatcher(transport)
            task = asyncio.create_task(dispatcher.execute(ESP3Command(1)))
            await transport.send_started.wait()
            await dispatcher.aclose()
            with self.assertRaises(ESP3DispatcherClosed):
                await asyncio.wait_for(task, 0.1)
            return transport.send_cancelled.is_set()

        self.assertTrue(asyncio.run(scenario()))

    def test_receive_method_wakes_on_transport_failure(self):
        """Dedicated receive helpers propagate disconnects without hanging."""

        class FailingTransport(FrameTransport):
            def __init__(self):
                super().__init__()
                self.fail = asyncio.Event()

            async def receive(self):
                await self.fail.wait()
                raise ConnectionError("ESP3 receive failed")

        async def scenario():
            transport = FailingTransport()
            dispatcher = ESP3Dispatcher(transport)
            task = asyncio.create_task(dispatcher.receive_event())
            await asyncio.sleep(0)
            transport.fail.set()
            with self.assertRaisesRegex(ConnectionError, "receive failed"):
                await asyncio.wait_for(task, 0.1)
            await dispatcher.aclose()

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
