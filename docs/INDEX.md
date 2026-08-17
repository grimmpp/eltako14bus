# eltako14bus documentation

This page is the documentation entry point for developers and users. The
documents are grouped by purpose so that the flat, backwards-compatible file
names in `docs/` remain stable while the reading order stays clear.

## Recommended paths

### 1. First use

| Document | Purpose |
| --- | --- |
| [User guide](USER_GUIDE.md) | Short installation and operational quick start. |
| [Gateway overview](GATEWAYS.md) | Choose between FAM14, USB, ESP3, TCP, CoAP and LAN gateways. |
| [ESP2 tutorial](TUTORIAL_ESP2.md) | Read and use the legacy Eltako/ESP2 transport. |
| [ESP3 tutorial](TUTORIAL_ESP3.md) | Decode native ESP3 streams and use USB readers. |
| [EEP reference](EEP_REFERENCE.md) | Find implemented profiles, fields, units and ranges. |

### 2. Application features

| Document | Purpose |
| --- | --- |
| [Device catalog](DEVICE_CATALOG.md) | Map products, capabilities and EEPs without Home Assistant. |
| [Teach-in telegrams](TEACH_IN.md) | Eltako-specific sender-button teach-in commands. |
| [UTE sessions](UTE_SESSION.md) | Explicit, fail-closed generic UTE decisions and persistence. |
| [A5-38-08 commands](A5_38_08_COMMANDS.md) | Central switching, dimming, HVAC, fan and blind commands. |
| [Memory sessions](MEMORY_SESSIONS.md) | Dry-run, confirmation, verification and rollback boundaries. |
| [Transactions](TRANSACTIONS.md) | Request/response matching, retries and cancellation. |
| [Diagnostics](DIAGNOSTICS.md) | Passive snapshots, metrics and support reports. |

### 3. Protocol and architecture

| Document | Purpose |
| --- | --- |
| [Native ESP3](NATIVE_ESP3.md) | Protocol-neutral radio telegram model. |
| [ESP3 framing](ESP3_FRAMING.md) | Incremental framing, CRC validation and recovery. |
| [ESP3 dispatcher](ESP3_DISPATCHER.md) | Typed packet dispatch and serialized commands. |
| [ESP2 framing](ESP2_FRAMING.md) | Shared legacy ESP2 parser and compatibility boundary. |
| [ESP2 message parser](MESSAGE_PARSER.md) | Deterministic message classification without exception probing. |
| [VLD fields](VLD_FIELDS.md) | Declarative bit fields, scaling, units and enums. |
| [EEP schemas](EEP_SCHEMA.md) | Opt-in declarative D2 schema support. |
| [Virtual bus](VIRTUAL_BUS.md) | Deterministic replay, recording and fault injection. |
| [Conformance vectors](CONFORMANCE_VECTORS.md) | Provenance-aware offline protocol and EEP vectors. |
| [Reference comparison](REFERENCE_COMPARISON.md) | Architectural comparison with other EnOcean libraries. |
| [OpenOcean EEP comparison](EEP_OPENOCEAN_COMPARISON.md) | Profile coverage comparison and compatibility notes. |

### 4. Development, testing and operations

| Document | Purpose |
| --- | --- |
| [Developer guide](DEVELOPER_GUIDE.md) | Public APIs, extension points and local development. |
| [Roadmap](ROADMAP.md) | Planned library-level protocol and tooling work. |
| [Roadmap status](ROADMAP_STATUS.md) | Completed milestones, validation baseline and next iteration. |
| [Roadmap QA](ROADMAP_QA.md) | Review gates and quality criteria for roadmap work. |
| [Refactoring checkpoint](REFACTORING_CHECKPOINT.md) | Compatibility and module-boundary review procedure. |
| [Release guide](RELEASING.md) | Versioning, package builds, tags, GitHub Releases and PyPI. |
| [Hardware test report](HARDWARE_TEST_AQ028YCS.md) | Reproducible AQ028YCS/FAM14 hardware findings. |
| [Home Assistant compatibility](HOME_ASSISTANT_COMPATIBILITY.md) | Compatibility contract without a runtime dependency. |
| [Upstream issue triage](UPSTREAM_ISSUE_TRIAGE.md) | Scope decisions for external integration requests. |

### 5. EEP and device correctness

| Document | Purpose |
| --- | --- |
| [D2 migration](D2_EEP_MIGRATION.md) | Migration from the formerly mislabeled D2 decoder. |
| [Eltako special cases](ELTAKO_EEP_SPECIAL_CASES.md) | Manufacturer-specific wire-format exceptions. |

## Suggested reading by task

- **Build an application:** User guide → gateway overview → relevant tutorial → EEP reference.
- **Add a device or EEP:** EEP reference → device catalog → special cases → conformance vectors.
- **Implement a transport:** developer guide → ESP2/ESP3 framing → dispatcher → diagnostics.
- **Work on the roadmap:** roadmap → roadmap status → roadmap QA → refactoring checkpoint.
- **Prepare a release:** developer guide → release guide → complete test and package checks.

The repository intentionally keeps the existing filenames and links stable.
This index provides the structure; it does not introduce a second copy of the
technical documentation.
