"""Pure helpers for interpreting gateway identity responses.

Reading an identity can interrupt an active serial consumer, so this module keeps parsing and
request construction separate.  Applications can use these helpers in their own controlled
probe, or with the existing serial interface after it has been stopped safely.
"""
from __future__ import annotations

from .const import GatewayDeviceType, baud_rate_for
from .message import ESP2Message

FAM_USB_BASE_ID_REQUEST = bytes.fromhex("AB 58 00 00 00 00 00 00 00 00 00")
VERSION_RESPONSE_LENGTH = 32


def format_id(value) -> str | None:
    try:
        data = bytes(value)
    except (TypeError, ValueError):
        return None
    return "-".join(f"{byte:02X}" for byte in data) if len(data) == 4 else None


def parse_version_response(response_data) -> dict:
    """Parse the 32-byte ESP3 ``CO_RD_VERSION`` response payload."""
    try:
        data = bytes(response_data or b"")
    except (TypeError, ValueError):
        return {}
    if len(data) < VERSION_RESPONSE_LENGTH:
        return {}

    def version(part):
        return ".".join(str(byte) for byte in part)

    return {
        "app_version": version(data[0:4]),
        "api_version": version(data[4:8]),
        "chip_id": format_id(data[8:12]),
        "chip_version": version(data[12:16]),
        "app_description": data[16:32].split(b"\0", 1)[0].decode("ascii", "replace").strip() or None,
    }


def fam_usb_base_id_request() -> ESP2Message:
    """Build the ESP2 request used by FAM-USB identity probes."""
    return ESP2Message(FAM_USB_BASE_ID_REQUEST)


def parse_fam_usb_base_id(response) -> str | None:
    """Extract the four-byte base id from an ESP2 FAM-USB response."""
    body = getattr(response, "body", None)
    return format_id(body[2:6]) if body is not None and len(body) >= 6 else None


def identity_capabilities(device_type) -> dict:
    """Describe what can be learned without guessing or opening the port twice."""
    kind = GatewayDeviceType.find(device_type)
    return {
        "device_type": kind.value if kind else str(device_type),
        "baud_rate": baud_rate_for(kind),
        "is_bus_gateway": GatewayDeviceType.is_bus_gateway(kind),
        "can_read_base_id": kind in (GatewayDeviceType.FAM_USB, GatewayDeviceType.USB300, GatewayDeviceType.ESP3),
        "can_read_chip_id": kind in (GatewayDeviceType.USB300, GatewayDeviceType.ESP3),
    }


async def async_read_identity(bus, device_type, *, retries=1, timeout=1.0) -> dict:
    """Read the identity supported by an already-owned ESP2 bus interface.

    Only FAM-USB has a native ESP2 identity request here.  FAM14/FGW14-USB identify the
    installation bus rather than the adapter itself, and ESP3 identity requests depend on the
    optional ESP3 transport.  Keeping this function bound to an existing ``BusInterface`` avoids
    opening a second handle to an active serial port.
    """
    kind = GatewayDeviceType.find(device_type)
    if kind is not GatewayDeviceType.FAM_USB:
        return {"device_type": kind.value if kind else str(device_type),
                "capabilities": identity_capabilities(kind)}
    response = await bus.exchange(fam_usb_base_id_request(), ESP2Message,
                                  retries=retries, timeout=timeout)
    base_id = parse_fam_usb_base_id(response)
    return {"device_type": kind.value, "base_id": base_id} if base_id else {}
