# Architecture comparison

The v2 protocol layer was reviewed against two independent EnOcean
implementations:

- [kipe/enocean](https://github.com/kipe/enocean), a Python ESP2/ESP3 library;
- [fruggy83/openocean](https://github.com/fruggy83/openocean), a Java EnOcean
  implementation with a large EEP model.

These projects are reference implementations, not runtime dependencies and
not replacements for the official ESP3 and EEP specifications.

## Adopted ideas

`eltakobus.esp3_frame` follows the useful separation visible in both projects:
framing, CRC validation and stream recovery happen before semantic packet
decoding. `ESP3FrameParser` accepts partial reads, concatenated frames and
noise, while preserving unknown packet types and raw data sections.

`eltakobus.vld` adopts the declarative field idea used by the Python library's
EEP definitions and the Java implementation's shared profile structure. It
keeps definitions in Python, so the library has no XML parser or runtime data
file dependency. Fields retain raw values and explicitly classify reserved,
error and unmapped values.

The same boundary is now used for the fixed-size Eltako ESP2 stream in
`eltakobus.esp2_frame`. Its parser validates the complete fourteen-byte frame
before the transport applies `prettify()` or exchange matching.

The existing `RadioTelegram`, transaction manager and virtual bus remain
separate layers. This keeps transport, framing, radio semantics and test
simulation composable and preserves the legacy ESP2 interfaces.

## Deliberate differences

The Python reference combines packet construction, EEP lookup and optional
teach-in behavior in a broad packet/communicator abstraction. This library
keeps teach-in acceptance and destructive operations in explicit sessions;
receiving a telegram must never enroll a device implicitly.

The Java reference contains openHAB lifecycle, channel and discovery classes.
Those concerns do not belong in this protocol library. Unknown packet and
profile values are retained for diagnostics rather than silently discarded.

## Compatibility policy

The new layers are opt-in. Existing EEP constructors, ESP2 message classes,
serial interfaces and the optional third-party ESP3 adapter remain available.
Compatibility aliases such as `ESP3StreamParser`, `optional_data` and
`ESP3FrameLengthError` ease adoption without coupling the core to either
reference project.

The comparison informed architecture and tests only; no source code from
either project is copied into this repository.
