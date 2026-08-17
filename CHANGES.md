# Release Notes
All notable changes to this project will be documented in this file.
This project adheres to [Semantic Versioning](http://semver.org/).

## 2.0.0rc1

This release candidate contains the first protocol-focused v2 line. Existing
ESP2 message classes and their established constructors remain available; the
D2 correction below requires the documented migration for callers that used
the old mislabeled decoder.

### Fixed

- Corrected the former `D2-00-01` decoder, which actually implemented the
  `D2-06-01` window-handle and multisensor layout. The sensor decoder is now
  registered as `D2-06-01`; the standards-correct `D2-00-01` decoder supports
  documented room-control-panel messages A through E with corrected byte order.
- Changed FMMS44SB/FMS55SB/FMS55ESB/FMS65ESB catalog defaults to `D2-14-41`
  and exposed their documented NFC-selectable D2 alternatives as extra rows.

### Documentation and tests

- Added passive LAN gateway discovery for the `SmartConn`, `EUL` and
  `Virtual-Network-Gateway-Adapter` mDNS services. The optional `discovery`
  extra uses `zeroconf`; imports remain dependency-free until discovery starts.
- Added ESP2/ESP3 tutorials, runnable examples and the `eltakotool.py
  lan_scan` command for JSON or human-readable LAN gateway discovery.
- Added a read-only `examples/esp3_usb_stream.py` example for decoding native
  ESP3 packets directly from a USB serial port without `enocean`.
- Extended passive transport diagnostic snapshots with opt-in cumulative
  `TransportMetrics` data when a transport was explicitly instrumented.
- Made the changelog update an explicit required exit criterion for every
  roadmap iteration, including documentation, test and refactoring rounds.
- Added an explicit JSON-backed `LearnedDeviceRegistry` for accepted UTE
  associations with versioned schema validation and atomic persistence.
- Added `docs/INDEX.md` as the structured documentation entry point with
  recommended reading paths and short descriptions of all guides.
- Aligned the roadmap and UTE documentation with the new opt-in persistence
  boundary: storage is available, while authorization and secure teach-in stay
  explicit application responsibilities.
- Reworked mixed ESP2 message classification to select decoders from validated
  wire-format markers instead of probing every message class with exceptions.
- Refreshed the roadmap and status with post-RC milestones for secure teach-in,
  memory safety, EEP conformance, transport resilience, quality automation and
  explicit backward-compatibility acceptance gates.
- Updated the README with the current release-line capabilities, documentation
  entry point, safety boundaries, testing instructions and release workflow.
- Added a gateway overview covering FAM14, FGW14-USB, FAM-USB, USB300, ESP3,
  LAN, ESP2-over-TCP and CoAP transports, including baud rates, capabilities,
  usage examples and the passive LAN discovery boundary.
- Removed the obsolete `enocean` runtime/development dependency and the unused
  ESP3 extra. Native ESP3 framing, packet models and radio conversion are now
  the supported path. `ESP3MessageAdapter` keeps its public conversion methods
  and packet attributes; applications needing a concrete legacy `enocean`
  packet can opt in with an explicit factory after installing that package.

- Documented the A5-38-08 switching lock semantics directly in the EEP code,
  metadata reference, and regression tests.
- Added A5-38-08 gateway commands for setpoint shift, basic setpoint, control
  variable override, fan-stage selection and common blind/shutter control,
  with backward-compatible encode/decode tests.
- Added a detailed library roadmap covering ESP3, VLD, transactions, teach-in,
  virtual-bus testing, diagnostics and project boundaries.
- Added a persistent roadmap status and hand-off document describing the
  implementation state, validation baseline and continuation procedure.
- Documented recurring refactoring checkpoints as a required part of the
  roadmap implementation methodology.
- Documented the future folder-structure strategy: thematic subpackages may
  be introduced with compatibility-preserving re-export shims for old imports.
- Added a dependency-free declarative VLD field engine with strict encoding,
  scaling, units, enums and explicit reserved/error values.
- Added an incremental ESP3 framing parser with CRC validation, bounded input,
  noise recovery and lossless raw packet sections.
- Added a shared incremental ESP2 frame parser and refactored the ESP2 TCP and
  threaded serial receivers to use it, preserving their public interfaces and
  echo-suppression behavior.
- Added architecture documentation comparing the implementation with the
  independent `kipe/enocean` and `fruggy83/openocean` projects.
- Added native ESP3 semantic packet models and a serialized asynchronous
  dispatcher with response/event/radio separation and diagnostics.
- Added opt-in compatibility schemas for D2-06-01, D2-14-40 and D2-14-41;
  existing EEP classes and result objects remain unchanged.
- Added generic UTE query/response models and an explicit fail-closed teach-in
  session; no automatic enrollment or response is performed by parsing alone.
- Added safe opt-in memory sessions with dry-run, explicit confirmation,
  read-back verification and best-effort rollback.
- Added structured JSON-serializable diagnostics snapshots and a provenance-
  aware offline conformance-vector test framework.
- Added opt-in declarative D2-00-01 schemas for variants A-E without changing
  the existing decoder API.
- Added passive LAN-gateway mDNS discovery for SmartConn, EUL and
  Virtual-Network-Gateway-Adapter. Zeroconf is lazy and available only through
  the optional `discovery` extra; discovery never opens a gateway connection or
  sends telegrams.

## 1.0.1

### Fixed

- Updated the CoAP extra from obsolete `aiocoap 0.4a1` to a Python 3.10–3.14
  compatible release range and made the optional CoAP import lazy.
- Fixed CI push coverage for the repository's `master` branch.
- Added clean source-archive manifests and release-time package-version checks.
- Removed deprecated setuptools `tests_require` metadata and the deprecated
  license classifier warning.

### Added

- Added Eltako profiles `A5-13-02`, `A5-13-04`, `A5-14-01`, `A5-14-03`,
  `A5-14-05`, `A5-14-07`, and `A5-14-08`, including Eltako-specific bit
  layouts, scaling, metadata, error codes, and round-trip tests.
- Added ESP3/VLD support for `D2-00-01`, `D2-14-40`, and `D2-14-41` through
  the protocol-neutral `VLDMessage` type. Reserved/error values remain
  available as raw attributes and are not silently converted to physical
  values.
- Added the corresponding FWS61, FSU55D/FSU65D, eTronic, FFGB-hg, and
  FMMS44SB/FMS55SB/FMS55ESB/FMS65ESB entries to the independent device catalog.

## 1.0.0

### Added

- Portable gateway constants, passive serial-port scanning, protocol identity
  parsers, and reusable discovery/memory diagnostics in `eltakobus.const`,
  `eltakobus.gateway_scan`, `eltakobus.gateway_identity`, and
  `eltakobus.diagnostics`.
- Hardware-independent unit tests for the new gateway helpers.
- Added EEP `A5-02-05` for pure temperature sensors such as STM 330, including
  the official 0 to 40 °C scaling, metadata, validation, and regression tests.
- Added EEP `A5-07-03` for occupancy, supply voltage, and 10-bit illumination.
- Added the missing standard profiles `A5-02-01` through `A5-02-1B` (where
  applicable), `A5-02-20`, `A5-02-30`, `A5-06-03`, and `A5-07-02` from EEP
  2.6.7, including their documented bit layouts and physical ranges.
- Added EEP `F6-05-02` for smoke-detector alarm and low-battery status.
- Added Eltako catalogue profiles `A5-06-02`, `A5-09-05`, `A5-14-09`,
  `A5-14-0A`, `A5-20-04`, and
  `F6-05-01`, and aligned `A5-02-05` and `A5-30-03` with Eltako's inverted
  temperature scaling and status markers.
- Documented triage of upstream Home Assistant Eltako issues and the boundary
  between library-level and Home-Assistant-specific changes.

- Corrected the project licensing to the original LGPLv3-or-later terms,
  preserved the accompanying GPLv3 text required by LGPLv3, and clarified
  original and current author attribution.
- Added pull-request/push CI across Python 3.10–3.14 with unit tests,
  compilation checks, distribution builds, and `twine` metadata validation.
- Hardened the release workflow by testing declared package extras, validating
  build artifacts, and checking wheel installation before PyPI publication.
- Synchronized `requirements.txt` with the declared serial, CoAP, ESP3, test,
  and build dependencies; removed the unrelated `serial` package and the
  standard-library `asyncio` entry.
- Expanded offline replay coverage to all recorded memory rows, discovery
  frames, passive telegrams, switch-state results, and TCP-adapter input.
- Added `ESP2TCPSerialInterface` (also available as the upstream-compatible
  `ESP2TCP2SerialCommunicator`) for ESP2-over-TCP gateway adapters, including
  framed telegram parsing, asynchronous exchanges, callbacks, clean stop,
  and automatic reconnect.
- Added optional `ESP3MessageAdapter` support (`pip install .[esp3]`) with
  standards-compliant seven-byte RADIO_ERP1 optional data, defensive response
  conversion, and logging/ignoring of malformed ESP3 packets.
- Added structured metadata for all registered EEP profiles.
- Added the HA-independent `eltakobus.device_catalog` with the Eltako/EnOcean
  device list, gateway descriptions, receive/sender EEP mappings, PCT14
  programming hints, address counts, and device-name normalization.
- Added catalog lookup helpers (`find_hw_type`, `describe_gateway_type`,
  `devices_for_eep`, and `eep_device_mapping`) with unit tests.
- Added HA-independent Eltako teach-in support with the documented sender
  payloads, outgoing 4BS message builder, and links from sender EEPs to
  catalog devices in `eltakobus.teach_in`.
- Added dedicated Eltako telegram tests for FTF65S, FHD65SB, FLT58, FKS-H,
  FHMB/FRWB, FFGB/mTronic, FWS81, FRW, gateway switching, and shutter
  status/command markers.
- Added Home Assistant integration compatibility tests covering all imported
  EEP classes, constructor contracts, enum helpers, and common outgoing
  telegrams.
- Added `EEPMetadata` and `EEPFieldMetadata` with names, descriptions, ORG
  identifiers, units, logical value ranges, data types, and enum values.
- Added `EEP.get_metadata()` and JSON-friendly `EEPMetadata.as_dict()`.
- Added developer documentation for using, testing, and extending the library.
- Added a full command-line reference for `eltakotool.py` to the developer
  guide, and an `eltakotool.py --version` flag.
- Added `eltakotool.py benchmark ADDRESS`, measuring forced-poll
  request/response performance across several `delay_message` values and
  recommending the fastest delay meeting a minimum success rate.
- Added `tests/eltakotool_test.py`, covering argument parsing, the
  `benchmark` command's delay/rate measurement, and the `fakefam` command's
  serial/socket fallback.

### Fixed

- Fixed A5-10-03 target-temperature decoding and encoding to honor the
  documented 8 °C lower bound.
- Corrected the A5-06-03/A5-07-03 10-bit illumination layout: DB2 contains
  the two most significant bits and DB1 the eight least significant bits.
- Corrected A5-04-03 to use the official humidity-in-DB3 and 10-bit
  temperature-in-DB2/DB1 layout; added an independent OpenOcean comparison
  report and raw-payload regression coverage.
- `eltakotool.py --serial_lib_version 1` no longer crashes with a
  `NameError`: the option now parses as `int`, matching the `--baud_rate`
  option, which previously compared a string against `1`/`2` and left `bus`
  unassigned.
- `eltakotool.py fakefam` no longer crashes: it passed an unsupported `loop=`
  keyword argument to `asyncio.start_unix_server()`/`asyncio.start_server()`,
  and fell through into dead code referencing an undefined variable after a
  successful serial connection closed. `fakefam` now also honors
  `--baud_rate` instead of always using 57600.

### Compatibility

- Existing EEP constructors, encoders, decoders, and `EEP.find()` behavior are
  unchanged.
- H5-3F-7F keeps its existing three-argument whole-second constructor and now
  optionally supports 100-ms movement-time resolution.
- Metadata containers use immutable standard-library named tuples and add no
  runtime dependency.

### Packaging

- Source distributions and wheels include `eltakobus` only; repository tests
  and hardware fixtures remain available in the source tree but are excluded
  from installed library packages.

## Bug fix in initializing EEP A5-10-06 HeatingCooling

## 0.0.81 Echo Tests are made optional for serial connection.

## 0.0.80 New EEP added A5_09_04 CO2TemperatureHumiditySensor

## 0.0.79 Broken message handling fixed

## 0.0.78 Additional type for FSB14 added

## 0.0.77 Prettified broken telegram logs

## 0.0.76 Print parse error of broken packages

## 0.0.75 repeater mode functions added

## 0.0.74 Exception handling in serial thread extended

## 0.0.73 Added functions for discovery of devices
* Added functions for discovery of devices
* fixed blocking sleep function

## 0.0.68 Added helper functions for AddressExpression

## 0.0.67 updates b2s so that other objects of the same address can be printed as well

## 0.0.66 Fixed EEP A5-04-02 and added default values for EEPs

## 0.0.65 Added command to query for gateway base id and version

## 0.0.64 Refactored A5_10_06 (Heating and Cooling)
* Refactored A5_10_06 (Heating and Cooling)
* Cleaned up devices.py

## 0.0.63 Write sender with EEP F6-02-01 into actuator improved.
* Writing sender into actuator list with EEP F6-02-01/02. default: left push button

## 0.0.62 Added device FSR14M-2x 

## 0.0.61 Added EEP F6-01-01 for one-/push-button switch

## 0.0.59 Added EPP A5-10-03 for thermostat

## 0.0.57 Improved FTD14 handling

## 0.0.56 Added Sensor support for FTD14
- Sensors/Memory list of FTD14 can be read out

## 0.0.55 Added device FTD14
- Added device Telegram Duplicator (FTD14) which is a bus gateway

## 0.0.54 Added device FHK14 and F4HK14
- Added device FHK14 and F4HK14
- Changed slightly discovery mechanism of devices. (More than one type id can be added to identify device type)

## 0.0.53 Detection for FDG14 added
- Improvements to detect devices and added detection for FDG14 (DALI)

## 0.0.52 Unit Tests introduced
- Added initial unit test 
- Added test executing as part of release process

## 0.0.51
- Added EEP A5-30-01 and A5-30-03 for Digital Inputs

## 0.0.50
- Improved device programmability and added FAE14SSR and FMZ14

## 0.0.49
- Bug fixes/cleanup in EEPs

## 0.0.48
- Added EEP A5-0-03

## 0.0.47
- Made A5-08-01 compatible and fixed but

## 0.0.46
- added auto_reconnect as optional
- added more configuration possibility to RS485SerialInterfaceV2
- automatic release pipeline added

## 0.0.42
- Stabilized unlock and lock of FAM14

## 0.0.41
- Added get_all_sensors for FSB14 and FMZ14

## 0.0.40
- fixed message overflow in fgw14-usb. RS485 bus is working with 9600 and baudrate can be set to 57600 for FGW14-USB. When sending many message (ca. 12) in a row the buffer of FGW14-USB is flowing over.
- Added EEP H5-3F-7F for ensuring switches are programmed for cover (FSB14)

## 0.0.39
- status changed handler to serial connector added

## 0.0.38
- reconnect function for serial communication added

## 0.0.37
- extentions for management tooling

## 0.0.36
- fix of occupancy sensor (EEP A5-07-01)

## 0.0.35
- Status messages for temperature and humidity sensor (EEP A5-04-01) added
- Status messages for occupancy sensor (EEP A5-07-01) added

## 0.0.34
- Corrected telegram signals for window handle positions.

## 0.0.33
- new serial communication added which is running in a thread instead of event loop and which can automatically recover after connection loss.

## 0.0.32
- Changes for devices and sensor discovery added.

## 0.0.31
- Added parameter for baud rate.

## 0.0.30
- Status message for temperature actuator/sensor added. (EEP A5-10-06 and A5-10-12)
- Status message for air quality sensor added. (EEP A5-09-0C)

## 0.0.28
- Temperature and Humidity Sensor for EEP A5-04-02 added

## 0.0.27
- Bug Fix - Out of Memory: Range of device memory was not fitting.
- GFVS codes added so that automation software can use triggers in a generic manner.

## 0.0.26
- Refactoring and introduction of FGW14 communication

## 0.0.9
- Transferred from [GitLab eltakobus](https://gitlab.com/chrysn/eltakobus) library project to GitHub
