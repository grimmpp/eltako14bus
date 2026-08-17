"""Tests for explicit, hardware-independent persistent UTE associations."""

import json
import tempfile
import unittest
from pathlib import Path

from eltakobus.device_registry import DeviceRegistryError, LearnedDeviceRegistry
from eltakobus.radio import RadioTelegram
from eltakobus.ute import UTERequest, UTERequestType


def request(request_type=UTERequestType.TEACH_IN) -> UTERequest:
    telegram = RadioTelegram(
        rorg=0xD4,
        payload=bytes.fromhex("000146000e01d2"),
        sender=bytes.fromhex("01020304"),
        status=0,
    )
    decoded = UTERequest.from_telegram(telegram)
    return UTERequest(
        profile=decoded.profile,
        sender=decoded.sender,
        channel_count=decoded.channel_count,
        communication=decoded.communication,
        response_expected=decoded.response_expected,
        request_type=request_type,
        status=decoded.status,
    )


class DeviceRegistryTest(unittest.TestCase):
    def test_enrollment_is_explicit_and_round_trips(self):
        registry = LearnedDeviceRegistry()
        device = registry.enroll(request(), metadata={"room": "office"})

        self.assertEqual(1, len(registry))
        self.assertIs(registry.get(device.sender, device.channel_count), device)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "devices.json"
            registry.save(path)
            loaded = LearnedDeviceRegistry.load(path)
        restored = loaded.get(bytes.fromhex("01020304"), 1)
        self.assertIsNotNone(restored)
        self.assertEqual("D2-01-0E", restored.profile.eep)
        self.assertEqual("office", restored.metadata["room"])

    def test_duplicate_and_delete_requests_are_fail_closed(self):
        registry = LearnedDeviceRegistry()
        registry.enroll(request())
        with self.assertRaises(DeviceRegistryError):
            registry.enroll(request())
        with self.assertRaises(DeviceRegistryError):
            registry.enroll(request(UTERequestType.DELETE))

    def test_replace_remove_and_schema_validation(self):
        registry = LearnedDeviceRegistry()
        registry.enroll(request(), metadata={"label": "old"})
        registry.enroll(request(), metadata={"label": "new"}, replace=True)
        self.assertEqual(
            "new", registry.get(bytes.fromhex("01020304"), 1).metadata["label"]
        )
        removed = registry.remove(bytes.fromhex("01020304"), 1)
        self.assertEqual(bytes.fromhex("01020304"), removed.sender)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invalid.json"
            path.write_text(
                json.dumps({"schema_version": 999, "devices": []}), encoding="utf-8"
            )
            with self.assertRaises(DeviceRegistryError):
                LearnedDeviceRegistry.load(path)

    def test_metadata_must_be_json_serializable(self):
        with self.assertRaises(TypeError):
            LearnedDeviceRegistry().enroll(request(), metadata={"bad": object()})


if __name__ == "__main__":
    unittest.main()
