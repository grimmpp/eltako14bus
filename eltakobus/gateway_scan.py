"""Portable, passive discovery of serial ports which may host an Eltako gateway.

The scan never opens or writes a port.  It combines pyserial's cross-platform enumeration with
Linux ``/dev/serial/by-id`` links and sysfs descriptors when available.  Device type suggestions
are hints only; an application should use :mod:`eltakobus.gateway_identity` to verify hardware.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, asdict

from .const import GatewayDeviceType

SERIAL_BY_ID_DIR = "/dev/serial/by-id"
SERIAL_BY_PATH_DIR = "/dev/serial/by-path"
DEVICE_GLOBS = ("/dev/ttyUSB*", "/dev/ttyACM*", "/dev/ttyAMA*", "/dev/cu.usbserial-*", "/dev/serial[0-9]*")

_HINTS = (
    ("enocean programmer", (GatewayDeviceType.FAM_USB.value, GatewayDeviceType.USB300.value)),
    ("usb300", (GatewayDeviceType.USB300.value,)),
    ("usb 300", (GatewayDeviceType.USB300.value, GatewayDeviceType.ESP3.value)),
    ("usb 500", (GatewayDeviceType.ESP3.value,)),
    ("enocean", (GatewayDeviceType.ESP3.value, GatewayDeviceType.USB300.value)),
    ("ft2232", (GatewayDeviceType.FGW14_USB.value,)),
    ("ft232", (GatewayDeviceType.FAM14.value, GatewayDeviceType.FGW14_USB.value, GatewayDeviceType.FAM_USB.value)),
    ("cp210", (GatewayDeviceType.ESP3.value,)),
)


@dataclass
class SerialPortInfo:
    device: str
    by_id: str | None = None
    by_path: str | None = None
    manufacturer: str | None = None
    product: str | None = None
    serial_number: str | None = None
    interface: str | None = None
    suggested_device_types: tuple[str, ...] = ()
    hint: str = ""

    def as_dict(self) -> dict:
        result = asdict(self)
        result["suggested_device_types"] = list(self.suggested_device_types)
        return result


def _links(directory):
    result = {}
    try:
        for name in os.listdir(directory):
            result[name] = os.path.realpath(os.path.join(directory, name))
    except OSError:
        pass
    return result


def _pyserial_ports():
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    try:
        return list(list_ports.comports())
    except Exception:
        return []


def _value(port, *names):
    for name in names:
        value = getattr(port, name, None)
        if value and str(value).strip().lower() != "n/a":
            return str(value).strip()
    return None


def _suggest(text):
    normalized = text.lower().replace("_", " ")
    for fragment, types in _HINTS:
        if fragment in normalized:
            return types, f"Possible gateway descriptor match: {fragment}"
    return (), ""


def scan_serial_ports(*, device_globs=DEVICE_GLOBS, by_id_dir=SERIAL_BY_ID_DIR,
                      by_path_dir=SERIAL_BY_PATH_DIR, ports=None) -> list[SerialPortInfo]:
    """Return serial ports and non-authoritative gateway type suggestions.

    ``ports`` is an optional iterable of pyserial-like objects and makes the function fully
    deterministic in unit tests.  No port is opened.
    """
    entries = {}

    def get(device):
        key = os.path.realpath(device)
        return entries.setdefault(key, SerialPortInfo(device=device))

    for pattern in device_globs:
        for device in glob.glob(pattern):
            get(device)
    for port in _pyserial_ports() if ports is None else ports:
        info = get(port.device)
        info.manufacturer = info.manufacturer or _value(port, "manufacturer")
        info.product = info.product or _value(port, "product", "description")
        info.serial_number = info.serial_number or _value(port, "serial_number")
        info.interface = info.interface or _value(port, "interface")
    for name, device in _links(by_id_dir).items():
        info = get(device)
        info.by_id = os.path.join(by_id_dir, name)
        info.interface = info.interface or next((part for part in name.split("-") if part.startswith("if")), None)
    for name, device in _links(by_path_dir).items():
        get(device).by_path = os.path.join(by_path_dir, name)

    for info in entries.values():
        text = " ".join(filter(None, (info.by_id, info.manufacturer, info.product, info.serial_number)))
        info.suggested_device_types, info.hint = _suggest(text)
    return sorted(entries.values(), key=lambda item: item.device)
