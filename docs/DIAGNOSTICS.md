# Structured diagnostics

`eltakobus.diagnostic_snapshot` creates immutable, JSON-serializable views of
parser, transport and gateway state. It is intended for logs, support bundles,
command-line tools and monitoring integrations. It has no Home Assistant or
optional serial dependency.

Taking a snapshot is passive. It does not open a device, transmit a telegram,
drain a queue, clear parser errors or change reconnect behavior.

## Parser metrics

```python
from eltakobus.diagnostic_snapshot import snapshot_parser

snapshot = snapshot_parser(frame_parser)
print(snapshot.buffered_bytes, snapshot.discarded_bytes)
print(snapshot.error_counts)
print(snapshot.to_json(indent=2))
```

The parser snapshot contains the protocol and parser type, number and hex form
of buffered bytes, discarded stream bytes, retained recoverable errors and an
error count grouped by exception type. Error text is diagnostic information;
applications should use `error_type` for stable grouping.

Both `ESP2FrameParser` and `ESP3FrameParser` are supported through their
existing `buffered_bytes`, `discarded_bytes`, `errors` and `max_errors` APIs.
The retained error list is copied and remains available on the parser.

## Transport metrics

```python
from eltakobus.diagnostic_snapshot import snapshot_transport

snapshot = snapshot_transport(bus)
print(snapshot.active, snapshot.endpoint)
for queue in snapshot.queues:
    print(queue.name, queue.depth)
```

Transport snapshots normalize the transport class, active and worker state,
serial filename or TCP endpoint, automatic reconnect setting, queue depths and
embedded frame-parser state. If the transport was constructed with an
opt-in `TransportMetrics` collector, its immutable metrics snapshot is exposed
as `snapshot.metrics`; otherwise that field is `None`. A value is `None` when
a transport does not expose that metric. This keeps the API compatible with the legacy asyncio ESP2
transport, the threaded ESP2 serial transport and ESP2-over-TCP gateways.

Queue depths are momentary observations. They are useful for health monitoring
but must not be interpreted as transaction acknowledgements.

For cumulative transport telemetry, use the optional, transport-neutral
`TransportMetrics` collector. Existing transports can report successful sends,
receives, retries and connection transitions without changing their public
constructors:

```python
from eltakobus import TransportMetrics

metrics = TransportMetrics(history_limit=32)
metrics.record_message("received")
metrics.record_connection(False, reason="device disappeared")
metrics.record_reconnect_failure()
metrics.record_connection(True, reason="device returned")
print(metrics.snapshot().as_dict())
```

The snapshot contains cumulative average message rates, retry and transaction
counters, plus a bounded reconnect history. Collection is thread-safe,
read-only at snapshot time and does not open hardware. It is deliberately
opt-in so legacy transports retain their timing and behavior.

## Optional transport integration

The three ESP2 transport implementations accept an optional
`metrics=TransportMetrics(...)` keyword:

```python
from eltakobus.transport_metrics import TransportMetrics
from eltakobus.serial import RS485SerialInterfaceV2

metrics = TransportMetrics()
bus = RS485SerialInterfaceV2("/dev/tty.usbserial-AQ028YCS", metrics=metrics)
bus.start()

# Later, from an application diagnostics endpoint:
report = metrics.snapshot().as_dict()
```

The same keyword is available on `RS485SerialInterface` and
`ESP2TCPSerialInterface`. Existing constructors and defaults are unchanged;
`metrics=None` performs no collection. The adapters report only successful
message handoffs: a completed serial/socket write and a parsed message
delivered to the callback or receive queue. Connection transitions and failed
reconnect attempts are recorded separately. Metrics are emitted outside user
callbacks and do not acquire the transport's serial/queue locks, so a slow
application callback cannot be made slower by diagnostics.

This instrumentation is intentionally limited to transport-owned events. It
does not count bytes, parser-discarded frames, expired queue entries or
application-level transaction retries. Use the transaction metrics for the
latter.

## ESP3 dispatcher metrics

`snapshot_dispatcher()` normalizes the immutable counters exposed by
`ESP3Dispatcher.diagnostics` and adds current packet, radio, event, response,
unknown-packet and error queue depths. Unknown packet and decode-error counters
are preserved instead of being hidden.

## Gateway support reports

```python
from eltakobus.diagnostic_snapshot import snapshot_gateway

report = snapshot_gateway(
    bus,
    identity={"device_type": "fam14", "base_id": "FF-AA-00-01"},
    metadata={"site": "workshop"},
)

with open("gateway-diagnostics.json", "w", encoding="utf-8") as output:
    output.write(report.to_json(indent=2))
```

The top-level report includes `schema_version`, an ISO-8601 UTC timestamp,
gateway type, identity data, transport state, optional ESP3 dispatcher metrics
and application metadata. Bytes in identity or metadata values are represented
as lowercase hexadecimal text. The current schema version is `1`.

Applications should treat added dictionary members as backwards-compatible.
A future incompatible representation will increment `schema_version`.

## Privacy and operational safety

Identity and metadata are supplied by the application. Avoid placing secrets,
user names or precise installation locations in reports intended for external
support. A snapshot can reveal gateway endpoints and partial buffered telegram
bytes, but it never includes serial handles, callbacks or message objects.

Structured snapshots complement `probe_devices()` and `read_memory_test()` in
`eltakobus.diagnostics`: those functions actively exercise an already-owned
bus, while snapshot creation is read-only.
