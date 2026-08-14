"""Protocol and gateway constants shared by applications using :mod:`eltakobus`.

This module intentionally contains no Home Assistant configuration or UI constants.  Those
belong to an integration, while gateway kinds and serial settings are useful to every client.
"""
from enum import Enum


class GatewayDeviceType(str, Enum):
    """Known gateway families and their stable configuration names."""

    FAM14 = "fam14"
    FGW14_USB = "fgw14usb"
    FAM_USB = "fam-usb"
    USB300 = "enocean-usb300"
    ESP3 = "esp3-gateway"
    LAN = "lan"
    LAN_ESP2 = "lan-gw-esp2"
    MGW_LAN = "mgw-lan"
    EUL_LAN = "eul_lan"

    @classmethod
    def find(cls, value):
        if isinstance(value, cls):
            return value
        value = str(value).lower()
        return next((item for item in cls if item.value == value), None)

    @classmethod
    def is_bus_gateway(cls, value) -> bool:
        return cls.find(value) in (cls.FAM14, cls.FGW14_USB)

    @classmethod
    def is_transceiver(cls, value) -> bool:
        return cls.find(value) in (cls.FAM_USB, cls.USB300, cls.ESP3, cls.LAN, cls.LAN_ESP2, cls.MGW_LAN, cls.EUL_LAN)

    @classmethod
    def is_esp2_gateway(cls, value) -> bool:
        return cls.find(value) in (cls.FAM14, cls.FGW14_USB, cls.FAM_USB, cls.LAN_ESP2)


BAUD_RATE_DEVICE_TYPE_MAPPING = {
    GatewayDeviceType.FAM14: 57600,
    GatewayDeviceType.FGW14_USB: 57600,
    GatewayDeviceType.FAM_USB: 9600,
    GatewayDeviceType.USB300: 57600,
    GatewayDeviceType.ESP3: 57600,
}

DEFAULT_BAUD_RATE = 57600
DEFAULT_MESSAGE_DELAY = 0.01
DEFAULT_RECONNECTION_TIMEOUT = 10.0
DEFAULT_TCP_PORT = 5000


def baud_rate_for(device_type, default: int = 0) -> int:
    """Return the recommended serial baud rate, or ``default`` for non-serial gateways."""
    return BAUD_RATE_DEVICE_TYPE_MAPPING.get(GatewayDeviceType.find(device_type), default)
