"""Explicit, JSON-backed storage for accepted UTE device associations.

The registry is intentionally separate from :mod:`teach_in_session`. Parsing
or receiving a UTE request never changes this registry; an application must
call :meth:`LearnedDeviceRegistry.enroll` after its own policy has accepted a
teach-in response. The registry stores protocol identity and application
metadata only and performs no bus I/O.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .ute import UTECommunication, UTEProfile, UTERequest, UTERequestType


REGISTRY_SCHEMA_VERSION = 1


class DeviceRegistryError(ValueError):
    """A persisted device record is invalid or cannot be used."""


def _sender(value: bytes) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("sender must be bytes-like")
    try:
        result = bytes(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("sender must be bytes-like") from exc
    if len(result) != 4:
        raise ValueError("sender must contain exactly four bytes")
    return result


def _metadata(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise TypeError("metadata must be a mapping")
    result = {str(key): item for key, item in value.items()}
    try:
        json.dumps(result)
    except (TypeError, ValueError) as exc:
        raise TypeError("metadata must contain JSON-serializable values") from exc
    return result


@dataclass(frozen=True, slots=True)
class LearnedDevice:
    """One explicitly accepted UTE association."""

    sender: bytes
    profile: UTEProfile
    channel_count: int
    communication: UTECommunication
    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(self, "sender", _sender(self.sender))
        if not isinstance(self.profile, UTEProfile):
            raise TypeError("profile must be a UTEProfile")
        if isinstance(self.channel_count, bool) or not isinstance(self.channel_count, int):
            raise TypeError("channel_count must be an integer")
        if not 0 <= self.channel_count <= 0xFF:
            raise ValueError("channel_count must be between 0 and 255")
        try:
            communication = UTECommunication(self.communication)
        except (TypeError, ValueError) as exc:
            raise ValueError("communication must be a valid UTECommunication") from exc
        object.__setattr__(self, "communication", communication)
        object.__setattr__(self, "metadata", _metadata(self.metadata))

    @classmethod
    def from_request(
        cls, request: UTERequest, *, metadata: Mapping[str, Any] | None = None
    ) -> "LearnedDevice":
        """Create a record from a teach-in request, without persisting it."""

        if not isinstance(request, UTERequest):
            raise TypeError("request must be a UTERequest")
        if request.request_type is UTERequestType.DELETE:
            raise DeviceRegistryError("a delete request cannot enroll a device")
        return cls(
            sender=request.sender,
            profile=request.profile,
            channel_count=request.channel_count,
            communication=request.communication,
            metadata=metadata or {},
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the stable JSON representation of this record."""

        return {
            "sender": self.sender.hex(),
            "profile": {
                "rorg": self.profile.rorg,
                "function": self.profile.function,
                "type": self.profile.type,
                "manufacturer": self.profile.manufacturer,
            },
            "channel_count": self.channel_count,
            "communication": int(self.communication),
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "LearnedDevice":
        """Parse one persisted record with strict field validation."""

        if not isinstance(value, Mapping):
            raise DeviceRegistryError("device record must be an object")
        try:
            sender = bytes.fromhex(value["sender"])
            profile_data = value["profile"]
            profile = UTEProfile(
                rorg=profile_data["rorg"],
                function=profile_data["function"],
                type=profile_data["type"],
                manufacturer=profile_data["manufacturer"],
            )
            return cls(
                sender=sender,
                profile=profile,
                channel_count=value["channel_count"],
                communication=value["communication"],
                metadata=value.get("metadata", {}),
            )
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise DeviceRegistryError("invalid learned-device record") from exc


class LearnedDeviceRegistry:
    """In-memory registry with optional atomic JSON persistence."""

    def __init__(self, devices: tuple[LearnedDevice, ...] | list[LearnedDevice] = ()) -> None:
        self._devices: dict[tuple[bytes, int], LearnedDevice] = {}
        for device in devices:
            self.add(device)

    @staticmethod
    def _key(sender: bytes, channel_count: int) -> tuple[bytes, int]:
        normalized = _sender(sender)
        if isinstance(channel_count, bool) or not isinstance(channel_count, int):
            raise TypeError("channel_count must be an integer")
        if not 0 <= channel_count <= 0xFF:
            raise ValueError("channel_count must be between 0 and 255")
        return normalized, channel_count

    def add(self, device: LearnedDevice, *, replace: bool = False) -> LearnedDevice:
        """Add an already validated record without bus side effects."""

        if not isinstance(device, LearnedDevice):
            raise TypeError("device must be a LearnedDevice")
        key = self._key(device.sender, device.channel_count)
        if key in self._devices and not replace:
            raise DeviceRegistryError("device association already exists")
        self._devices[key] = device
        return device

    def enroll(
        self,
        request: UTERequest,
        *,
        metadata: Mapping[str, Any] | None = None,
        replace: bool = False,
    ) -> LearnedDevice:
        """Explicitly store an accepted, non-delete UTE request."""

        return self.add(
            LearnedDevice.from_request(request, metadata=metadata), replace=replace
        )

    def get(self, sender: bytes, channel_count: int) -> LearnedDevice | None:
        """Return one association, or ``None`` when it is not enrolled."""

        return self._devices.get(self._key(sender, channel_count))

    def remove(self, sender: bytes, channel_count: int) -> LearnedDevice:
        """Explicitly remove one association and return the removed record."""

        key = self._key(sender, channel_count)
        try:
            return self._devices.pop(key)
        except KeyError as exc:
            raise KeyError("device association is not enrolled") from exc

    def __len__(self) -> int:
        return len(self._devices)

    def __iter__(self):
        return iter(tuple(self._devices.values()))

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": REGISTRY_SCHEMA_VERSION,
            "devices": [device.as_dict() for device in self._devices.values()],
        }

    def save(self, path: str | os.PathLike[str]) -> None:
        """Atomically write the registry as UTF-8 JSON."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=target.name + ".", suffix=".tmp", dir=target.parent
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                json.dump(self.as_dict(), output, indent=2, sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, target)
        except Exception:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            raise

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "LearnedDeviceRegistry":
        """Load and validate a registry file; missing files are not hidden."""

        try:
            with Path(path).open("r", encoding="utf-8") as source:
                document = json.load(source)
        except (OSError, json.JSONDecodeError) as exc:
            raise DeviceRegistryError("cannot read learned-device registry") from exc
        if not isinstance(document, Mapping):
            raise DeviceRegistryError("registry root must be an object")
        if document.get("schema_version") != REGISTRY_SCHEMA_VERSION:
            raise DeviceRegistryError("unsupported learned-device registry schema")
        devices = document.get("devices")
        if not isinstance(devices, list):
            raise DeviceRegistryError("registry devices must be an array")
        try:
            return cls([LearnedDevice.from_dict(item) for item in devices])
        except (DeviceRegistryError, TypeError, ValueError) as exc:
            if isinstance(exc, DeviceRegistryError):
                raise
            raise DeviceRegistryError("invalid learned-device registry") from exc


__all__ = [
    "DeviceRegistryError",
    "LearnedDevice",
    "LearnedDeviceRegistry",
    "REGISTRY_SCHEMA_VERSION",
]
