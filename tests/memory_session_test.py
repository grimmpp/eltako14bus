"""Safety tests for explicit, hardware-independent memory sessions.

The fake bus implements the existing ``read_mem``/``exchange`` contract.  It
proves that planning and default execution are read-only, while confirmed
writes are verified and partial failures are restored where possible.
"""

import asyncio
import unittest

from eltakobus.memory_session import (
    MemoryChangedError,
    MemoryConfirmationError,
    MemoryExecutionError,
    MemorySession,
    MemorySessionStatus,
    MemoryValidationError,
)
from eltakobus.message import EltakoMemoryRequest, EltakoMemoryResponse, EltakoMessage


def row(value):
    return bytes((value,)) * 8


class FakeMemoryBus:
    """Mutable in-memory implementation of the unchanged legacy primitives."""

    def __init__(self, rows=(row(0), row(1), row(2))):
        self.rows = list(rows)
        self.exchanges = []
        self.selected = None
        self.fail_write_row = None
        self.corrupt_write_row = None
        self.after_write = None

    async def read_mem(self, address, known_memory_size=None):
        if known_memory_size is not None:
            return tuple(self.rows[: known_memory_size + 1])
        return tuple(self.rows)

    async def exchange(self, request, responsetype=None):
        self.exchanges.append(request)
        if isinstance(request, EltakoMemoryRequest):
            return EltakoMemoryResponse(request.row, self.rows[request.row])
        if isinstance(request, EltakoMessage) and request.org == 0xF2:
            self.selected = request.address
            return EltakoMessage(0xF2, request.address, is_request=False)
        if isinstance(request, EltakoMessage) and request.org == 0xF4:
            if self.selected is None:
                raise RuntimeError("device was not selected")
            if request.address == self.fail_write_row:
                raise RuntimeError("simulated write failure")
            if request.address != self.corrupt_write_row:
                self.rows[request.address] = bytes(request.payload)
            self.selected = None
            if self.after_write is not None:
                await self.after_write(request.address)
            return EltakoMessage(0xF4, request.address, is_request=False)
        raise AssertionError("unexpected exchange")


