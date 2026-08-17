# Native ESP3 radio telegrams

`RadioTelegram` is the dependency-free, immutable representation of an ESP3
`RADIO_ERP1` telegram. It preserves information that cannot fit into the
library's fixed-size ESP2 message format, especially VLD payloads and ESP3
optional metadata.

The existing classes in `eltakobus.message` remain unchanged. Applications can
adopt the native model incrementally and existing EEP decoders can read it
through the compatibility properties `org`, `data`, `address`, `status` and
`outgoing`.

## Data model

```python
from eltakobus.radio import RadioTelegram, TelegramDirection

telegram = RadioTelegram(
    rorg=0xD2,
    payload=bytes.fromhex("0102030405"),
    sender=bytes.fromhex("01020304"),
    status=0,
    direction=TelegramDirection.INCOMING,
    destination=bytes.fromhex("FFFFFFFF"),
    subtelegram_count=1,
    rssi_dbm=-70,
    security_level=0,
)
```

The model validates the RADIO_ERP1 limits when it is created:

- RORG and status are one byte each;
- sender and destination IDs contain four bytes;
- payloads contain 1 to 14 bytes;
- RPS (`F6`) and 1BS (`D5`) payloads contain one byte;
- 4BS (`A5`) payloads contain four bytes;
- subtelegram count is retained as its complete ESP3 wire byte (`0..255`), RSSI is `-255..0 dBm`, and the supported ESP3
  security levels are `0..4`;
- optional metadata is either complete or absent.

Instances are frozen and hashable. Byte-like input is copied to `bytes`, so a
caller cannot mutate a telegram through a `bytearray` after construction.

## Reading ESP3 RADIO_ERP1 packets

No `enocean` import is required. An existing packet object only needs `data`
and `optional` attributes; `packet_type` and `rorg` are validated when they are
present.

```python
telegram = RadioTelegram.from_esp3_packet(packet)
```

Direction is a local transport property and is not encoded by the ESP3
subtelegram counter. Pass it explicitly for transmitted packets:

```python
telegram = RadioTelegram.from_esp3_packet(
    packet,
    direction=TelegramDirection.OUTGOING,
)
```

For adapters that already expose the two wire sections, use
`from_esp3_fields(data, optional_data)`. `to_esp3_fields()` returns those same
sections without changing their bytes. Unknown RORG values are retained and
can therefore be recorded, inspected and forwarded even when no EEP decoder
exists.

```python
data, optional = telegram.to_esp3_fields()
packet = telegram.to_esp3_packet(
    lambda packet_data, packet_optional: Packet(
        PACKET.RADIO_ERP1, packet_data, packet_optional
    )
)
```

The factory form keeps the core model independent of any third-party ESP3
package. The built-in ESP3 framing, packet and radio models are the supported
implementation.

An incomplete captured telegram has no seven-byte optional section. It can be
round-tripped with `to_esp3_fields()` for capture and inspection, but
`to_esp3_packet()` rejects it by default because it would create an invalid
outbound `RADIO_ERP1` packet. An adapter that supplies the optional section
itself may deliberately opt in with
`allow_incomplete_optional_data=True`.

## Existing ESP2 and VLD objects

Create a native telegram from `RPSMessage`, `Regular1BSMessage`,
`Regular4BSMessage`, `VLDMessage`, or another object with the same public radio
fields:

```python
native = RadioTelegram.from_legacy_message(message)
```

ESP2 has no destination, RSSI, security level or raw optional-data fields.
Those values are consequently absent after this conversion. Core radio fields
and the incoming/outgoing direction are preserved.

Conversion back to the existing message classes is supported for RORG `F6`,
`D5`, `A5` and `D2`:

```python
legacy = native.to_legacy_message()
```

If the native telegram contains ESP3 optional metadata, conversion is rejected
because it would be lossy. A caller that consciously needs an existing message
object can opt in:

```python
legacy = native.to_legacy_message(allow_metadata_loss=True)
```

Unknown RORG values have no legacy representation and raise `ValueError`
instead of being silently misclassified.

## Current limitations

- `RadioTelegram` models `RADIO_ERP1` only. ESP3 response, event, common-command
  and remote-management packets need separate native models.
- It does not frame ESP3 packets or validate ESP3 header/data CRCs; that remains
  the transport's responsibility.
- Converting a native 4BS teach-in telegram to a legacy object preserves all
  wire fields but returns the general `Regular4BSMessage` class, not a specific
  teach-in subclass.
- Existing serial and ESP3 gateway adapters do not emit `RadioTelegram` yet.
  This bounded slice provides the model and explicit adapters without changing
  transport behavior.
