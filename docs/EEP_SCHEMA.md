# Declarative D2 EEP schemas

`eltakobus.eep_schema` is an opt-in migration layer for EEP wire layouts. It
uses the dependency-free MSB-first field engine in `eltakobus.vld` while the
established classes in `eltakobus.eep` remain the public decoding API.

The migration layer is intentionally additive. Existing applications should
continue to use `EEP.find(...)` and `Profile.decode_message(...)`; no return
type, attribute name or EEP registry entry changes as a result of these
schemas.

## Available schemas

| EEP | Schema | Scope |
| --- | --- | --- |
| `D2-00-01` | `D2_00_01_SCHEMA` | Selected message variants A-E, including little-endian and split compound fields |
| `D2-06-01` | `D2_06_01_SCHEMA` | Window-handle multisensor sensor-values message (`message_type == 0`) |
| `D2-14-40` | `D2_14_40_SCHEMA` | Indoor multisensor values |
| `D2-14-41` | `D2_14_41_SCHEMA` | Indoor multisensor values plus contact bit |

Each schema retains raw values and classifies out-of-range values as
`reserved` or `unmapped`. This is more expressive than a plain physical value,
but the legacy decoders continue their established convention of exposing an
invalid physical measurement as `None` and retaining its `*_raw` attribute.

## New-code use

Use a schema only when the wire-level result is useful, for example for a
conformance tool or a vendor-specific extension:

```python
from eltakobus.eep_schema import D2_14_41_SCHEMA

fields = D2_14_41_SCHEMA.decode_message(vld_message)
temperature = fields.value("temperature")
contact = fields.value("contact")
print(fields["humidity"].raw, fields["humidity"].status)
```

Schemas decode their documented prefix and accept longer VLD payloads. This
matches the existing D2 decoders and avoids rejecting forward-compatible
vendor extensions.

The D2-06-01 schema is restricted to its implemented sensor-values variant
(`message_type == 0`) and raises `eltakobus.error.NotImplementedError` for
other message types, matching `D2_06_01.decode_message(...)`. Schema payloads
must be bytes-like; passing an integer is rejected rather than interpreting it
as a number of zero bytes.

## Compatibility adapter

The adapter is primarily useful in tests and migration work. It runs both the
old decoder and the declarative schema, then compares their public values:

```python
from eltakobus.eep_schema import d2_compatibility_adapter

adapter = d2_compatibility_adapter("D2-06-01")
legacy_profile, wire_fields = adapter.decode(vld_message)
adapter.assert_compatible(vld_message)
```

`legacy_profile` is the unchanged instance returned by
`D2_06_01.decode_message`; the adapter never substitutes a wrapper in the
legacy path.

## D2-00-01 selected variants and codec

`D2_00_01_SCHEMA` selects a schema from the message ID in the low three bits
of the first payload byte. The five variants remain explicit because they have
different directions, lengths and fields:

| Variant | Direction | Minimum bytes | Content |
| --- | --- | ---: | --- |
| A | sensor to gateway | 2 | Configuration-valid flag and first user action |
| B | gateway to sensor | 5 | Display, presence, fan and status-symbol values |
| C | sensor to gateway | 4 | Repeated user action and signed set point |
| D | sensor to gateway | 3 | Measurement channel and 12-bit measurement |
| E | gateway to sensor | 6 | Set-point, timing, level and keep-alive configuration |

The dedicated field descriptors model compound values as named byte-local bit
segments. This represents B and C's little-endian 16-bit values, D's split
12-bit measurement and E's split interval directly, without changing the
general MSB-first `VLDLayout` contract.

Decode through the selector in the same way as the other schemas:

```python
from eltakobus.eep_schema import D2_00_01_SCHEMA

fields = D2_00_01_SCHEMA.decode_message(vld_message)
print(fields.value("message_type"), fields.value("direction"))
```

Encoding is deliberately limited to documented wire fields. Physical values
such as `figure_value`, `setpoint`, `measurement` and
`measurement_interval` are derived during decoding and cannot be supplied to
the encoder; callers encode their corresponding `*_raw` value instead:

```python
payload = D2_00_01_SCHEMA.encode_variant("D", {
    "channel_type": 0,
    "measurement_raw": 1234,
})
```

Encoding validates field widths, signed ranges and documented reserved-zero
bits. `base_payload` plus `require_all=False` supports a deliberate partial
update and preserves extension bytes. Variant B's upper three bits in its
final byte are preserved but not interpreted or rejected because the existing
decoder assigns no semantics to them. This boundary avoids inventing behavior
that is not present in the established implementation.

The compatibility adapter covers all five variants:

```python
adapter = d2_compatibility_adapter("D2-00-01")
adapter.assert_compatible(vld_message)
```

The original `D2_00_01` class remains the public decoder. No existing class,
constructor, attribute, registry entry or decode return type is replaced by
the schema.

## Migration rules

1. Add a schema beside, not instead of, the existing EEP class.
2. Add parity cases for nominal, reserved/error and extended payload values.
3. Keep all existing class names, constructors, attributes and `EEP.find()`
   behaviour unchanged.
4. Delegate an existing decoder internally only after parity coverage covers
   every supported message variant.

The D2 correction and public compatibility path are documented separately in
[D2 EEP migration](D2_EEP_MIGRATION.md).
