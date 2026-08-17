"""Dependency-free semantic packet models layered above ESP3 framing.

The framing layer deliberately preserves bytes without interpreting them.
This module adds the small amount of packet-type-specific meaning needed by
applications and transports while retaining unknown packet types and numeric
response/event codes for diagnostics and replay.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Union

from .esp3_frame import ESP3Frame, ESP3PacketType
from .radio import RadioTelegram, TelegramDirection


class ESP3PacketError(ValueError):
    """An ESP3 frame is valid on the wire but malformed for its packet type."""


class ESP3ReturnCode(IntEnum):
    """Standard ESP3 response return codes."""

    OK = 0x00
    ERROR = 0x01
    NOT_SUPPORTED = 0x02
    WRONG_PARAMETER = 0x03
    OPERATION_DENIED = 0x04


class ESP3EventCode(IntEnum):
    """Known ESP3 event codes; models retain unknown codes as integers."""

    SMART_ACK_RECLAIM_NOT_SUCCESSFUL = 0x01
    SMART_ACK_CONFIRM_LEARN = 0x02
    SMART_ACK_LEARN_ACK = 0x03
    READY = 0x04
    SECURE_DEVICES = 0x05


def _byte(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if not 0 <= value <= 0xFF:
        raise ValueError("%s must be between 0 and 255" % name)
    return value


def _bytes(name: str, value: object) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("%s must be bytes-like" % name)
    try:
        return bytes(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise TypeError("%s must be bytes-like" % name) from exc


@dataclass(frozen=True, slots=True)
class ESP3Response:
    """A response packet whose first DATA byte is the return code."""

    return_code: int
    data: bytes = b""
    optional_data: bytes = b""
    raw_frame: ESP3Frame | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "return_code", _byte("return_code", self.return_code))
        object.__setattr__(self, "data", _bytes("data", self.data))
        object.__setattr__(
            self, "optional_data", _bytes("optional_data", self.optional_data)
        )
        if self.raw_frame is not None:
            if not isinstance(self.raw_frame, ESP3Frame):
                raise TypeError("raw_frame must be an ESP3Frame")
            expected = ESP3Frame(
                ESP3PacketType.RESPONSE,
                bytes((self.return_code,)) + self.data,
                self.optional_data,
            )
            if self.raw_frame != expected:
                raise ValueError("raw_frame does not match ESP3 response fields")

    @property
    def successful(self) -> bool:
        """Whether the transceiver returned the standard success code."""

        return self.return_code == ESP3ReturnCode.OK

    @property
    def known_return_code(self) -> ESP3ReturnCode | None:
        """Return the enum value, or ``None`` for a future/vendor code."""

        try:
            return ESP3ReturnCode(self.return_code)
        except ValueError:
            return None

    def to_frame(self) -> ESP3Frame:
        """Encode this semantic response as an ESP3 frame."""

        return ESP3Frame(
            ESP3PacketType.RESPONSE,
            bytes((self.return_code,)) + self.data,
            self.optional_data,
        )


@dataclass(frozen=True, slots=True)
class ESP3Event:
    """An event packet whose first DATA byte identifies the event."""

    event_code: int
    data: bytes = b""
    optional_data: bytes = b""
    raw_frame: ESP3Frame | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_code", _byte("event_code", self.event_code))
        object.__setattr__(self, "data", _bytes("data", self.data))
        object.__setattr__(
            self, "optional_data", _bytes("optional_data", self.optional_data)
        )
        if self.raw_frame is not None:
            if not isinstance(self.raw_frame, ESP3Frame):
                raise TypeError("raw_frame must be an ESP3Frame")
            expected = ESP3Frame(
                ESP3PacketType.EVENT,
                bytes((self.event_code,)) + self.data,
                self.optional_data,
            )
            if self.raw_frame != expected:
                raise ValueError("raw_frame does not match ESP3 event fields")

    @property
    def known_event_code(self) -> ESP3EventCode | None:
        """Return the enum value, or ``None`` for a future/vendor event."""

        try:
            return ESP3EventCode(self.event_code)
        except ValueError:
            return None

    def to_frame(self) -> ESP3Frame:
        """Encode this semantic event as an ESP3 frame."""

        return ESP3Frame(
            ESP3PacketType.EVENT,
            bytes((self.event_code,)) + self.data,
            self.optional_data,
        )


@dataclass(frozen=True, slots=True)
class ESP3Command:
    """An outbound ESP3 command with an explicit packet type and code."""

    command_code: int
    data: bytes = b""
    optional_data: bytes = b""
    packet_type: int = ESP3PacketType.COMMON_COMMAND

    def __post_init__(self) -> None:
        object.__setattr__(self, "command_code", _byte("command_code", self.command_code))
        object.__setattr__(self, "packet_type", _byte("packet_type", self.packet_type))
        object.__setattr__(self, "data", _bytes("data", self.data))
        object.__setattr__(
            self, "optional_data", _bytes("optional_data", self.optional_data)
        )
        if self.packet_type in (
            ESP3PacketType.RADIO_ERP1,
            ESP3PacketType.RESPONSE,
            ESP3PacketType.EVENT,
        ):
            raise ValueError("packet_type is not command-bearing")

    def to_frame(self) -> ESP3Frame:
        """Encode command code, parameters and optional data losslessly."""

        return ESP3Frame(
            self.packet_type,
            bytes((self.command_code,)) + self.data,
            self.optional_data,
        )


@dataclass(frozen=True, slots=True)
class UnknownESP3Packet:
    """Lossless representation for packet types unknown to this library."""

    raw_frame: ESP3Frame

    def __post_init__(self) -> None:
        if not isinstance(self.raw_frame, ESP3Frame):
            raise TypeError("raw_frame must be an ESP3Frame")

    @property
    def packet_type(self) -> int:
        return self.raw_frame.packet_type

    @property
    def data(self) -> bytes:
        return self.raw_frame.data

    @property
    def optional_data(self) -> bytes:
        return self.raw_frame.optional_data

    def to_frame(self) -> ESP3Frame:
        return self.raw_frame


ESP3SemanticPacket = Union[
    RadioTelegram, ESP3Response, ESP3Event, ESP3Command, UnknownESP3Packet
]


def decode_esp3_packet(
    frame: ESP3Frame,
    *,
    direction: TelegramDirection = TelegramDirection.INCOMING,
) -> ESP3SemanticPacket:
    """Decode one frame without discarding unknown packet types or codes."""

    if not isinstance(frame, ESP3Frame):
        raise TypeError("frame must be an ESP3Frame")

    if frame.packet_type == ESP3PacketType.RADIO_ERP1:
        try:
            return RadioTelegram.from_esp3_fields(
                frame.data, frame.optional_data, direction=direction
            )
        except (TypeError, ValueError) as exc:
            raise ESP3PacketError("malformed RADIO_ERP1 packet: %s" % exc) from exc

    if frame.packet_type == ESP3PacketType.RESPONSE:
        if not frame.data:
            raise ESP3PacketError("ESP3 RESPONSE packet has no return code")
        return ESP3Response(
            frame.data[0], frame.data[1:], frame.optional_data, frame
        )

    if frame.packet_type == ESP3PacketType.EVENT:
        if not frame.data:
            raise ESP3PacketError("ESP3 EVENT packet has no event code")
        return ESP3Event(frame.data[0], frame.data[1:], frame.optional_data, frame)

    if frame.packet_type == ESP3PacketType.COMMON_COMMAND:
        if not frame.data:
            raise ESP3PacketError("ESP3 COMMON_COMMAND packet has no command code")
        return ESP3Command(
            frame.data[0], frame.data[1:], frame.optional_data, frame.packet_type
        )

    return UnknownESP3Packet(frame)


__all__ = [
    "ESP3PacketError",
    "ESP3ReturnCode",
    "ESP3EventCode",
    "ESP3Response",
    "ESP3Event",
    "ESP3Command",
    "UnknownESP3Packet",
    "ESP3SemanticPacket",
    "decode_esp3_packet",
]
