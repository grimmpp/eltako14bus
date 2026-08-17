# Native ESP3 packets and dispatcher

`eltakobus.esp3_packet` adds immutable semantic packet models above the
dependency-free framing API in `eltakobus.esp3_frame`. It supports native
RADIO_ERP1 telegrams, responses, events, commands and lossless unknown packet
types. Unknown response and event codes remain available as integers.

## Packet decoding

```python
from eltakobus.esp3_frame import ESP3Frame
from eltakobus.esp3_packet import ESP3Response, decode_esp3_packet

frame = ESP3Frame.from_bytes(wire_data)
packet = decode_esp3_packet(frame)

if isinstance(packet, ESP3Response):
    print(packet.return_code, packet.data)
```

Framing and semantic decoding intentionally remain separate. A malformed
typed packet raises `ESP3PacketError`; an unknown packet type produces an
`UnknownESP3Packet` and can be serialized without information loss.

## Asynchronous dispatch

`ESP3Dispatcher` expects a frame transport with async `send(frame)` and either
async `receive()` or `received.get()`. Stream transports first feed their
bytes into `ESP3FrameParser` and then expose complete `ESP3Frame` objects.

```python
from eltakobus.esp3_dispatcher import ESP3Dispatcher
from eltakobus.esp3_packet import ESP3Command

async with ESP3Dispatcher(frame_transport) as dispatcher:
    response = await dispatcher.execute(ESP3Command(0x08), timeout=1.0)
    telegram = await dispatcher.receive_radio()
```

ESP3 responses carry no general transaction identifier. The command client
therefore permits only one outstanding response-bearing command per
dispatcher. Concurrent callers wait in order while radio telegrams, events,
unknown packets and unsolicited responses continue to their own queues.

The public queues are:

- `packets`: unsolicited successfully decoded packets
- `radio`: RADIO_ERP1 `RadioTelegram` objects
- `events`: `ESP3Event` objects
- `responses`: responses received without an active command
- `unknown`: lossless `UnknownESP3Packet` objects
- `errors`: recoverable `(frame, ESP3PacketError)` pairs

`diagnostics` returns immutable routing counters. Closing the dispatcher or a
transport receive failure immediately fails an active command. A timeout
raises `ESP3CommandTimeout` and bounds both `send()` and response waiting. A
later response is treated as unsolicited and cannot satisfy a subsequent
command. The `receive_packet()`, `receive_radio()` and `receive_event()`
helpers also wake with the transport or close error instead of waiting after
the receive loop has terminated.

## Compatibility and scope

This milestone does not modify legacy ESP2 classes, serial interfaces or
`ESP3MessageAdapter`. The native packet and dispatcher names are exported by
their modules and by the integrated `eltakobus` package namespace. Existing
callers continue to work unchanged. The dispatcher owns semantic routing
only; serial reconnect policy and raw ESP3 stream parsing remain transport
responsibilities.
