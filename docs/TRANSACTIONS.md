# Transactions

`eltakobus.transactions` adds an opt-in request/response layer without
changing existing serial, TCP, or `BusInterface.exchange()` behavior.  It is
intended for new transports that expose:

```python
async def send(request) -> None: ...
async def receive() -> object: ...
```

Instead of `receive()`, a transport may expose `received`, an `asyncio.Queue`
whose `get()` method returns the next decoded message.  `VirtualBus` already
provides this shape, which makes it appropriate for offline tests.

## Basic use

```python
from eltakobus.transactions import TransactionManager, TransactionOptions

async with TransactionManager(transport) as transactions:
    result = await transactions.request(
        request,
        matcher=lambda message: (
            isinstance(message, ExpectedReply)
            and message.address == request.address
        ),
        options=TransactionOptions(timeout=1.0, retries=2, retry_delay=0.1),
    )

print(result.response)
print(result.metrics.attempts, result.metrics.retries, result.metrics.elapsed)
```

`retries` means additional attempts after the initial send, so the example can
send at most three times.  `timeout` applies to each individual attempt.
`elapsed` uses `time.monotonic()` and is safe for measurements even if the
system clock changes.

## Matching and passive telegrams

Each request supplies its own `matcher`.  The manager owns one receive
dispatcher and gives a received message to the oldest pending request whose
matcher accepts it.  This avoids the legacy pattern of clearing a shared
receive queue before a command.

Messages that do not match any pending request are never discarded.  They are
available through `transactions.unmatched`; optionally they can be observed as
they arrive:

```python
def on_passive_message(message):
    print("received unrelated telegram", message)

transactions = TransactionManager(
    transport,
    unmatched_callback=on_passive_message,
)
```

Supply `unmatched_queue=your_queue` when the application owns the passive
message queue.  The callback may be synchronous or async.

## Rejections, timeout, and cancellation

Use `rejecter` for a request-specific negative response:

```python
result = await transactions.request(
    request,
    matcher=is_expected_confirmation,
    rejecter=is_explicit_protocol_rejection,
)
```

The module raises these explicit errors from `eltakobus.error`:

| Error | Meaning |
| --- | --- |
| `CommandTimeout` | All bounded attempts timed out.  Its `metrics` attribute records attempts and elapsed time. |
| `CommandRejected` | `rejecter` accepted an incoming response.  Its `response` attribute contains that response. |
| `UnsupportedCommand` | The supplied transport cannot provide the required async contract or declines a command. |
| `TransactionCancelled` | The waiting task was cancelled or the manager was closed. |

When a caller cancels a request, its waiter is removed before
`TransactionCancelled` is raised.  A response arriving afterward is forwarded
as an unmatched message and cannot be mistaken for a later request.

## Scope and compatibility

This is deliberately a new API.  It does not alter `BusInterface.exchange()`,
`RS485SerialInterfaceV2`, or the ESP2 gateway transports.  Adapting those
transports to a dispatcher-backed receive stream is a separate v2 step.
