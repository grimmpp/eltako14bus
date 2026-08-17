"""Safety and concurrency tests for explicit policy-controlled UTE sessions."""

import asyncio
import time
import unittest

import eltakobus
from eltakobus.radio import RadioTelegram
from eltakobus.teach_in_session import (
    UTESessionStatus,
    UTETeachInSession,
)
from eltakobus.ute import (
    UTERequest,
    UTERequestType,
    UTEResponse,
    UTEResponseCode,
)


SENDER = bytes.fromhex("0582f709")
GATEWAY = bytes.fromhex("ffdec801")


def query(control=0x00):
    return RadioTelegram(
        0xD4,
        bytes((control, 1, 0x46, 0, 0x0E, 1, 0xD2)),
        SENDER,
        0,
    )


class FakeTransport:
    def __init__(self):
        self.received = asyncio.Queue()
        self.sent = []

    async def send(self, message):
        self.sent.append(message)


class BlockingSendTransport(FakeTransport):
    def __init__(self):
        super().__init__()
        self.send_started = asyncio.Event()
        self.send_cancelled = False

    async def send(self, message):
        self.send_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.send_cancelled = True
            raise


class TestUTETeachInSession(unittest.TestCase):
    """Prove that acceptance is explicit, bounded and observable."""

    def test_constructing_session_never_consumes_or_accepts_a_query(self):
        async def scenario():
            transport = FakeTransport()
            await transport.received.put(query())
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            await asyncio.sleep(0)
            return transport, session

        transport, session = asyncio.run(scenario())
        self.assertEqual(1, transport.received.qsize())
        self.assertEqual([], transport.sent)
        self.assertTrue(session.unmatched.empty())

    def test_session_exports_are_available_from_package(self):
        self.assertIs(UTETeachInSession, eltakobus.UTETeachInSession)
        self.assertIs(UTESessionStatus, eltakobus.UTESessionStatus)

    def test_explicit_acceptance_sends_one_addressed_response(self):
        async def scenario():
            transport = FakeTransport()
            await transport.received.put(query())
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            request = await session.wait_for_request(timeout=0.1)
            result = await session.respond(
                request, UTEResponseCode.TEACH_IN_ACCEPTED
            )
            return transport, request, result

        transport, request, result = asyncio.run(scenario())
        self.assertTrue(result.sent)
        self.assertEqual(UTESessionStatus.RESPONSE_SENT, result.status)
        self.assertEqual(1, len(transport.sent))
        self.assertEqual(SENDER, transport.sent[0].destination)
        self.assertEqual(
            UTEResponseCode.TEACH_IN_ACCEPTED,
            UTEResponse.from_telegram(transport.sent[0]).response_code,
        )
        self.assertIsInstance(request, UTERequest)

    def test_explicit_policy_can_reject_delete_or_ignore(self):
        async def scenario():
            transport = FakeTransport()
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            await transport.received.put(query(0x10))

            seen = []

            async def reject_delete(request):
                seen.append(request.request_type)
                return UTEResponseCode.NOT_ACCEPTED

            rejected = await session.process_once(
                policy=reject_delete, timeout=0.1
            )
            await transport.received.put(query())
            ignored = await session.process_once(
                policy=lambda request: None, timeout=0.1
            )
            return transport, seen, rejected, ignored

        transport, seen, rejected, ignored = asyncio.run(scenario())
        self.assertEqual([UTERequestType.DELETE], seen)
        self.assertEqual(UTESessionStatus.RESPONSE_SENT, rejected.status)
        self.assertEqual(UTEResponseCode.NOT_ACCEPTED, rejected.decision)
        self.assertEqual(UTESessionStatus.IGNORED, ignored.status)
        self.assertEqual(1, len(transport.sent))

    def test_no_response_query_is_never_transmitted_even_after_decision(self):
        async def scenario():
            transport = FakeTransport()
            await transport.received.put(query(0x40))
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            return transport, await session.process_once(
                policy=lambda request: UTEResponseCode.TEACH_IN_ACCEPTED,
                timeout=0.1,
            )

        transport, result = asyncio.run(scenario())
        self.assertFalse(result.sent)
        self.assertEqual(UTESessionStatus.NO_RESPONSE_REQUIRED, result.status)
        self.assertEqual([], transport.sent)

    def test_unrelated_and_malformed_traffic_is_preserved(self):
        async def scenario():
            transport = FakeTransport()
            unrelated = RadioTelegram(0xF6, b"\x10", bytes(4), 0)
            malformed = RadioTelegram(0xD4, b"\x00", SENDER, 0)
            await transport.received.put(unrelated)
            await transport.received.put(malformed)
            await transport.received.put(query())
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            request = await session.wait_for_request(timeout=0.1)
            preserved = [await session.unmatched.get(), await session.unmatched.get()]
            return session, request, preserved

        session, request, preserved = asyncio.run(scenario())
        self.assertEqual([0xF6, 0xD4], [item.rorg for item in preserved])
        self.assertEqual(1, len(session.parse_errors))
        self.assertEqual(SENDER, request.sender)

    def test_valid_response_is_unmatched_but_not_a_parse_error(self):
        async def scenario():
            transport = FakeTransport()
            response = UTERequest.from_telegram(query()).build_response(
                GATEWAY, UTEResponseCode.NOT_ACCEPTED
            ).to_telegram()
            await transport.received.put(response)
            await transport.received.put(query())
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            request = await session.wait_for_request(timeout=0.1)
            return session, request, await session.unmatched.get()

        session, request, unmatched = asyncio.run(scenario())
        self.assertEqual(SENDER, request.sender)
        self.assertEqual(GATEWAY, unmatched.sender)
        self.assertEqual([], session.parse_errors)

    def test_policy_timeout_and_receive_timeout_send_nothing(self):
        async def scenario():
            transport = FakeTransport()
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            await transport.received.put(query())

            async def blocked_policy(request):
                await asyncio.Event().wait()

            with self.assertRaises(asyncio.TimeoutError):
                await session.process_once(
                    policy=blocked_policy,
                    timeout=0.1,
                    decision_timeout=0.001,
                )
            with self.assertRaises(asyncio.TimeoutError):
                await session.wait_for_request(timeout=0.001)
            return transport

        self.assertEqual([], asyncio.run(scenario()).sent)

    def test_synchronous_policy_is_bounded_without_blocking_the_loop(self):
        async def scenario():
            transport = FakeTransport()
            await transport.received.put(query())
            session = UTETeachInSession(transport, local_sender=GATEWAY)

            def blocked_policy(request):
                time.sleep(0.02)
                return UTEResponseCode.TEACH_IN_ACCEPTED

            with self.assertRaises(asyncio.TimeoutError):
                await session.process_once(
                    policy=blocked_policy,
                    timeout=0.1,
                    decision_timeout=0.001,
                )
            return transport

        transport = asyncio.run(scenario())
        self.assertEqual([], transport.sent)

    def test_cancellation_stops_receive_and_cancellable_send_without_accepting(self):
        async def scenario():
            transport = BlockingSendTransport()
            session = UTETeachInSession(transport, local_sender=GATEWAY)

            receive_task = asyncio.create_task(session.wait_for_request())
            await asyncio.sleep(0)
            receive_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await receive_task

            await transport.received.put(query())
            request = await session.wait_for_request(timeout=0.1)
            send_task = asyncio.create_task(
                session.respond(request, UTEResponseCode.TEACH_IN_ACCEPTED)
            )
            await transport.send_started.wait()
            send_task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await send_task
            return transport

        transport = asyncio.run(scenario())
        self.assertTrue(transport.send_cancelled)
        self.assertEqual([], transport.sent)

    def test_invalid_transport_and_decisions_fail_closed(self):
        with self.assertRaises(TypeError):
            UTETeachInSession(object(), local_sender=GATEWAY)
        with self.assertRaises(TypeError):
            UTETeachInSession(FakeTransport(), local_sender=4)

        async def scenario():
            transport = FakeTransport()
            session = UTETeachInSession(transport, local_sender=GATEWAY)
            request = UTERequest.from_telegram(query())
            with self.assertRaises(TypeError):
                await session.respond(request, True)
            return transport

        self.assertEqual([], asyncio.run(scenario()).sent)


if __name__ == "__main__":
    unittest.main()
