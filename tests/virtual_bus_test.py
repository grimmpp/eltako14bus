"""Tests for deterministic, hardware-free bus replay and fault injection.

These tests exercise the public virtual bus API with real ESP2 frames.  They
ensure that request/response scripts, unsolicited replay, faults, connection
changes, and concurrent callers remain deterministic and never require a
serial adapter.
"""

import asyncio
import json
import unittest

from eltakobus.error import TimeoutError
from eltakobus.message import (
    EltakoDiscoveryReply,
    EltakoDiscoveryRequest,
    EltakoMemoryRequest,
    EltakoMemoryResponse,
    RPSMessage,
)
from eltakobus.virtual_bus import (
    Direction,
    Fault,
    FaultRule,
    ReplayAction,
    ReplayEvent,
    VirtualBus,
    VirtualBusDisconnected,
    decode_recording,
    encode_recording,
)


def discovery_reply(address=1):
    return EltakoDiscoveryReply(
        reported_address=address,
        reported_size=1,
        memory_size=2,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    )


def radio_message(address=1):
    return RPSMessage(
        address=bytes((0, 0, 0, address)),
        status=0x30,
        data=b"\x70",
    )


class TestVirtualBus(unittest.TestCase):
    """Verify the virtual bus behaves like a deterministic BusInterface."""

    def test_scripted_exchanges_are_typed_and_fifo_ordered(self):
        """Repeated requests consume typed responses in insertion order."""

        async def scenario():
            bus = VirtualBus()
            request = EltakoDiscoveryRequest(1)
            bus.queue_response(request, discovery_reply(1))
            bus.queue_response(request, discovery_reply(2))
            first = await bus.exchange(request, EltakoDiscoveryReply)
            second = await bus.exchange(request, EltakoDiscoveryReply)
            return bus, first, second

        bus, first, second = asyncio.run(scenario())
        self.assertEqual((1, 2), (first.reported_address, second.reported_address))
        self.assertEqual(2, len(bus.attempted_raw))
        self.assertEqual(bus.attempted_raw, bus.sent_raw)

    def test_businterface_memory_read_uses_scripted_responses(self):
        """Existing BusInterface helpers work against the virtual transport."""

        async def scenario():
            bus = VirtualBus()
            for row in range(3):
                bus.queue_response(
                    EltakoMemoryRequest(5, row),
                    EltakoMemoryResponse(row, bytes((row,)) * 8),
                )
            return await bus.read_mem(5, known_memory_size=2)

        self.assertEqual(
            (b"\x00" * 8, b"\x01" * 8, b"\x02" * 8),
            asyncio.run(scenario()),
        )

    def test_injected_frames_use_queue_or_callback(self):
        """Unsolicited traffic supports the same two consumer styles as serial."""

        async def scenario():
            bus = VirtualBus()
            await bus.inject(radio_message(1))
            queued = await bus.received.get()
            callback_messages = []
            bus.set_callback(callback_messages.append)
            await bus.inject(radio_message(2))
            return bus, queued, callback_messages

        bus, queued, callback_messages = asyncio.run(scenario())
        self.assertEqual(bytes((0, 0, 0, 1)), queued.address)
        self.assertEqual(bytes((0, 0, 0, 2)), callback_messages[0].address)
        self.assertEqual(2, bus.raw_received.qsize())
        self.assertTrue(bus.received.empty())

    def test_fault_rules_drop_duplicate_and_corrupt_exact_occurrences(self):
        """Receive faults are repeatable, including disconnect and reconnect."""

        async def scenario():
            bus = VirtualBus(faults=(
                FaultRule(Direction.RECEIVE, 1, Fault.DROP),
                FaultRule(Direction.RECEIVE, 2, Fault.DUPLICATE),
                FaultRule(Direction.RECEIVE, 3, Fault.CORRUPT_CHECKSUM),
                FaultRule(Direction.RECEIVE, 4, Fault.DISCONNECT),
                FaultRule(Direction.RECEIVE, 5, Fault.RECONNECT),
            ))
            statuses = []
            bus.set_status_changed_handler(statuses.append)
            delivered = [await bus.inject(radio_message(index)) for index in range(1, 6)]
            queued = [await bus.received.get() for _ in range(3)]
            return bus, delivered, queued, statuses

        bus, delivered, queued, statuses = asyncio.run(scenario())
        self.assertEqual([0, 2, 0, 0, 1], [len(messages) for messages in delivered])
        self.assertEqual([2, 2, 5], [message.address[-1] for message in queued])
        self.assertEqual(1, len(bus.decode_errors))
        self.assertEqual(4, bus.raw_received.qsize())
        self.assertEqual([True, False, True], statuses)
        self.assertTrue(bus.connected)
        self.assertEqual(Direction.RECEIVE, bus.dropped[0][0])

    def test_dropped_response_can_be_retried_with_injected_delay(self):
        """A bounded retry consumes the next script and uses the supplied sleeper."""

        async def scenario():
            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            request = EltakoDiscoveryRequest(1)
            bus = VirtualBus(
                faults=(FaultRule(Direction.RECEIVE, 1, Fault.DROP),),
                sleeper=fake_sleep,
            )
            bus.queue_response(request, discovery_reply(1))
            bus.queue_response(request, discovery_reply(2))
            response = await bus.exchange(
                request,
                EltakoDiscoveryReply,
                retries=2,
                retry_delay=0.25,
            )
            return bus, response, sleeps

        bus, response, sleeps = asyncio.run(scenario())
        self.assertEqual(2, response.reported_address)
        self.assertEqual(2, len(bus.attempted_raw))
        self.assertEqual([0.25], sleeps)

    def test_scripted_response_delay_is_bounded_by_attempt_timeout(self):
        """A late scripted response times out without sleeping past its deadline."""

        async def scenario():
            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            request = EltakoDiscoveryRequest(1)
            bus = VirtualBus(sleeper=fake_sleep)
            bus.queue_response(request, discovery_reply(), delay=0.05)
            with self.assertRaises(TimeoutError):
                await bus.exchange(request, timeout=0.001)
            return bus, sleeps

        bus, sleeps = asyncio.run(scenario())
        self.assertEqual([0.001], sleeps)
        self.assertEqual(1, len(bus.sent_raw))
        self.assertTrue(bus.received.empty())

    def test_send_fault_and_connection_transitions_are_explicit(self):
        """Dropped sends time out, while a disconnected transport fails clearly."""

        async def scenario():
            request = EltakoDiscoveryRequest(1)
            bus = VirtualBus(faults=(FaultRule("send", 1, "drop"),))
            bus.queue_response(request, discovery_reply())
            with self.assertRaises(TimeoutError):
                await bus.exchange(request)
            bus.disconnect()
            with self.assertRaises(VirtualBusDisconnected):
                await bus.send(request)
            bus.reconnect()
            await bus.send(request)
            return bus

        bus = asyncio.run(scenario())
        self.assertTrue(bus.connected)
        self.assertEqual(3, len(bus.attempted_raw))
        self.assertEqual(1, len(bus.sent_raw))

    def test_replay_preserves_order_timing_and_recording_format(self):
        """Replay timing is injectable and its JSON representation round-trips."""

        async def scenario():
            sleeps = []

            async def fake_sleep(delay):
                sleeps.append(delay)

            events = (
                ReplayEvent.message(0.0, radio_message(1)),
                ReplayEvent.disconnect(0.25),
                ReplayEvent.reconnect(0.5),
                ReplayEvent.message(0.75, radio_message(2)),
            )
            recording = encode_recording(events, gateway={"type": "virtual"})
            # Prove callers can persist the document without custom encoders.
            restored = decode_recording(json.loads(json.dumps(recording)))
            bus = VirtualBus(sleeper=fake_sleep)
            statuses = []
            bus.set_status_changed_handler(statuses.append)
            delivered = await bus.replay(restored, time_scale=1.0)
            return recording, sleeps, statuses, delivered

        recording, sleeps, statuses, delivered = asyncio.run(scenario())
        self.assertEqual("eltako14bus.virtual-bus", recording["format"])
        self.assertEqual([0.25, 0.25, 0.25], sleeps)
        self.assertEqual([True, False, True], statuses)
        self.assertEqual([1, 2], [message.address[-1] for message in delivered])
        self.assertEqual(ReplayAction.MESSAGE.value, recording["events"][0]["action"])

    def test_replay_rejects_events_that_move_backwards_in_time(self):
        """Invalid captures fail early instead of replaying ambiguous ordering."""

        events = (ReplayEvent.message(1.0, radio_message()), ReplayEvent.reconnect(0.5))
        with self.assertRaises(ValueError):
            asyncio.run(VirtualBus().replay(events))

    def test_sixty_concurrent_senders_finish_without_lost_frames(self):
        """Concurrent producers are serialized without deadlock or data loss."""

        async def scenario():
            bus = VirtualBus()
            messages = [radio_message(index) for index in range(1, 61)]
            await asyncio.wait_for(
                asyncio.gather(*(bus.send(message) for message in messages)),
                timeout=1.0,
            )
            return bus, messages

        bus, messages = asyncio.run(scenario())
        self.assertEqual(60, len(bus.sent_raw))
        self.assertEqual(
            [message.serialize() for message in messages],
            bus.sent_raw,
        )


if __name__ == "__main__":
    unittest.main()
