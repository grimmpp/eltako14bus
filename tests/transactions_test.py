"""Tests for the opt-in, transport-neutral transaction manager.

The tests use :class:`eltakobus.virtual_bus.VirtualBus` where its queue-based
receive transport is useful.  No serial interface is changed or required.
"""

import asyncio
import unittest

from eltakobus.error import (
    CommandRejected,
    CommandTimeout,
    TransactionCancelled,
    UnsupportedCommand,
)
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest, RPSMessage
from eltakobus.transactions import TransactionManager, TransactionOptions
from eltakobus.virtual_bus import VirtualBus


def response(address=1):
    return EltakoDiscoveryReply(
        reported_address=address,
        reported_size=1,
        memory_size=2,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    )


def passive(address=99):
    return RPSMessage(address=bytes((0, 0, 0, address)), status=0x30, data=b"\x70")


class TestTransactionManager(unittest.TestCase):
    """Verify matching, retries, cancellation, and passive-message delivery."""

    def test_matches_response_and_reports_monotonic_metrics(self):
        """A request-specific matcher resolves only its response via VirtualBus."""

        async def scenario():
            bus = VirtualBus()
            async with TransactionManager(bus) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: isinstance(message, EltakoDiscoveryReply),
                    )
                )
                while not bus.sent_raw:
                    await asyncio.sleep(0)
                await bus.inject(response(1))
                return await task

        result = asyncio.run(scenario())
        self.assertEqual(1, result.response.reported_address)
        self.assertEqual(1, result.attempts)
        self.assertGreaterEqual(result.elapsed, 0.0)

    def test_preserves_unmatched_messages_in_queue_and_callback(self):
        """Passive telegrams survive while a different response satisfies a request."""

        async def scenario():
            seen = []
            bus = VirtualBus()
            async with TransactionManager(bus, unmatched_callback=seen.append) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: isinstance(message, EltakoDiscoveryReply),
                    )
                )
                while not bus.sent_raw:
                    await asyncio.sleep(0)
                unsolicited = passive()
                await bus.inject(unsolicited)
                await bus.inject(response(1))
                result = await task
                return result, await transactions.unmatched.get(), seen

        result, unmatched, seen = asyncio.run(scenario())
        self.assertEqual(1, result.response.reported_address)
        self.assertEqual(unmatched.address, passive().address)
        self.assertEqual([unmatched], seen)

    def test_retries_are_bounded_and_second_attempt_can_succeed(self):
        """The first timeout retries once; a second response completes the request."""

        async def scenario():
            bus = VirtualBus()
            async with TransactionManager(bus) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: isinstance(message, EltakoDiscoveryReply),
                        options=TransactionOptions(timeout=0.01, retries=1),
                    )
                )
                while len(bus.sent_raw) < 2:
                    await asyncio.sleep(0)
                await bus.inject(response(2))
                return await task

        result = asyncio.run(scenario())
        self.assertEqual(2, result.response.reported_address)
        self.assertEqual(2, result.attempts)
        self.assertEqual(1, result.metrics.retries)

    def test_timeout_exposes_bounded_attempt_metrics(self):
        """Exhausted attempts raise a specific timeout with diagnostic metrics."""

        async def scenario():
            async with TransactionManager(VirtualBus()) as transactions:
                with self.assertRaises(CommandTimeout) as caught:
                    await transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: False,
                        options=TransactionOptions(timeout=0.001, retries=1),
                    )
                return caught.exception

        error = asyncio.run(scenario())
        self.assertEqual(2, error.metrics.attempts)
        self.assertEqual(1, error.metrics.retries)

    def test_rejecter_raises_explicit_command_rejected(self):
        """A protocol-specific reject matcher takes precedence over success matching."""

        async def scenario():
            bus = VirtualBus()
            async with TransactionManager(bus) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: isinstance(message, EltakoDiscoveryReply),
                        rejecter=lambda message: isinstance(message, RPSMessage),
                    )
                )
                while not bus.sent_raw:
                    await asyncio.sleep(0)
                await bus.inject(passive())
                with self.assertRaises(CommandRejected) as caught:
                    await task
                return caught.exception

        error = asyncio.run(scenario())
        self.assertEqual(passive().address, error.response.address)

    def test_cancellation_removes_waiter_and_late_response_is_unmatched(self):
        """Cancelling a request cannot let its late response satisfy later work."""

        async def scenario():
            bus = VirtualBus()
            async with TransactionManager(bus) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        EltakoDiscoveryRequest(1),
                        matcher=lambda message: isinstance(message, EltakoDiscoveryReply),
                    )
                )
                while not bus.sent_raw:
                    await asyncio.sleep(0)
                task.cancel()
                with self.assertRaises(TransactionCancelled):
                    await task
                late = response(1)
                await bus.inject(late)
                return await transactions.unmatched.get()

        self.assertEqual(1, asyncio.run(scenario()).reported_address)

    def test_invalid_transport_is_rejected_before_a_request_is_sent(self):
        """The public API reports missing receive support as UnsupportedCommand."""

        class SendOnly:
            async def send(self, request):
                pass

        with self.assertRaises(UnsupportedCommand):
            TransactionManager(SendOnly())

    def test_receive_method_is_supported_without_a_public_queue(self):
        """A transport may expose an async receive() method instead of received."""

        class ReceiveOnly:
            def __init__(self):
                self.incoming = asyncio.Queue()
                self.sent = []

            async def send(self, request):
                self.sent.append(request)

            async def receive(self):
                return await self.incoming.get()

        async def scenario():
            transport = ReceiveOnly()
            async with TransactionManager(transport) as transactions:
                task = asyncio.create_task(
                    transactions.request(
                        "request",
                        matcher=lambda message: message == "response",
                    )
                )
                while not transport.sent:
                    await asyncio.sleep(0)
                await transport.incoming.put("response")
                return await task

        self.assertEqual("response", asyncio.run(scenario()).response)

    def test_receiver_exception_fails_active_waiter_and_is_consumed_on_close(self):
        """A broken receive stream aborts requests promptly and cleanup stays safe."""

        class FailingReceiveTransport:
            def __init__(self):
                self.sent = asyncio.Event()
                self.send_cancelled = asyncio.Event()
                self.fail_receive = asyncio.Event()

            async def send(self, request):
                self.sent.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
                    raise

            async def receive(self):
                await self.fail_receive.wait()
                raise ConnectionError("transport disconnected")

        async def scenario():
            transport = FailingReceiveTransport()
            transactions = TransactionManager(transport)
            task = asyncio.create_task(
                transactions.request(
                    "request",
                    matcher=lambda message: message == "response",
                    options=TransactionOptions(timeout=1.0),
                )
            )
            await transport.sent.wait()
            started = asyncio.get_running_loop().time()
            transport.fail_receive.set()
            with self.assertRaisesRegex(ConnectionError, "transport disconnected"):
                await asyncio.wait_for(task, 0.1)
            elapsed = asyncio.get_running_loop().time() - started
            await transactions.aclose()
            return elapsed, transport.send_cancelled.is_set()

        elapsed, send_cancelled = asyncio.run(scenario())
        self.assertLess(elapsed, 0.1)
        self.assertTrue(send_cancelled)

    def test_send_is_bounded_by_the_attempt_timeout(self):
        """A blocked send is cancelled when the transaction deadline expires."""

        class BlockingSendTransport:
            def __init__(self):
                self.send_started = asyncio.Event()
                self.send_cancelled = asyncio.Event()
                self.incoming = asyncio.Queue()

            async def send(self, request):
                self.send_started.set()
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    self.send_cancelled.set()
                    raise

            async def receive(self):
                return await self.incoming.get()

        async def scenario():
            transport = BlockingSendTransport()
            async with TransactionManager(transport) as transactions:
                started = asyncio.get_running_loop().time()
                with self.assertRaises(CommandTimeout) as caught:
                    await transactions.request(
                        "request",
                        matcher=lambda message: message == "response",
                        options=TransactionOptions(timeout=0.01),
                    )
                elapsed = asyncio.get_running_loop().time() - started
                return caught.exception, elapsed, transport.send_cancelled.is_set()

        error, elapsed, send_cancelled = asyncio.run(scenario())
        self.assertEqual(1, error.metrics.attempts)
        self.assertTrue(send_cancelled)
        self.assertLess(elapsed, 0.1)
