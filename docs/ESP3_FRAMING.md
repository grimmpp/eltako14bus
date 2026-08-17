# Native ESP3 framing

`eltakobus.esp3_frame` is a small dependency-free ESP3 layer. It owns only
the ESP3 wire envelope; it does not replace the legacy ESP3 adapter and does
not open serial connections.

It is useful when a transport supplies raw ESP3 bytes, especially where a
single read can contain noise, part of a frame, or several frames.

```python
from eltakobus.esp3_frame import ESP3FrameParser

parser = ESP3FrameParser()
for chunk in raw_transport_chunks:
    for frame in parser.feed(chunk):
        print(hex(frame.packet_type), frame.data, frame.optional)

for error in parser.errors:
    logger.warning("Ignored malformed ESP3 frame: %s", error)
parser.clear_errors()
```

## Frame model

`ESP3Frame(packet_type, data, optional=b"")` is immutable. `data` and
`optional` are stored exactly as received; `bytes(frame)` or
`frame.to_bytes()` recreates the ESP3 wire frame:

```text
0x55 | data length (2) | optional length | packet type | header CRC8
     | DATA | OPTIONAL_DATA | data CRC8
```

`ESP3Frame.from_bytes()` expects exactly one complete frame and raises an
explicit `ESP3ParseError` variant for missing sync, an invalid length, or a
header/data CRC mismatch. `crc8()` implements ESP3 CRC-8 (polynomial `0x07`,
initial value `0x00`) without a runtime dependency.

## Incremental recovery

`ESP3FrameParser.feed()` returns only complete valid frames. It retains an
incomplete suffix until the next call, ignores bytes before `0x55`, and keeps
parsing frames after corrupted CRCs. Parsing errors are appended to
`parser.errors`, so a receive loop does not terminate because of a bad radio
frame.

The parser is bounded by the ESP3 field widths by default (DATA up to 65,535
bytes and OPTIONAL_DATA up to 255 bytes). Tighter per-transport limits can be
set with `max_data_length` and `max_optional_length`.

## RADIO_ERP1

For packet type `0x01`, `frame.radio_erp1` exposes immutable sections:
`rorg`, `payload`, four-byte `sender`, `status`, and the complete raw
`optional` field. The optional field is intentionally not truncated to seven
bytes, so captures with malformed, vendor-specific, or future data remain
lossless. Use `RadioTelegram.from_esp3_fields(frame.data, frame.optional)`
only when the radio payload and its optional metadata meet that higher-level
model's validation rules.

## Compatibility

This module is opt-in. Existing `eltakobus.esp3.ESP3MessageAdapter`, serial
interfaces, and their callback behavior are unchanged. The adapter now creates
a native packet-shaped result without a third-party dependency. Applications
that still require a concrete legacy `enocean` packet must install that
package themselves and pass an explicit packet factory (or use
`ESP3MessageAdapter.legacy_enocean_packet_factory()`).

The design follows the framing discipline used by the `kipe/enocean` parser:
locate the sync byte, wait for the declared complete frame, verify header and
data CRCs separately, and continue with remaining stream data after an error.
