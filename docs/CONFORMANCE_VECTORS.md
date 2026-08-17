# Conformance vectors

The data-driven tests in `tests/conformance_vector_test.py` exercise ESP2,
ESP3 and selected declarative EEP schemas without adding a runtime dependency.
Their resources live in `tests/resources/conformance`.

## Current evidence level

The framework intentionally distinguishes protocol conformance from ordinary
regression coverage. At present, the executable records are derived only from
data that was already in this repository:

- an ESP2 FAM14 poll from the passive hardware report;
- existing ESP2 and ESP3 regression fixtures; and
- existing D2 schema-parity fixtures.

These records prove compatibility and stable round trips. They are **not
official specification vectors**. The current number of executable official
vectors is therefore zero. Placeholder records make that gap machine-readable
instead of implying a stronger assurance level.

## Resource format

`manifest.json` lists the suites. Each suite contains records with a globally
unique `id`, a `status` and a `provenance` object.

An executable repository vector uses one of these provenance kinds:

- `repository_capture`: bytes captured by this project's hardware tooling;
- `repository_regression`: bytes already represented by an existing test.

Its `source` must be a repository-relative path that exists. ESP2 and ESP3
records contain exact wire bytes as lowercase hexadecimal. EEP records contain
the VLD payload and expected public field values.

A missing authoritative vector uses `status: placeholder`,
`provenance.kind: official_specification` and a concrete `gap`. Placeholders
must not contain wire or payload bytes, so they can never run accidentally.

## Adding an official vector

Use the applicable EnOcean Alliance or Eltako specification, not source code
from another implementation. Transcribe the example directly into the
appropriate JSON suite and record:

- the exact document title and revision;
- the page, table, section or example identifier in `location`;
- the person or process that transcribed it in `transcribed_by`;
- a different reviewer in `reviewed_by`.

Then change the record to `status: executable` and add the expected decoded
sections or values. The resource-contract test rejects an official executable
record without all of this provenance and independent review metadata.

Do not copy parser tests, generated arrays or source-code constants from
third-party implementations. They can be useful comparison targets, but they
are not authoritative protocol evidence.

## What the tests prove

For every executable ESP2 vector, the suite verifies:

- legacy `ESP2Message` parse/serialize identity;
- semantic `prettify()` classification; and
- the incremental parser at every possible two-chunk boundary.

For every executable ESP3 vector, it verifies:

- exact packet type, DATA and OPTIONAL_DATA sections;
- CRC-protected parse/serialize identity; and
- the incremental parser at every possible two-chunk boundary.

For each EEP schema vector, it verifies:

- equality between the declarative schema and the established EEP decoder;
- selected physical values; and
- reserved or unmapped status where specified.

## Known gaps

- No executable vector is yet tied to a reviewed official document revision.
- ESP2 capture diversity is limited to FAM14 poll traffic; discovery is a
  repository regression fixture, not a hardware capture.
- ESP3 has no hardware capture in the repository resource set.
- ESP3 coverage lacks official vectors for commands, responses, events,
  RADIO_ERP1, malformed CRCs and maximum lengths.
- EEP official vectors are missing for normal, boundary, unavailable,
  reserved, overrange and underrange values.
- The schema implementation also supports D2-00-01 variants A-E, but this
  resource set does not yet contain D2-00-01 conformance records. Add normal,
  boundary, reserved-bit and vendor-extension vectors for every direction
  before treating that profile as vector-covered.
- Secure teach-in, UTE and memory-session vectors are outside this milestone.

Until these gaps are closed, describe this suite as a provenance-controlled
conformance-vector framework with repository regression vectors, not as full
ESP2, ESP3 or EEP certification.
