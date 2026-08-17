# Virtual bus, replay, and fault injection

`eltakobus.virtual_bus` provides a deterministic in-process transport for unit
tests and offline examples. It opens no serial device, starts no worker thread,
and is not imported automatically by the existing serial interfaces. Existing
applications therefore keep their current behavior.

## Script request/response traffic

Queue responses before calling the normal asynchronous bus API. Responses for
the same serialized request are consumed in FIFO order.

```python
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest
from eltakobus.virtual_bus import VirtualBus

bus = VirtualBus()
request = EltakoDiscoveryRequest(1)
bus.queue_response(
    request,
    EltakoDiscoveryReply(
        reported_address=1,
        reported_size=1,
        memory_size=127,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    ),
)

reply = await bus.exchange(request, EltakoDiscoveryReply)
```

`VirtualBus` implements `BusInterface`, including inherited helpers such as
`read_mem()`. `attempted_raw` contains every attempted outgoing frame;
`sent_raw` excludes frames removed by a send-side fault.

## Inject and consume unsolicited telegrams

`inject()` parses real ESP2 bytes and puts the prettified message into the
asynchronous `received` queue. It also accepts an ESP2 message object.

```python
await bus.inject(captured_frame_bytes)
message = await bus.received.get()
```

As with the serial transports, `set_callback(callback)` routes future injected
messages to a synchronous callback. `raw_received` contains frames presented
to the parser, while `decode_errors` records checksum or framing failures.

## Replay a capture

Replay events use recording-relative seconds. The default `time_scale=0`
delivers them immediately in the recorded order. Use `time_scale=1` for the
original spacing or `0.5` to run twice as fast.

```python
from eltakobus.virtual_bus import ReplayEvent

events = (
    ReplayEvent.message(0.0, first_frame),
    ReplayEvent.disconnect(0.2),
    ReplayEvent.reconnect(0.4),
    ReplayEvent.message(0.5, second_frame),
)
await bus.replay(events)
```

Events must be ordered by `at`; ambiguous recordings are rejected. The small,
versioned JSON representation is produced by `encode_recording(events,
gateway=...)` and restored with `decode_recording(document)`. Frame bytes are
stored as hexadecimal text. The current format identifier is
`eltako14bus.virtual-bus`, version `1`.

## Deterministic faults

Faults target a 1-based frame occurrence and direction. Send and receive
counters are independent, and no random-number generator is involved.

```python
from eltakobus.virtual_bus import Direction, Fault, FaultRule, VirtualBus

bus = VirtualBus(faults=(
    FaultRule(Direction.RECEIVE, 2, Fault.DROP),
    FaultRule(Direction.RECEIVE, 4, Fault.DUPLICATE),
    FaultRule(Direction.RECEIVE, 6, Fault.CORRUPT_CHECKSUM),
    FaultRule(Direction.RECEIVE, 8, Fault.DISCONNECT),
    FaultRule(Direction.RECEIVE, 9, Fault.RECONNECT),
))
```

- `DROP` removes exactly that frame.
- `DUPLICATE` delivers exactly two copies.
- `CORRUPT_CHECKSUM` changes the final byte; receive-side parsing records the
  resulting `ParseError` without delivering a decoded message.
- `DISCONNECT` changes the connection state before the selected frame, so that
  frame is dropped. Sending while disconnected raises
  `VirtualBusDisconnected`.
- `RECONNECT` restores the connection before the selected frame.

Connection transitions can also be triggered directly with `disconnect()` and
`reconnect()`. `set_status_changed_handler()` observes the initial state and
later transitions.

Scripted exchanges are serialized to model a half-duplex bus. Missing, dropped,
or corrupted scripted responses raise the library `TimeoutError` after the
configured number of attempts. `retries`, `timeout`, and `retry_delay` are
explicit arguments of `exchange()`. Inject a custom asynchronous `sleeper` in
the constructor when a test needs to assert delays without waiting in real
time.

Run the focused suite with:

```console
python -m unittest tests.virtual_bus_test -v
```
