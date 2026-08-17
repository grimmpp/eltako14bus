# Library roadmap

For the current implementation state, validation baseline and next iteration,
see [ROADMAP_STATUS.md](ROADMAP_STATUS.md). That file is updated after each
milestone and review round.

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

## Delivered for v2.0.0rc1

- Native immutable `RadioTelegram` for RADIO_ERP1, including optional ESP3
  metadata and explicit legacy conversion boundaries. See `NATIVE_ESP3.md`.
- Opt-in request/response transactions with matchers, cancellation, bounded
  retries, metrics and unmatched-message preservation. See `TRANSACTIONS.md`.
- Deterministic `VirtualBus` with replay, recording, fault injection and
  concurrent-sender coverage. See `VIRTUAL_BUS.md`.
- Serial callback deadlock fixes and bounded exchange behavior before start,
  after stop, and during reconnect scenarios.
- Corrected D2-00-01/D2-06-01 profile registration and multisensor catalog
  defaults. See `D2_EEP_MIGRATION.md`.
- Core package import is independent of optional serial, CoAP, YAML and ESP3
  dependencies; explicit transport use reports installation guidance.
- Added a dependency-free declarative VLD field engine with MSB-first fields,
  scaling, enums, units, reserved/error values and strict encoding. See
  `VLD_FIELDS.md`.
- Added a dependency-free incremental ESP3 framing layer with CRC validation,
  bounded lengths, noise recovery and lossless raw packet sections. See
  `ESP3_FRAMING.md` and `REFERENCE_COMPARISON.md`.
- Added a dependency-free incremental ESP2 framing layer and refactored the
  TCP gateway and threaded RS485 receiver to share it. ESP2 framing,
  resynchronisation and checksum diagnostics are now tested independently of
  the transports.
- Added deterministic legacy ESP2 message classification from validated wire
  markers. Mixed-message dispatch no longer probes every decoder by catching
  `ParseError`; existing semantic parsers remain responsible for content
  validation.
- Added native ESP3 response, event, command and unknown-packet models plus a
  serialized async dispatcher with separate radio/event/response queues and
  diagnostics. See `ESP3_DISPATCHER.md`.
- Added compatibility-safe declarative schemas for D2-00-01 variants A-E,
  D2-06-01, D2-14-40 and D2-14-41. Existing EEP classes remain unchanged; the
  schema layer is opt-in until independent conformance coverage is broader.
  See `EEP_SCHEMA.md`.
- Added generic UTE query/response models and an explicit policy-controlled
  teach-in session. Parsing never changes state or sends an acceptance; secure
  teach-in remains outside this milestone. The opt-in persistent
  `LearnedDeviceRegistry` is documented in `UTE_SESSION.md`.
- Added safe opt-in memory sessions with dry-run, explicit write confirmation,
  stale-plan detection, read-back verification and best-effort rollback. See
  `MEMORY_SESSIONS.md`.
- Added structured JSON-serializable parser, transport, dispatcher and gateway
  diagnostic snapshots. See `DIAGNOSTICS.md`.
- Added optional `TransportMetrics` integration to the serial and ESP2-over-TCP
  transports for successful I/O, connection failures and reconnect history.
  Passing `metrics=None` preserves legacy behavior. See `DIAGNOSTICS.md`.
- Added passive optional mDNS discovery for supported LAN gateway service
  types. Discovery remains separate from transport connections and telegram
  I/O. See `GATEWAYS.md`.
- Added an offline conformance-vector framework for repository captures and
  schema parity, with explicit provenance rules. See `CONFORMANCE_VECTORS.md`.
- Added opt-in declarative D2-00-01 schemas for variants A-E while preserving
  the existing decoder classes and `EEP.find()` behavior.
- Removed the obsolete `enocean` dependency and unused ESP3 extra. The public
  `ESP3MessageAdapter` now uses a native packet-shaped default; applications
  needing a concrete legacy packet can pass an explicit factory. See
  `DEVELOPER_GUIDE.md` and `ESP3_FRAMING.md`.

The RC does not claim secure teach-in, device-specific protected-memory rules,
or a complete official vector corpus as finished. Those remain post-RC roadmap
work. Persistent learned-device storage is available only through the explicit
opt-in registry and does not authorize or perform teach-in by itself.

## Priority 1: protocol correctness and reliability

### Native ESP3 message model

The RC delivers a protocol-neutral radio telegram model that retains RORG, sender,
status, optional ESP3 data, security level and direction. ESP3 packets should
not need to be converted to fixed-size ESP2 messages when the application only
needs to decode them. The existing ESP2 conversion API remains as a backwards-
compatible adapter.

This is especially important for VLD/D2 profiles and ESP3 gateways such as
USB300 and MGW-LAN. Unsupported conversions should be classified as expected
capability differences instead of logged as receive failures.

### Command/response transactions

The RC delivers an opt-in reusable command layer with:

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

The native ESP3 dispatcher is now available as the transport-neutral base for
these sessions. Generic UTE policy and memory-operation safety are kept out of
the receive parser and are implemented as explicit session layers. Secure
teach-in and actuator-specific rollback policies remain open; persistent
enrollment is available only as an explicit registry operation after policy
approval.

## Priority 2: EEP coverage and validation

The RC corrects the D2 profile identity and validates the currently registered
D2 profiles. The generic field engine and independent official vector corpus
remain planned work.

### Generic VLD field engine

The standalone engine now has opt-in schemas for D2-00-01 variants A-E,
D2-06-01, D2-14-40 and D2-14-41, without changing public constructors or
decoded result objects. The next step is independently sourced vector coverage
and, only then, carefully considered internal delegation by legacy decoders.

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

The RC delivers the virtual bus, replay and recording foundation plus passive,
structured diagnostic snapshots. Transport-level cumulative rates, retry
counters and reconnect histories remain planned work.

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

The serializable snapshot API is now available for gateway identity, parser
state, queue depth and decode/dispatcher counters. Cumulative message rates,
retry counters and reconnect history are available through the opt-in,
transport-neutral `TransportMetrics` collector; existing transports are not
silently instrumented and therefore keep their legacy timing behavior.

## Priority 4: maintainability

- perform a refactoring checkpoint after each major implementation milestone;
  review duplication, module boundaries, public exports, type hints and error
  handling while preserving compatibility;
- introduce thematic subpackages when the flat module layout becomes too
  large, preserving old module paths through tested re-export shims;
- generate the EEP reference documentation from runtime metadata;
- keep type hints and public API contracts current;
- add static checks for formatting, typing and unused protocol branches;
- test supported Python versions and optional dependencies independently;
- keep all core features free of Home Assistant imports.

## Deliberate boundaries

The library should not contain Home Assistant entity classes, UI behavior,
service names or platform-specific state restoration. Those concerns belong in
integrations that use the protocol and EEP APIs.
