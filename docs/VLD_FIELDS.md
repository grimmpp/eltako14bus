# Declarative VLD bit fields

`eltakobus.vld` provides a standalone field engine for variable-length data
(VLD) telegrams. It has no dependency on XML profile files, Home Assistant,
openHAB, a serial transport, or a third-party ESP3 package. Existing EEP
classes continue to work unchanged; profiles can migrate to this engine one at
a time in a later release.

## Bit numbering

Offsets follow EnOcean EEP notation. Offset `0` is the most-significant bit of
the first payload byte, and fields may cross byte boundaries:

```text
byte 0                  byte 1
offset 0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15
       M S B       L S B M S B          L S B
```

## Define a payload

```python
from eltakobus.vld import VLDField, VLDLayout

sensor_values = VLDLayout(
    name="sensor-values",
    payload_size=3,
    fields=(
        VLDField.enum(
            "mode", offset=0, width=2,
            values={0: "off", 1: "heating", 2: "cooling"},
        ),
        VLDField.boolean("contact", offset=2),
        VLDField.linear(
            "temperature", offset=8, width=10,
            raw_range=(0, 1000),
            value_range=(-40.0, 60.0),
            unit="°C",
            reserved_values=frozenset(range(1001, 1024)),
        ),
    ),
)
```

Four field types are available:

- `VLDField.raw(...)` exposes an unsigned integer.
- `VLDField.linear(...)` maps a raw interval to a physical interval. Reversed
  physical ranges are supported.
- `VLDField.enum(...)` maps raw values to unique, hashable semantic values.
- `VLDField.boolean(...)` supports both normal `0/1` and explicit alternative
  raw values.

Definitions are frozen. Enum and error mappings are copied and exposed as
read-only mappings, so changing the caller's original dictionary cannot change
a profile after construction.

## Decode

```python
decoded = sensor_values.decode(payload)

temperature = decoded["temperature"]
print(temperature.raw)
print(temperature.value)
print(temperature.unit)
print(temperature.status)

# Convenient when the caller requires a valid value:
value = decoded.value("temperature")
```

Every result retains the raw integer. Its status is one of:

- `VALID`: `value` contains the decoded value.
- `RESERVED`: the raw value was explicitly listed in `reserved_values`.
- `ERROR`: the raw value is present in `error_values`; `reason` contains the
  configured protocol error description.
- `UNMAPPED`: the value fits the field but is outside its operational range or
  has no enum/boolean mapping.

For the last three states, `value` is `None`. `decoded.value(name)` raises a
`ValueError`, which prevents unavailable or reserved values from being mistaken
for real measurements.

## Strict encoding

```python
payload = sensor_values.encode({
    "mode": "heating",
    "contact": True,
    "temperature": 20.0,
})
```

Encoding validates all of the following:

- all declared fields are present by default;
- unknown names are rejected;
- values stay inside raw and physical ranges;
- enum and boolean values have an explicit mapping;
- reserved and error raw values cannot be produced;
- a physical value must be exactly representable by the field resolution.

Strict representability avoids hidden rounding. For example, a two-bit linear
field mapping `0..3` to `0.0..1.0` can encode `0`, `1/3`, `2/3`, and `1`, but
not `0.5`.

To modify selected fields while keeping all other and unused bits, use an
explicit partial update:

```python
updated = sensor_values.encode(
    {"contact": False},
    base_payload=existing_payload,
    require_all=False,
)
```

Field-level `decode()`, `extract_raw()`, `encode_raw()`, and `encode_into()`
are available for profile variants that do not need a complete layout.

## Scope and integration

The engine operates on the VLD payload bytes only. RORG, sender, status,
security metadata, transport framing, message direction, and transaction timing
remain responsibilities of `RadioTelegram`, transport code, or the EEP class.
This boundary keeps field definitions deterministic and easy to test.
