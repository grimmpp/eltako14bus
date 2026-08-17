"""Safe, explicit memory read and write sessions for Series 14 devices.

The legacy bus and message APIs intentionally remain unchanged.  This module
coordinates their existing ``read_mem()`` and F2/F4 ``exchange()`` primitives
and makes memory writes an opt-in, confirmable operation.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

from .message import EltakoMemoryRequest, EltakoMemoryResponse, EltakoMessage


MEMORY_ROW_SIZE = 8


class MemorySessionError(Exception):
    """Base class for errors raised by the safe memory session layer."""


class MemoryValidationError(MemorySessionError, ValueError):
    """A memory address, snapshot, change, or device response is invalid."""


class MemoryConfirmationError(MemorySessionError):
    """A write was requested without the exact plan confirmation token."""


class MemoryChangedError(MemorySessionError):
    """Device memory changed after the write plan was created."""


class MemoryExecutionError(MemorySessionError):
    """A write or verification failed; ``result`` describes recovery."""

    def __init__(self, message: str, result: "MemorySessionResult") -> None:
        super().__init__(message)
        self.result = result


class MemorySessionStatus(str, Enum):
    """Terminal state of one memory session operation."""

    DRY_RUN = "dry_run"
    NO_CHANGES = "no_changes"
    APPLIED = "applied"
    CANCELLED = "cancelled"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """Immutable complete memory image returned by ``BusInterface.read_mem``."""

    address: int
    rows: tuple[bytes, ...]

    def row(self, index: int) -> bytes:
        """Return one row while retaining normal tuple bounds behavior."""

        return self.rows[index]


@dataclass(frozen=True, slots=True)
class MemoryChange:
    """One validated row transition in a memory write plan."""

    row: int
    before: bytes
    after: bytes


@dataclass(frozen=True, slots=True)
class MemoryPlan:
    """Immutable, reviewable plan created from a device snapshot."""

    snapshot: MemorySnapshot
    changes: tuple[MemoryChange, ...]
    confirmation_token: str

    @property
    def address(self) -> int:
        return self.snapshot.address

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

    @property
    def rollback_changes(self) -> tuple[MemoryChange, ...]:
        """Return inverse changes in the order needed for restoration."""

        return tuple(
            MemoryChange(change.row, change.after, change.before)
            for change in reversed(self.changes)
        )


@dataclass(frozen=True, slots=True)
class MemorySessionResult:
    """Structured audit record for dry-run, success, cancellation, or failure."""

    status: MemorySessionStatus
    plan: MemoryPlan
    attempted_rows: tuple[int, ...] = ()
    written_rows: tuple[int, ...] = ()
    verified_rows: tuple[int, ...] = ()
    restored_rows: tuple[int, ...] = ()
    rollback_errors: tuple[str, ...] = ()
    error: Optional[str] = None

    @property
    def wrote(self) -> bool:
        """Whether at least one write received a valid F4 response."""

        return bool(self.written_rows)

    @property
    def rollback_complete(self) -> bool:
        """Whether every attempted row was restored without a reported error."""

        return (
            bool(self.attempted_rows)
            and not self.rollback_errors
            and set(self.restored_rows) == set(self.attempted_rows)
        )


MemoryValidator = Callable[[int, bytes, bytes], Any]


class _SessionCancellation(Exception):
    pass


class MemorySession:
    """Plan and execute safe memory operations without changing ``BusInterface``.

    Constructing a session and calling :meth:`read`, :meth:`plan`, or
    :meth:`execute` with its defaults never writes.  A real write requires both
    ``allow_write=True`` and the confirmation token from the exact immutable
    plan.  The device is read again before writing so that a stale plan cannot
    overwrite intervening changes.
    """

    def __init__(
        self,
        bus: Any,
        address: int,
        *,
        known_memory_size: Optional[int] = None,
        validator: Optional[MemoryValidator] = None,
    ) -> None:
        if not callable(getattr(bus, "read_mem", None)):
            raise TypeError("bus must provide async read_mem(address, ...)")
        if not callable(getattr(bus, "exchange", None)):
            raise TypeError("bus must provide async exchange(request, ...)")
        self.address = _validate_byte("address", address)
        if known_memory_size is not None:
            self.known_memory_size = _validate_byte(
                "known_memory_size", known_memory_size
            )
        else:
            self.known_memory_size = None
        if validator is not None and not callable(validator):
            raise TypeError("validator must be callable")
        self.bus = bus
        self.validator = validator
        self._operation_lock = asyncio.Lock()

    async def read(self) -> MemorySnapshot:
        """Read and validate a complete immutable memory snapshot."""

        if self.known_memory_size is None:
            result = self.bus.read_mem(self.address)
        else:
            result = self.bus.read_mem(
                self.address, known_memory_size=self.known_memory_size
            )
        if not inspect.isawaitable(result):
            raise TypeError("bus.read_mem() must be async")
        rows = await result
        try:
            normalized = tuple(_normalize_row(value) for value in rows)
        except TypeError as exc:
            raise MemoryValidationError("read_mem() must return an iterable") from exc
        if self.known_memory_size is not None:
            expected = self.known_memory_size + 1
            if len(normalized) != expected:
                raise MemoryValidationError(
                    "read_mem() returned %d rows, expected %d"
                    % (len(normalized), expected)
                )
        if len(normalized) > 256:
            raise MemoryValidationError("device memory cannot exceed 256 rows")
        return MemorySnapshot(self.address, normalized)

    async def plan(self, changes: Mapping[int, Any]) -> MemoryPlan:
        """Read memory and create a validated plan without writing anything."""

        if not isinstance(changes, Mapping):
            raise TypeError("changes must be a mapping of row numbers to bytes")
        snapshot = await self.read()
        planned: list[MemoryChange] = []
        for row in changes:
            if isinstance(row, bool) or not isinstance(row, int):
                raise MemoryValidationError("memory row must be an integer")
        for row, requested in sorted(changes.items()):
            if row < 0 or row >= len(snapshot.rows):
                raise MemoryValidationError(
                    "memory row %r is outside snapshot range 0..%d"
                    % (row, len(snapshot.rows) - 1)
                )
            after = _normalize_row(requested)
            before = snapshot.rows[row]
            if self.validator is not None:
                validation = self.validator(row, before, after)
                if inspect.isawaitable(validation):
                    validation = await validation
                if validation is False:
                    raise MemoryValidationError(
                        "validator rejected memory row %d" % row
                    )
            if after != before:
                planned.append(MemoryChange(row, before, after))
        changes_tuple = tuple(planned)
        token = _plan_token(snapshot, changes_tuple)
        return MemoryPlan(snapshot, changes_tuple, token)

    async def execute(
        self,
        plan: MemoryPlan,
        *,
        allow_write: bool = False,
        confirmation: Optional[str] = None,
        verify: bool = True,
        rollback: bool = True,
        cancel_event: Optional[asyncio.Event] = None,
    ) -> MemorySessionResult:
        """Dry-run by default, or explicitly apply and verify a confirmed plan.

        ``cancel_event`` provides cooperative cancellation with a structured
        result.  Native task cancellation is re-raised after a shielded,
        best-effort restore of every row whose write may have started.
        """

        self._validate_plan(plan)
        if (
            not isinstance(allow_write, bool)
            or not isinstance(verify, bool)
            or not isinstance(rollback, bool)
        ):
            raise TypeError("allow_write, verify and rollback must be booleans")
        if cancel_event is not None and not isinstance(cancel_event, asyncio.Event):
            raise TypeError("cancel_event must be an asyncio.Event")
        if not plan.has_changes:
            return MemorySessionResult(MemorySessionStatus.NO_CHANGES, plan)
        if not allow_write:
            return MemorySessionResult(MemorySessionStatus.DRY_RUN, plan)
        if confirmation != plan.confirmation_token:
            raise MemoryConfirmationError(
                "write requires the confirmation token from the exact plan"
            )

        async with self._operation_lock:
            attempted: list[MemoryChange] = []
            written: list[int] = []
            verified: list[int] = []
            try:
                self._raise_if_cancelled(cancel_event)
                current = await self.read()
                for change in plan.changes:
                    if current.rows[change.row] != change.before:
                        raise MemoryChangedError(
                            "memory row %d changed after the plan was created"
                            % change.row
                        )

                for change in plan.changes:
                    self._raise_if_cancelled(cancel_event)
                    # Include the row before awaiting I/O: cancellation can
                    # make the write outcome uncertain even without a reply.
                    attempted.append(change)
                    await self._write_row(change.row, change.after)
                    written.append(change.row)
                    if verify:
                        observed = await self._read_row(change.row)
                        if observed != change.after:
                            raise MemoryValidationError(
                                "verification failed for memory row %d" % change.row
                            )
                        verified.append(change.row)
                return MemorySessionResult(
                    MemorySessionStatus.APPLIED,
                    plan,
                    attempted_rows=tuple(change.row for change in attempted),
                    written_rows=tuple(written),
                    verified_rows=tuple(verified),
                )
            except _SessionCancellation as exc:
                restored, rollback_errors = await self._restore(attempted, rollback)
                return MemorySessionResult(
                    MemorySessionStatus.CANCELLED,
                    plan,
                    attempted_rows=tuple(change.row for change in attempted),
                    written_rows=tuple(written),
                    verified_rows=tuple(verified),
                    restored_rows=restored,
                    rollback_errors=rollback_errors,
                    error=str(exc),
                )
            except asyncio.CancelledError:
                # A second cancellation may still interrupt this shield.  The
                # restore task remains scheduled in that case, which is the
                # strongest guarantee possible without owning the transport.
                restore_task = asyncio.create_task(self._restore(attempted, rollback))
                await asyncio.shield(restore_task)
                raise
            except Exception as exc:
                restored, rollback_errors = await self._restore(attempted, rollback)
                result = MemorySessionResult(
                    MemorySessionStatus.FAILED,
                    plan,
                    attempted_rows=tuple(change.row for change in attempted),
                    written_rows=tuple(written),
                    verified_rows=tuple(verified),
                    restored_rows=restored,
                    rollback_errors=rollback_errors,
                    error="%s: %s" % (type(exc).__name__, exc),
                )
                raise MemoryExecutionError("memory write failed", result) from exc

    def _validate_plan(self, plan: MemoryPlan) -> None:
        if not isinstance(plan, MemoryPlan):
            raise TypeError("plan must be a MemoryPlan")
        if plan.address != self.address:
            raise MemoryValidationError("plan belongs to another device address")
        if plan.confirmation_token != _plan_token(plan.snapshot, plan.changes):
            raise MemoryValidationError("plan contents do not match its confirmation token")

    @staticmethod
    def _raise_if_cancelled(cancel_event: Optional[asyncio.Event]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise _SessionCancellation("memory operation was cancelled")

    async def _read_row(self, row: int) -> bytes:
        response = await self.bus.exchange(
            EltakoMemoryRequest(self.address, row), EltakoMemoryResponse
        )
        if not isinstance(response, EltakoMemoryResponse):
            raise MemoryValidationError("memory read returned an unexpected response")
        if response.row != row:
            raise MemoryValidationError(
                "memory read returned row %d, expected %d" % (response.row, row)
            )
        return _normalize_row(response.value)

    async def _write_row(self, row: int, value: bytes) -> None:
        select_response = await self.bus.exchange(EltakoMessage(0xF2, self.address))
        if getattr(select_response, "org", None) != 0xF2:
            raise MemoryValidationError("device selection did not return an F2 response")
        write_response = await self.bus.exchange(EltakoMessage(0xF4, row, value))
        if getattr(write_response, "org", None) != 0xF4:
            raise MemoryValidationError("memory write did not return an F4 response")

    async def _restore(
        self, attempted: list[MemoryChange], enabled: bool
    ) -> tuple[tuple[int, ...], tuple[str, ...]]:
        if not enabled or not attempted:
            return (), ()
        restored: list[int] = []
        errors: list[str] = []
        for change in reversed(attempted):
            try:
                await self._write_row(change.row, change.before)
                observed = await self._read_row(change.row)
                if observed != change.before:
                    raise MemoryValidationError(
                        "restore verification failed for memory row %d" % change.row
                    )
                restored.append(change.row)
            except Exception as exc:
                errors.append(
                    "row %d: %s: %s" % (change.row, type(exc).__name__, exc)
                )
        return tuple(restored), tuple(errors)


def _validate_byte(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if value < 0 or value > 0xFF:
        raise ValueError("%s must be between 0 and 255" % name)
    return value


def _normalize_row(value: Any) -> bytes:
    if isinstance(value, (str, int)):
        raise MemoryValidationError("memory row must be bytes-like")
    try:
        normalized = bytes(value)
    except (TypeError, ValueError) as exc:
        raise MemoryValidationError("memory row must be bytes-like") from exc
    if len(normalized) != MEMORY_ROW_SIZE:
        raise MemoryValidationError(
            "memory row must contain exactly %d bytes" % MEMORY_ROW_SIZE
        )
    return normalized


def _plan_token(snapshot: MemorySnapshot, changes: tuple[MemoryChange, ...]) -> str:
    digest = hashlib.sha256()
    digest.update(bytes((snapshot.address,)))
    digest.update(len(snapshot.rows).to_bytes(2, "big"))
    for row in snapshot.rows:
        digest.update(row)
    for change in changes:
        digest.update(bytes((change.row,)))
        digest.update(change.before)
        digest.update(change.after)
    return digest.hexdigest()[:16]


__all__ = [
    "MEMORY_ROW_SIZE",
    "MemoryChange",
    "MemoryChangedError",
    "MemoryConfirmationError",
    "MemoryExecutionError",
    "MemoryPlan",
    "MemorySession",
    "MemorySessionError",
    "MemorySessionResult",
    "MemorySessionStatus",
    "MemorySnapshot",
    "MemoryValidationError",
]
