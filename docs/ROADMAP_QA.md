# Roadmap QA: ESP2 parser integration

## Scope and milestone

This independent QA milestone reviews the parser-oriented roadmap work without
changing production code. It covers the additive `ESP2FrameParser` API, its
integration into the threaded RS485 interface, the legacy asyncio RS485
interface, the ESP2-over-TCP gateway, and package-level wildcard imports.

The tested compatibility contract is intentionally narrow and stable:

- ESP2 wire telegrams remain exactly fourteen bytes (`A5 5A`, eleven body
  bytes, checksum).
- `ESP2Message`, its existing subclasses, `serialize()`, `parse()` and the
  package-level message imports remain available.
- Framing only selects valid raw frames. Existing transports keep ownership of
  message specialisation (`prettify`), echo handling, callbacks and exchange
  matching.
- The legacy asyncio RS485 interface still yields generic `ESP2Message`
  instances, as it did before the parser refactor.
- Malformed input, split preambles, arbitrary chunks and consecutive frames
  do not prevent a later valid frame from being delivered.

## QA tests

[`tests/roadmap_qa_test.py`](../tests/roadmap_qa_test.py) adds an independent
regression layer. It verifies:

1. The new parser is additive to the historic package-level message API.
2. An invalid candidate that overlaps the preamble of the next valid frame is
   resynchronised without losing that valid frame.
3. Buffer-protocol input and ordered multiple-frame delivery work.
4. The legacy asyncio transport uses the parser while preserving its generic
   `ESP2Message` delivery semantics.
5. A dependency-free `from eltakobus import *` keeps the core ESP2 symbols
   available.
6. Explicit lazy imports of the V2 serial transport still resolve when its
   optional extra is installed.

The existing focused suites remain responsible for threaded V2 echo handling,
callbacks, reconnects, concurrent exchanges, TCP transport behavior, and the
optional-serial import boundary.

Run the full parser and transport regression group with:

```sh
pytest -q \
  tests/roadmap_qa_test.py \
  tests/esp2_frame_test.py \
  tests/serial_test.py \
  tests/esp2_gateway_test.py \
  tests/serial_import_test.py
```

## Result

The reviewed parser integration is compatible with the tested ESP2 public API.
The framing layer improves recovery from corrupted byte streams without
changing the semantics of legacy message parsing or transport-specific
delivery.

The second pass also verified the native ESP3 and package-level integration.
The final fixes cover bounded command sends, close-time cancellation, receive
wakeup after transport failure, semantic/raw-frame parity, bounded parser
diagnostics and historic serial wildcard exports.

## Second-pass result: legacy wildcard export restored

When the optional serial extra is installed, the package root now exposes both
historical serial classes to:

```python
from eltakobus import *
```

In a minimal installation the optional import remains skipped, so importing
the dependency-free core does not require pyserial. Explicit lazy attribute
access continues to provide the historical names when the extra is present.

## Follow-up observations

- `ESP2FrameParser.errors` is bounded by `max_errors` and can be drained with
  `pop_errors()` or cleared with `reset()`.
- `feed()` accepts bytes-like values and integer iterables, but rejects a
  scalar integer to avoid Python's surprising `bytes(integer)` behavior.
- The legacy asyncio interface has deliberately not been given new callback
  semantics or changed to `prettify()`: changing those would be a compatibility
  break unrelated to framing.
- Package-root wildcard exports are currently broad and partly accidental,
  because several legacy modules do not define `__all__`. Adding a curated
  package `__all__` should be handled as a separate compatibility-reviewed
  change: it must preserve documented historic names while avoiding exports of
  imports such as typing helpers and implementation modules.

## Safety and compatibility audit (2026-08-18)

An independent audit added regression checks without changing production code.
It verified that all D2-00-01 variants A-E preserve the established acceptance
of trailing vendor bytes while their schema values remain equal to the legacy
decoder. It also proves that a memory plan is rejected before any I/O when it
is presented to a session for another device address, and that a diagnostic
snapshot only uses passive parser accessors rather than `pop_errors()` or
`reset()`.

The audit found no tested ESP2 or EEP API regression. One operational caveat
is documented in `MEMORY_SESSIONS.md`: confirmation tokens protect plan
integrity, not physical-gateway identity, so plans must not be transferred
between installations or transport owners.

The test environment must contain real `pyserial` and `pyserial-asyncio` for
the threaded serial tests. A local namespace-only `serial` installation lacks
`serial.serialutil` and `serial_for_url`; that is an environment/dependency
blocker, not a parser compatibility failure.

## Required gates for future roadmap milestones

Every future milestone must provide evidence for all applicable gates:

- **Behavior:** focused unit tests cover valid, invalid, boundary, cancellation
  and failure cases, with replay/fake transports before hardware tests.
- **Compatibility:** old imports, constructors, serialized bytes, parser
  exceptions, callback order and default timing are regression-tested. New
  behavior is opt-in and deprecations include a migration note.
- **Safety:** destructive bus operations require explicit policy/confirmation;
  snapshots and parsers are side-effect free; persistence rejects unknown
  schemas and partial writes.
- **Resilience:** fragmented streams, noise, duplicate frames, disconnects,
  reconnects, cancellation, queue pressure and concurrent callers are bounded
  and tested without hangs.
- **Evidence:** official EEP vectors record provenance; hardware results are
  stored as replayable fixtures; performance claims include workload and
  environment.
- **Packaging:** core imports without optional extras, supported Python
  versions are checked, metadata/license/dependency checks pass, and the wheel
  plus source distribution are validated.
- **Handoff:** implementation docs, roadmap status, refactoring findings and
  `CHANGES.md` are updated before the iteration is marked complete.

The acceptance result should state which gates were exercised and which remain
explicitly deferred. A passing unit test alone is not sufficient evidence for
a roadmap milestone that changes safety, persistence, timing or public APIs.
