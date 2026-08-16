# Library roadmap

This roadmap describes library-level improvements that fit `eltako14bus`.
Home Assistant entities, UI behavior and configuration schemas remain outside
the library and should consume these stable protocol APIs instead.

## Implemented in the current development line

### A5-38-08 central commands

`A5-38-08` now models the common gateway commands from the EEP definition:

- `0x01` switching, including time, delay/duration and explicit lock/unlock;
- `0x02` absolute or relative dimming, ramping time and final-value storage;
- `0x03` relative temperature setpoint shift;
- `0x04` absolute basic setpoint;
- `0x05` controller-variable override, operating mode, occupancy and energy
  hold-off;
- `0x06` fan-stage override, including automatic stage `255`;
- `0x07` common blind/shutter command with function, position/angle and
  service/status flags.

Normal switching keeps `lock=False`. Locking is an intentional actuator
operation: with `lock=True`, the actuator ignores other commands until the
timer expires; a zero timer means an unlimited lock. Applications should
expose this as a separate action, not silently enable it for every light
command.

## Priority 1: protocol correctness and reliability

### Native ESP3 message model

Introduce a protocol-neutral radio telegram model that retains RORG, sender,
status, optional ESP3 data, security level and direction. ESP3 packets should
not need to be converted to fixed-size ESP2 messages when the application only
needs to decode them. The existing ESP2 conversion API remains as a backwards-
compatible adapter.

This is especially important for VLD/D2 profiles and ESP3 gateways such as
USB300 and MGW-LAN. Unsupported conversions should be classified as expected
capability differences instead of logged as receive failures.

### Command/response transactions

Add a reusable command layer with:

- correlation of outgoing commands and feedback telegrams;
- timeout and cancellation handling;
- bounded retries and configurable retry delays;
- explicit `CommandTimeout`, `CommandRejected` and `UnsupportedCommand`
  errors;
- optional latency and retry metrics.

This should sit above serial framing and below consumer applications.

### Safe teach-in and memory sessions

Expose teach-in, teach-out, memory-read and memory-write as cancellable
sessions with confirmation handling, dry-run support, validation and rollback
where the device supports it. Destructive operations should require an
explicit opt-in and produce a structured diagnostic record.

## Priority 2: EEP coverage and validation

### Generic VLD field engine

Represent VLD fields declaratively with bit offset, width, scaling, units,
enumerations and reserved/error values. This will reduce duplicated D2 bit
handling and allow metadata, validation and decoding to share one definition.

### Official conformance vectors

Store raw test vectors derived from official EEP tables as JSON resources. Each
vector should cover minimum, maximum, reserved, error and teach-in values.
Tests should verify both decoding and encoding where the profile is
bidirectional.

### EEP and device catalog expansion

Continue adding profiles only when their wire layout is documented. Keep
manufacturer-specific behavior separate from the generic EEP and associate it
through the independent device catalog. The catalog should eventually model
firmware-dependent variants and receive/sender EEP compatibility explicitly.

## Priority 3: offline development and diagnostics

### Virtual bus and fault injection

Provide a deterministic virtual bus for tests and examples. It should support
message injection, configurable delay, packet loss, duplicate telegrams,
checksum errors, disconnect/reconnect and concurrent senders. This makes most
serial and gateway tests runnable without hardware.

### Recording and replay

Define a stable JSON or binary recording format containing timestamps, raw
telegram bytes, decoded metadata and gateway information. The CLI should be
able to record, inspect and replay captures without activating real actors.

### Structured diagnostics

Expose gateway identity, bus health, queue depth, message rates, retries,
decode failures and reconnect history through a serializable diagnostics API.

## Priority 4: maintainability

- generate the EEP reference documentation from runtime metadata;
- keep type hints and public API contracts current;
- add static checks for formatting, typing and unused protocol branches;
- test supported Python versions and optional dependencies independently;
- keep all core features free of Home Assistant imports.

## Deliberate boundaries

The library should not contain Home Assistant entity classes, UI behavior,
service names or platform-specific state restoration. Those concerns belong in
integrations that use the protocol and EEP APIs.