class TestMemorySession(unittest.TestCase):
    """Verify safe defaults, validation, confirmation and recovery semantics."""

    def test_planning_and_default_execution_never_write(self):
        async def scenario():
            bus = FakeMemoryBus()
            session = MemorySession(bus, 5, known_memory_size=2)
            plan = await session.plan({1: row(9)})
            result = await session.execute(plan)
            return bus, plan, result

        bus, plan, result = asyncio.run(scenario())
        self.assertEqual(MemorySessionStatus.DRY_RUN, result.status)
        self.assertEqual((1,), tuple(change.row for change in plan.changes))
        self.assertEqual(row(1), plan.changes[0].before)
        self.assertEqual(row(9), plan.changes[0].after)
        self.assertEqual([row(0), row(1), row(2)], bus.rows)
        self.assertEqual([], bus.exchanges)

    def test_no_change_plan_is_reported_without_confirmation(self):
        async def scenario():
            session = MemorySession(FakeMemoryBus(), 5)
            plan = await session.plan({1: row(1)})
            return plan, await session.execute(plan, allow_write=True)

        plan, result = asyncio.run(scenario())
        self.assertFalse(plan.has_changes)
        self.assertEqual(MemorySessionStatus.NO_CHANGES, result.status)

    def test_write_requires_matching_confirmation_before_bus_io(self):
        async def scenario():
            bus = FakeMemoryBus()
            session = MemorySession(bus, 5)
            plan = await session.plan({0: row(8)})
            with self.assertRaises(MemoryConfirmationError):
                await session.execute(plan, allow_write=True, confirmation="wrong")
            return bus

        bus = asyncio.run(scenario())
        self.assertEqual([], bus.exchanges)
        self.assertEqual(row(0), bus.rows[0])

    def test_plan_cannot_be_reused_for_a_different_device_address(self):
        """An exact plan is still rejected before I/O for another address."""
        async def scenario():
            original_bus = FakeMemoryBus()
            plan = await MemorySession(original_bus, 5).plan({0: row(8)})
            other_bus = FakeMemoryBus()
            with self.assertRaises(MemoryValidationError):
                await MemorySession(other_bus, 6).execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            return original_bus, other_bus

        original_bus, other_bus = asyncio.run(scenario())
        self.assertEqual([], original_bus.exchanges)
        self.assertEqual([], other_bus.exchanges)
        self.assertEqual(row(0), other_bus.rows[0])

    def test_confirmed_write_is_selected_written_and_verified(self):
        async def scenario():
            bus = FakeMemoryBus()
            session = MemorySession(bus, 7)
            plan = await session.plan({0: row(8), 2: row(9)})
            result = await session.execute(
                plan,
                allow_write=True,
                confirmation=plan.confirmation_token,
            )
            return bus, result

        bus, result = asyncio.run(scenario())
        self.assertEqual(MemorySessionStatus.APPLIED, result.status)
        self.assertEqual((0, 2), result.written_rows)
        self.assertEqual((0, 2), result.verified_rows)
        self.assertEqual([row(8), row(1), row(9)], bus.rows)
        self.assertEqual([0xF2, 0xF4, 0xF1, 0xF2, 0xF4, 0xF1], [m.org for m in bus.exchanges])

    def test_stale_plan_is_rejected_before_any_write(self):
        async def scenario():
            bus = FakeMemoryBus()
            session = MemorySession(bus, 5)
            plan = await session.plan({1: row(9)})
            bus.rows[1] = row(7)
            with self.assertRaises(MemoryExecutionError) as caught:
                await session.execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            return bus, caught.exception

        bus, error = asyncio.run(scenario())
        self.assertIsInstance(error.__cause__, MemoryChangedError)
        self.assertEqual((), error.result.attempted_rows)
        self.assertEqual([], bus.exchanges)
        self.assertEqual(row(7), bus.rows[1])

    def test_partial_failure_restores_successful_and_uncertain_rows(self):
        async def scenario():
            bus = FakeMemoryBus()
            bus.fail_write_row = 2
            session = MemorySession(bus, 5)
            plan = await session.plan({0: row(8), 2: row(9)})
            with self.assertRaises(MemoryExecutionError) as caught:
                await session.execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            return bus, caught.exception.result

        bus, result = asyncio.run(scenario())
        self.assertEqual(MemorySessionStatus.FAILED, result.status)
        self.assertEqual((0, 2), result.attempted_rows)
        self.assertEqual((0,), result.written_rows)
        # Row 2 keeps failing during rollback; row 0 is still restored.
        self.assertEqual((0,), result.restored_rows)
        self.assertEqual(1, len(result.rollback_errors))
        self.assertEqual(row(0), bus.rows[0])

    def test_verification_failure_restores_original_value(self):
        async def scenario():
            bus = FakeMemoryBus()
            bus.corrupt_write_row = 1
            session = MemorySession(bus, 5)
            plan = await session.plan({1: row(9)})
            with self.assertRaises(MemoryExecutionError) as caught:
                await session.execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            return bus, caught.exception.result

        bus, result = asyncio.run(scenario())
        self.assertEqual((1,), result.written_rows)
        self.assertEqual((1,), result.restored_rows)
        self.assertTrue(result.rollback_complete)
        self.assertEqual(row(1), bus.rows[1])

    def test_cooperative_cancellation_restores_prior_rows(self):
        async def scenario():
            bus = FakeMemoryBus()
            cancelled = asyncio.Event()

            async def cancel_after_first(written_row):
                if written_row == 0:
                    cancelled.set()

            bus.after_write = cancel_after_first
            session = MemorySession(bus, 5)
            plan = await session.plan({0: row(8), 2: row(9)})
            result = await session.execute(
                plan,
                allow_write=True,
                confirmation=plan.confirmation_token,
                cancel_event=cancelled,
            )
            return bus, result

        bus, result = asyncio.run(scenario())
        self.assertEqual(MemorySessionStatus.CANCELLED, result.status)
        self.assertEqual((0,), result.attempted_rows)
        self.assertEqual((0,), result.restored_rows)
        self.assertEqual(row(0), bus.rows[0])
        self.assertEqual(row(2), bus.rows[2])

    def test_task_cancellation_is_propagated_after_best_effort_restore(self):
        async def scenario():
            bus = FakeMemoryBus()
            write_started = asyncio.Event()
            block_once = True

            async def block_first_write(written_row):
                nonlocal block_once
                if block_once:
                    block_once = False
                    write_started.set()
                    await asyncio.Event().wait()

            bus.after_write = block_first_write
            session = MemorySession(bus, 5)
            plan = await session.plan({0: row(8)})
            operation = asyncio.create_task(
                session.execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            )
            await write_started.wait()
            operation.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await operation
            return bus

        bus = asyncio.run(scenario())
        self.assertEqual(row(0), bus.rows[0])

    def test_validation_rejects_bad_rows_and_custom_policy(self):
        async def scenario():
            session = MemorySession(
                FakeMemoryBus(),
                5,
                validator=lambda index, before, after: index != 1,
            )
            with self.assertRaises(MemoryValidationError):
                await session.plan({3: row(9)})
            with self.assertRaises(MemoryValidationError):
                await session.plan({0: b"short"})
            with self.assertRaises(MemoryValidationError):
                await session.plan({1: row(9)})

        asyncio.run(scenario())

    def test_rollback_can_be_explicitly_disabled(self):
        async def scenario():
            bus = FakeMemoryBus()
            bus.fail_write_row = 2
            session = MemorySession(bus, 5)
            plan = await session.plan({0: row(8), 2: row(9)})
            with self.assertRaises(MemoryExecutionError) as caught:
                await session.execute(
                    plan,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                    rollback=False,
                )
            return bus, caught.exception.result

        bus, result = asyncio.run(scenario())
        self.assertEqual((), result.restored_rows)
        self.assertEqual(row(8), bus.rows[0])


if __name__ == "__main__":
    unittest.main()
