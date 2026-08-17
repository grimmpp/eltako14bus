"""Regression tests found during the post-integration refactoring checkpoint.

These tests deliberately cover public seams, not private implementation
details.  They protect the safe-memory confirmation boundary and the
additive package-level exports while a later, separately versioned cleanup
can make the public namespace explicit.
"""

import asyncio
from dataclasses import replace
import unittest

import eltakobus
from eltakobus.memory_session import MemorySession, MemoryValidationError


def _row(value):
    return bytes((value,)) * 8


class _MemoryBus:
    """Minimal unchanged bus contract; no real hardware is accessed."""

    def __init__(self):
        self.rows = [_row(0), _row(1)]
        self.exchange_calls = 0

    async def read_mem(self, address, known_memory_size=None):
        return tuple(self.rows)

    async def exchange(self, request, responsetype=None):  # pragma: no cover
        self.exchange_calls += 1
        raise AssertionError("a rejected plan must not access the bus")


class RefactoringCheckpointTest(unittest.TestCase):
    """Keep reviewed compatibility and safety boundaries stable."""

    def test_additive_root_exports_reference_the_canonical_core_objects(self):
        """The current convenience exports must not create wrapper APIs."""
        from eltakobus.diagnostic_snapshot import snapshot_gateway
        from eltakobus.eep_schema import D2_00_01_SCHEMA
        from eltakobus.memory_session import MemorySession as DirectSession

        self.assertIs(DirectSession, eltakobus.MemorySession)
        self.assertIs(D2_00_01_SCHEMA, eltakobus.D2_00_01_SCHEMA)
        self.assertIs(snapshot_gateway, eltakobus.snapshot_gateway)

    def test_modified_memory_plan_is_rejected_before_write_io(self):
        """The confirmation token binds the address, snapshot and row changes."""
        async def scenario():
            bus = _MemoryBus()
            session = MemorySession(bus, address=5)
            plan = await session.plan({1: _row(9)})
            tampered = replace(plan, changes=())
            with self.assertRaises(MemoryValidationError):
                await session.execute(
                    tampered,
                    allow_write=True,
                    confirmation=plan.confirmation_token,
                )
            return bus

        bus = asyncio.run(scenario())
        self.assertEqual(0, bus.exchange_calls)


if __name__ == "__main__":
    unittest.main()
