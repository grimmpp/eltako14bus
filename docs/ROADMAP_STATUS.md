# Roadmap implementation status

This file is the hand-off point for continuing roadmap work. It records the
current implementation state, the validation baseline, and the next planned
iteration. It is intentionally separate from the conceptual roadmap so that
completed work and open risks remain auditable.

## Current state

The current development line contains the following completed milestones:

- dependency-free ESP2 framing in the legacy, V2 and TCP receive paths;
- dependency-free ESP3 framing with CRC validation and resynchronisation;
- native ESP3 response, event, command and unknown-packet models;
- serialized ESP3 command dispatcher with cancellation and diagnostics;
- explicit, fail-closed UTE teach-in sessions;
- compatibility-safe VLD schemas for D2-06-01, D2-14-40 and D2-14-41;
- native radio model, transactions and virtual-bus replay support;
- opt-in transport metrics with message rates, retries and bounded reconnect
  history;
- EEP/device metadata, catalog and developer/user documentation.

The previous validation baseline was `304 passed, 2 skipped, 311 subtests
passed`. The current suite reports `317 passed, 2 skipped, 319 subtests
passed`, including passive LAN discovery and packaging tests. Compilation and
diff checks pass. The isolated build requires network access for its temporary
build environment; the source metadata remains valid and the non-isolated
build is used in offline validation. The version remains `2.0.0rc1`; no tag or
release is moved by roadmap work alone.

## Latest completed iteration

The current milestone round is split into disjoint tasks:

1. Safe memory read/write sessions now provide dry-run, explicit write
   confirmation, stale-plan detection, read-back verification and best-effort
   rollback. They do not claim atomicity with the existing F2/F4 primitives.
2. D2-00-01 now has opt-in declarative schemas for variants A-E, including
   split/little-endian fields and strict encoding. Existing decoder classes
   remain unchanged.
3. Structured JSON-serializable diagnostics now cover parser state, queues,
   dispatcher counters and gateway support information without consuming
   queues or errors.
4. The conformance-vector framework covers repository ESP2/ESP3 captures and
   D2 schema parity, while clearly distinguishing repository vectors from
   official specification vectors.
5. A final safety/compatibility pass verifies old ESP2 message/framing
   contracts, plan-before-write protections, snapshot passivity and D2-00-01
   compatibility with trailing vendor bytes.
6. The dependency checkpoint removes the unused `enocean` declaration and the
   old ESP3 extra while retaining the public ESP3 adapter through a native
   packet-shaped default and an explicit legacy factory hook.
7. Transport metrics add an opt-in, thread-safe collector for cumulative
   message rates, retries and bounded reconnect history; legacy transports are
   not instrumented implicitly.
8. The obsolete `enocean` declaration is removed from requirements, extras and
   CI. `zeroconf` is available only through the separate optional `discovery`
   extra. `ESP3MessageAdapter` keeps its public methods and packet attributes
   through a native default, while concrete legacy `enocean` packets remain
   available only through an explicit application factory.
9. `TransportMetrics` is now optionally wired into both serial interfaces and
   the ESP2-over-TCP adapter. Successful I/O and connection failures are
   counted without running user callbacks under the metrics lock; `metrics=None`
   preserves the legacy behavior.
10. `GATEWAYS.md` documents the known gateway families, protocol differences,
    transport selection, baud rates, examples and the passive LAN discovery
    boundary.
11. Passive LAN-gateway mDNS discovery now supports the reference SmartConn,
    EUL and Virtual-Network-Gateway-Adapter mappings without adding a base
   runtime dependency. The optional `discovery` extra loads `zeroconf` only
   when discovery is started.
12. ESP2/ESP3 tutorials, offline/runnable examples and the `lan_scan` CLI
    command document and exercise the new protocol and discovery APIs.
13. Added a read-only USB ESP3 stream example using the native framing and
    packet decoders; the tutorial documents source-tree and installed-package
    usage without introducing an `enocean` dependency.
14. Transport diagnostic snapshots now include the immutable opt-in
    `TransportMetrics` view when a transport provides one, while preserving
    the existing `None` behavior for uninstrumented transports.
15. Added an explicit, versioned `LearnedDeviceRegistry` for UTE associations
    with atomic JSON persistence, duplicate protection and fail-closed loading;
    secure teach-in policy and device-specific authorization remain separate.
16. Added `docs/INDEX.md` as the documentation entry point, grouping all
    guides by user, application, protocol, testing, operations and releases.
17. Reworked legacy ESP2 message classification to use preamble, length,
    checksum, `h_seq`, ORG and teach-in markers before invoking one decoder;
    existing `.parse()` methods and `prettify()` behavior remain compatible.

The refactoring checkpoint confirmed that these additions remain additive,
dependency-free and outside Home Assistant. Its concrete boundaries,
regressions and deferred production cleanups are recorded in
[REFACTORING_CHECKPOINT.md](REFACTORING_CHECKPOINT.md). The full package has
now been checked after integration; the remaining roadmap items are explicitly
listed below.

After each implementation group, a dedicated refactoring checkpoint is
required. It reviews duplicated parsing/validation code, module boundaries,
public exports, type hints, naming, error handling and compatibility before
the next milestone is accepted.

The checkpoint also evaluates folder structure. Once a domain becomes large
enough, new canonical subpackages such as `eltakobus.protocol` or
`eltakobus.sessions` may be introduced. Existing paths must remain as thin
re-export shims, and both old and new import paths require tests.

Each task must add focused tests and documentation, must not introduce a Home
Assistant dependency, and must preserve existing constructors, `EEP.find()`,
ESP2 messages and transport behavior.

## Iteration procedure

For every round:

1. inspect the current public API and open roadmap risks;
2. delegate disjoint implementation or review milestones;
3. run focused tests for each milestone;
4. integrate only additive, compatibility-safe changes;
5. perform a targeted refactoring checkpoint without changing behavior;
6. run an independent second-pass review against old APIs and edge cases;
7. run the complete test suite, compilation, diff checks and package build;
8. update this file, `ROADMAP.md`, `CHANGES.md` and the relevant feature docs.
   The changelog update is a mandatory iteration exit criterion, including
   for documentation-only, test-only and refactoring milestones.

Refactoring is accepted only when the public compatibility tests and focused
milestone tests remain green. Structural cleanup must not be used to silently
change transport timing, message constructors, EEP identifiers or hardware
side effects.

Hardware access remains opt-in. Destructive bus operations require explicit
application confirmation and are validated using replay/fake transports first.

## Open after the latest iteration

- secure teach-in and persistent learned-device storage;
- actuator-specific memory-write rollback semantics;
- independently reviewed D2-00-01 and other official vector expansion where a
  source revision is available;
- multi-version CI/static typing improvements.
- explicit, safe semantics for requesting TCP reconnect from inside the
  transport's own status callback; callers should currently request reconnect
  from an external thread/task.
- optional integration of `TransportMetrics` into each transport's own
  higher-level gateway report, if this can be done without changing legacy
  timing. The transport constructors already support opt-in collection.

## Local verification note

The complete suite needs a valid `pyserial` installation. In the local `.venv`
the `serial` namespace package is incomplete and does not provide
`serial.serialutil` or `serial_for_url`; serial-transport tests therefore fail
before exercising the library. Running the same suite with the clean serial
extra on `PYTHONPATH` is the required verification path until the local virtual
environment is repaired.

The dependency iteration's isolated package build could not bootstrap its
temporary `setuptools` environment because this workspace had no network
access. This is an environment limitation, not a package metadata failure;
CI performs the isolated build with network access.
