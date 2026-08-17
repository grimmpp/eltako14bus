"""Data-driven conformance checks with explicit vector provenance.

The executable vectors in this milestone come only from existing repository
captures and regression fixtures.  Placeholder records describe missing
official vectors but deliberately carry no protocol bytes and are never
silently treated as conformance evidence.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest

from eltakobus.eep_schema import d2_compatibility_adapter
from eltakobus.esp2_frame import ESP2FrameParser
from eltakobus.esp3_frame import ESP3Frame, ESP3FrameParser
from eltakobus.message import ESP2Message, VLDMessage, prettify


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RESOURCE_ROOT = Path(__file__).with_name("resources") / "conformance"
EXECUTABLE_MATERIAL_KEYS = frozenset({
    "wire_hex", "payload_hex", "data_hex", "optional_hex",
})
REPOSITORY_PROVENANCE = frozenset({
    "repository_capture", "repository_regression",
})


def _load_json(path: Path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _load_suites():
    manifest = _load_json(RESOURCE_ROOT / "manifest.json")
    return manifest, [
        _load_json(RESOURCE_ROOT / entry["file"])
        for entry in manifest["suites"]
    ]


class ConformanceVectorResourceTest(unittest.TestCase):
    """Guard provenance so local fixtures cannot masquerade as official data."""

    def test_manifest_and_vector_contract(self):
        manifest, suites = _load_suites()
        self.assertEqual(1, manifest["format_version"])
        self.assertEqual(
            [entry["kind"] for entry in manifest["suites"]],
            [suite["kind"] for suite in suites],
        )

        identifiers = set()
        for suite in suites:
            self.assertEqual(1, suite["format_version"])
            self.assertTrue(suite["vectors"])
            for vector in suite["vectors"]:
                with self.subTest(vector=vector["id"]):
                    self.assertNotIn(vector["id"], identifiers)
                    identifiers.add(vector["id"])
                    self.assertIn(vector["status"], {"executable", "placeholder"})
                    provenance = vector["provenance"]

                    if vector["status"] == "placeholder":
                        self.assertEqual("official_specification", provenance["kind"])
                        self.assertTrue(vector.get("gap"))
                        self.assertTrue(EXECUTABLE_MATERIAL_KEYS.isdisjoint(vector))
                        continue

                    self.assertIn(provenance["kind"],
                                  REPOSITORY_PROVENANCE | {"official_specification"})
                    if provenance["kind"] in REPOSITORY_PROVENANCE:
                        source = REPOSITORY_ROOT / provenance["source"]
                        self.assertTrue(source.is_file(), source)
                    else:
                        for key in ("document", "revision", "location",
                                    "transcribed_by", "reviewed_by"):
                            value = provenance.get(key)
                            self.assertTrue(value, key)
                            self.assertNotEqual("TBD", str(value).strip().upper(), key)
                        self.assertNotEqual(provenance["transcribed_by"],
                                            provenance["reviewed_by"])

    def test_placeholders_make_current_official_coverage_explicit(self):
        _, suites = _load_suites()
        placeholders = [
            vector for suite in suites for vector in suite["vectors"]
            if vector["status"] == "placeholder"
        ]
        official_executable = [
            vector for suite in suites for vector in suite["vectors"]
            if vector["status"] == "executable"
            and vector["provenance"]["kind"] == "official_specification"
        ]
        self.assertGreaterEqual(len(placeholders), 1)
        self.assertEqual([], official_executable)


class ESP2ConformanceVectorTest(unittest.TestCase):
    """Replay every repository ESP2 vector through old and new parser APIs."""

    @classmethod
    def setUpClass(cls):
        _, suites = _load_suites()
        cls.vectors = next(s for s in suites if s["kind"] == "esp2")["vectors"]

    def test_esp2_round_trips_and_every_two_chunk_split(self):
        for vector in self.vectors:
            if vector["status"] != "executable":
                continue
            with self.subTest(vector=vector["id"]):
                wire = bytes.fromhex(vector["wire_hex"])
                legacy = ESP2Message.parse(wire)
                self.assertEqual(wire, legacy.serialize())
                self.assertEqual(
                    vector["expected_message_type"],
                    type(prettify(legacy)).__name__,
                )

                for split in range(len(wire) + 1):
                    parser = ESP2FrameParser()
                    frames = parser.feed(wire[:split]) + parser.feed(wire[split:])
                    self.assertEqual([wire], frames, (vector["id"], split))
                    self.assertEqual((), parser.errors)


class ESP3ConformanceVectorTest(unittest.TestCase):
    """Verify exact frame encoding and arbitrary two-chunk stream boundaries."""

    @classmethod
    def setUpClass(cls):
        _, suites = _load_suites()
        cls.vectors = next(s for s in suites if s["kind"] == "esp3")["vectors"]

    def test_esp3_round_trips_and_every_two_chunk_split(self):
        for vector in self.vectors:
            if vector["status"] != "executable":
                continue
            with self.subTest(vector=vector["id"]):
                wire = bytes.fromhex(vector["wire_hex"])
                frame = ESP3Frame.from_bytes(wire)
                self.assertEqual(vector["packet_type"], frame.packet_type)
                self.assertEqual(bytes.fromhex(vector["data_hex"]), frame.data)
                self.assertEqual(bytes.fromhex(vector["optional_hex"]), frame.optional)
                self.assertEqual(wire, bytes(frame))

                for split in range(len(wire) + 1):
                    parser = ESP3FrameParser()
                    frames = parser.feed(wire[:split]) + parser.feed(wire[split:])
                    self.assertEqual([frame], frames, (vector["id"], split))
                    self.assertFalse(parser.errors)


class EEPSchemaConformanceVectorTest(unittest.TestCase):
    """Keep declarative D2 schemas equal to the established public decoders."""

    @classmethod
    def setUpClass(cls):
        _, suites = _load_suites()
        cls.vectors = next(
            s for s in suites if s["kind"] == "eep_schema"
        )["vectors"]

    def test_schema_values_and_legacy_parity(self):
        for vector in self.vectors:
            if vector["status"] != "executable":
                continue
            with self.subTest(vector=vector["id"]):
                adapter = d2_compatibility_adapter(vector["eep"])
                message = VLDMessage(bytes(4), 0,
                                     bytes.fromhex(vector["payload_hex"]))
                legacy, decoded = adapter.decode(message)

                self.assertIsNotNone(legacy)
                self.assertEqual((), adapter.compatibility_errors(message))
                for field_name, expected in vector["expected_values"].items():
                    actual = decoded[field_name].value
                    if isinstance(expected, float):
                        self.assertAlmostEqual(expected, actual, places=9)
                    else:
                        self.assertEqual(expected, actual)
                for field_name, expected in vector.get("expected_status", {}).items():
                    self.assertEqual(expected, decoded[field_name].status.value)


if __name__ == "__main__":
    unittest.main()
