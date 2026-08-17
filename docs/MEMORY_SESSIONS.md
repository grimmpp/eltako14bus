# Safe memory sessions

`eltakobus.memory_session` provides a hardware-independent safety layer around
the existing `BusInterface.read_mem()` and F2/F4 `exchange()` primitives. It
does not change the bus, device, or message APIs and performs no background
work.

Memory changes can alter an actuator's configuration. Creating a session,
reading memory, planning changes, and executing with default arguments are all
read-only. A write requires two independent opt-ins:

1. `allow_write=True`;
2. the confirmation token generated for the exact immutable plan.

## Read and dry-run

```python
from eltakobus.memory_session import MemorySession

session = MemorySession(bus, address=5, known_memory_size=127)
snapshot = await session.read()

plan = await session.plan({
    12: bytes.fromhex("0102030405060708"),
})

# This is the default and never writes.
result = await session.execute(plan)
assert result.status.value == "dry_run"

for change in plan.changes:
    print(change.row, change.before.hex(), "->", change.after.hex())
print("confirmation:", plan.confirmation_token)
```

`known_memory_size` follows the historical `read_mem` convention: it is the
highest row number, so `127` reads rows 0 through 127. Every memory row is
validated as exactly eight bytes.

## Confirmed write

Only pass the token after the plan has been displayed and approved by the user
or maintenance workflow:

```python
result = await session.execute(
    plan,
    allow_write=True,
    confirmation=plan.confirmation_token,
)
```

Immediately before the first write, the session reads memory again and compares
all affected rows with the snapshot. It rejects a stale plan rather than
overwriting another client's changes. For each row, it then:

1. selects the device using the existing F2 exchange;
2. writes the eight-byte row using the existing F4 exchange;
3. reads the row back using F1 and verifies its value.

The result is an immutable diagnostic record containing attempted, written,
verified, and restored row numbers. No sensitive memory content is included in
its error strings; the reviewed values remain available in the plan.

## Validation policy

Applications can reject device- or row-specific values before confirmation:

```python
def validate(row, before, after):
    # Protect a device-specific calibration row.
    return row != 0x5D

session = MemorySession(bus, 5, validator=validate)
plan = await session.plan(changes)
```

The validator may be synchronous or asynchronous. Returning exactly `False`
rejects a row with `MemoryValidationError`; it may also raise a more specific
application exception.

## Cancellation and restore

Cooperative cancellation returns a structured result and restores every row
whose write may have started:

```python
cancel = asyncio.Event()
result = await session.execute(
    plan,
    allow_write=True,
    confirmation=plan.confirmation_token,
    cancel_event=cancel,
)
```

Normal asyncio task cancellation is propagated to the caller after a shielded,
best-effort restore. A write or verification failure raises
`MemoryExecutionError`; its `result` attribute documents restored rows and any
rollback errors:

```python
try:
    await session.execute(
        plan,
        allow_write=True,
        confirmation=plan.confirmation_token,
    )
except MemoryExecutionError as error:
    log.error("memory operation: %s", error.result)
```

Rollback is enabled by default and restores rows in reverse order. It can only
be best effort: a disconnected bus, an unresponsive device, or device-internal
side effects may prevent restoration. `rollback=False` is available for devices
where rewriting a previous row is known to be unsafe, but choosing it makes a
partial configuration persistent after failure.

## Concurrency and compatibility

One session serializes its own executions. Applications must still ensure that
only one component owns command/response exchanges on the physical half-duplex
bus. The session deliberately uses the same `EltakoMessage`,
`EltakoMemoryRequest`, and `EltakoMemoryResponse` classes as existing code, so
serial, TCP, virtual, cached, and custom `BusInterface` implementations remain
compatible without modification.

The confirmation token protects the immutable snapshot and requested changes;
it is not an authorization credential and it does not identify a physical
gateway. Do not transfer a plan or its token to another process, transport or
installation. Create and confirm a new plan from that transport's current
memory image instead. A plan is always rejected for a session with a different
device address before any bus I/O.

The session does not update a `BusObject.memory` cache. Existing device objects
should be refreshed after a successful write. It also does not infer which rows
are safe for a particular actuator; that policy belongs in the caller-provided
validator or a future device-specific schema.
