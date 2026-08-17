"""Generic EnOcean Universal Teach-In (UTE) telegram models.

UTE uses RORG ``0xD4`` and a seven-byte payload to describe an EEP and the
requested teach-in operation.  This module only parses and builds telegrams;
it never changes application state and never sends or accepts a request.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Optional

from .radio import RadioTelegram, TelegramDirection


UTE_RORG = 0xD4
UTE_QUERY_COMMAND = 0x00
UTE_RESPONSE_COMMAND = 0x01
UTE_PAYLOAD_LENGTH = 7
UTE_BROADCAST = b"\xff\xff\xff\xff"


class UTEParseError(ValueError):
    """A radio telegram is not a valid UTE query or response."""


class UTECommunication(IntEnum):
    """Communication direction used during normal EEP operation."""

    UNIDIRECTIONAL = 0
    BIDIRECTIONAL = 1


class UTERequestType(IntEnum):
    """Operation requested by an EEP Teach-In Query."""

    TEACH_IN = 0
    DELETE = 1
    NOT_SPECIFIC = 2


class UTEResponseCode(IntEnum):
    """Result carried by an EEP Teach-In Response."""

    NOT_ACCEPTED = 0
    TEACH_IN_ACCEPTED = 1
    DELETE_ACCEPTED = 2
    EEP_NOT_SUPPORTED = 3


def _integer(name: str, value: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if not minimum <= value <= maximum:
        raise ValueError(
            "%s must be between %d and %d" % (name, minimum, maximum)
        )
    return value


def _identifier(name: str, value: bytes) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("%s must be bytes-like" % name)
    try:
        result = bytes(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("%s must be bytes-like" % name) from exc
    if len(result) != 4:
        raise ValueError("%s must contain exactly four bytes" % name)
    return result


def _enum(name: str, enum_type: type[IntEnum], value: IntEnum) -> IntEnum:
    if isinstance(value, bool):
        raise TypeError("%s must not be a boolean" % name)
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid %s: %r" % (name, value)) from exc


@dataclass(frozen=True, slots=True)
class UTEProfile:
    """EEP and manufacturer information transported by UTE."""

    rorg: int
    function: int
    type: int
    manufacturer: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "rorg", _integer("rorg", self.rorg, 0, 0xFF))
        object.__setattr__(
            self, "function", _integer("function", self.function, 0, 0xFF)
        )
        object.__setattr__(self, "type", _integer("type", self.type, 0, 0xFF))
        object.__setattr__(
            self,
            "manufacturer",
            _integer("manufacturer", self.manufacturer, 0, 0x7FF),
        )

    @property
    def eep(self) -> str:
        """Return the canonical ``RORG-FUNC-TYPE`` profile identifier."""

        return "%02X-%02X-%02X" % (self.rorg, self.function, self.type)


def _decode_common(telegram: RadioTelegram) -> tuple[bytes, UTEProfile, int]:
    if not isinstance(telegram, RadioTelegram):
        raise TypeError("telegram must be a RadioTelegram")
    if telegram.rorg != UTE_RORG:
        raise UTEParseError("telegram is not UTE RORG 0xD4")
    payload = telegram.payload
    if len(payload) != UTE_PAYLOAD_LENGTH:
        raise UTEParseError("UTE payload must contain exactly seven bytes")
    if payload[3] & 0xF8:
        raise UTEParseError("reserved UTE manufacturer bits must be zero")
    manufacturer = payload[2] | ((payload[3] & 0x07) << 8)
    profile = UTEProfile(
        rorg=payload[6],
        function=payload[5],
        type=payload[4],
        manufacturer=manufacturer,
    )
    return payload, profile, payload[1]


def _encode_common(profile: UTEProfile, channel_count: int) -> bytes:
    return bytes((
        channel_count,
        profile.manufacturer & 0xFF,
        (profile.manufacturer >> 8) & 0x07,
        profile.type,
        profile.function,
        profile.rorg,
    ))


def _outbound_telegram(
    *,
    payload: bytes,
    sender: bytes,
    destination: bytes,
    status: int,
) -> RadioTelegram:
    return RadioTelegram(
        rorg=UTE_RORG,
        payload=payload,
        sender=sender,
        status=status,
        direction=TelegramDirection.OUTGOING,
        destination=destination,
        subtelegram_count=3,
        rssi_dbm=-255,
        security_level=0,
    )


@dataclass(frozen=True, slots=True)
class UTERequest:
    """Decoded EEP Teach-In Query (UTE command ``0x0``)."""

    profile: UTEProfile
    sender: bytes
    channel_count: int
    communication: UTECommunication
    response_expected: bool
    request_type: UTERequestType
    status: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.profile, UTEProfile):
            raise TypeError("profile must be a UTEProfile")
        object.__setattr__(self, "sender", _identifier("sender", self.sender))
        object.__setattr__(
            self,
            "channel_count",
            _integer("channel_count", self.channel_count, 0, 0xFF),
        )
        object.__setattr__(
            self,
            "communication",
            _enum("communication", UTECommunication, self.communication),
        )
        if not isinstance(self.response_expected, bool):
            raise TypeError("response_expected must be a boolean")
        object.__setattr__(
            self,
            "request_type",
            _enum("request_type", UTERequestType, self.request_type),
        )
        object.__setattr__(
            self, "status", _integer("status", self.status, 0, 0xFF)
        )

    @property
    def channel(self) -> int:
        """Compatibility shorthand for :attr:`channel_count`."""

        return self.channel_count

    @property
    def bidirectional(self) -> bool:
        """Whether regular EEP communication is bidirectional."""

        return self.communication is UTECommunication.BIDIRECTIONAL

    @property
    def teach_in(self) -> bool:
        """Whether the request may establish a teach-in association."""

        return self.request_type is not UTERequestType.DELETE

    @property
    def delete(self) -> bool:
        """Whether the request explicitly asks to delete an association."""

        return self.request_type is UTERequestType.DELETE

    @classmethod
    def from_telegram(cls, telegram: RadioTelegram) -> "UTERequest":
        """Decode and strictly validate an EEP Teach-In Query."""

        payload, profile, channel_count = _decode_common(telegram)
        command = payload[0] & 0x0F
        if command != UTE_QUERY_COMMAND:
            raise UTEParseError("UTE telegram is not an EEP Teach-In Query")
        request_value = (payload[0] >> 4) & 0x03
        if request_value == 0x03:
            raise UTEParseError("UTE request type 0b11 is reserved")
        return cls(
            profile=profile,
            sender=telegram.sender,
            channel_count=channel_count,
            communication=UTECommunication((payload[0] >> 7) & 0x01),
            response_expected=not bool(payload[0] & 0x40),
            request_type=UTERequestType(request_value),
            status=telegram.status,
        )

    def to_telegram(self, destination: bytes = UTE_BROADCAST) -> RadioTelegram:
        """Build an outbound EEP Teach-In Query.

        Building a query does not transmit it.  The caller remains responsible
        for putting the device into the appropriate teach-in state first.
        """

        target = _identifier("destination", destination)
        control = (
            (int(self.communication) << 7)
            | ((not self.response_expected) << 6)
            | (int(self.request_type) << 4)
            | UTE_QUERY_COMMAND
        )
        payload = bytes((control,)) + _encode_common(
            self.profile, self.channel_count
        )
        return _outbound_telegram(
            payload=payload,
            sender=self.sender,
            destination=target,
            status=self.status,
        )

    def build_response(
        self,
        sender: bytes,
        response_code: UTEResponseCode,
        *,
        status: int = 0,
    ) -> "UTEResponse":
        """Create, but do not send, a response addressed to this requester."""

        if isinstance(response_code, bool):
            raise TypeError("response_code must not be a boolean")
        try:
            selected = UTEResponseCode(response_code)
        except (TypeError, ValueError) as exc:
            raise ValueError("response_code must be a valid UTEResponseCode") from exc
        if (
            self.request_type is UTERequestType.TEACH_IN
            and selected is UTEResponseCode.DELETE_ACCEPTED
        ):
            raise ValueError("a teach-in request cannot accept deletion")
        if (
            self.request_type is UTERequestType.DELETE
            and selected is UTEResponseCode.TEACH_IN_ACCEPTED
        ):
            raise ValueError("a deletion request cannot accept teach-in")

        return UTEResponse(
            profile=self.profile,
            sender=sender,
            destination=self.sender,
            channel_count=self.channel_count,
            response_code=selected,
            status=status,
        )


@dataclass(frozen=True, slots=True)
class UTEResponse:
    """Decoded or generated EEP Teach-In Response (UTE command ``0x1``)."""

    profile: UTEProfile
    sender: bytes
    destination: Optional[bytes]
    channel_count: int
    response_code: UTEResponseCode
    status: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.profile, UTEProfile):
            raise TypeError("profile must be a UTEProfile")
        object.__setattr__(self, "sender", _identifier("sender", self.sender))
        if self.destination is not None:
            object.__setattr__(
                self, "destination", _identifier("destination", self.destination)
            )
        object.__setattr__(
            self,
            "channel_count",
            _integer("channel_count", self.channel_count, 0, 0xFF),
        )
        object.__setattr__(
            self,
            "response_code",
            _enum("response_code", UTEResponseCode, self.response_code),
        )
        object.__setattr__(
            self, "status", _integer("status", self.status, 0, 0xFF)
        )

    @property
    def accepted(self) -> bool:
        """Whether the response confirms teach-in or deletion success."""

        return self.response_code in (
            UTEResponseCode.TEACH_IN_ACCEPTED,
            UTEResponseCode.DELETE_ACCEPTED,
        )

    @classmethod
    def from_telegram(cls, telegram: RadioTelegram) -> "UTEResponse":
        """Decode and strictly validate an EEP Teach-In Response."""

        payload, profile, channel_count = _decode_common(telegram)
        if payload[0] & 0x40:
            raise UTEParseError("reserved UTE response bit must be zero")
        if not payload[0] & 0x80:
            raise UTEParseError("UTE response must use bidirectional communication")
        if payload[0] & 0x0F != UTE_RESPONSE_COMMAND:
            raise UTEParseError("UTE telegram is not an EEP Teach-In Response")
        return cls(
            profile=profile,
            sender=telegram.sender,
            destination=telegram.destination,
            channel_count=channel_count,
            response_code=UTEResponseCode((payload[0] >> 4) & 0x03),
            status=telegram.status,
        )

    def to_telegram(self, destination: Optional[bytes] = None) -> RadioTelegram:
        """Build an outbound response addressed to the original requester."""

        target = self.destination if destination is None else destination
        if target is None:
            raise ValueError(
                "destination is required when the parsed telegram had no optional data"
            )
        target = _identifier("destination", target)
        control = (
            0x80 | (int(self.response_code) << 4) | UTE_RESPONSE_COMMAND
        )
        payload = bytes((control,)) + _encode_common(
            self.profile, self.channel_count
        )
        return _outbound_telegram(
            payload=payload,
            sender=self.sender,
            destination=target,
            status=self.status,
        )


__all__ = [
    "UTE_BROADCAST",
    "UTECommunication",
    "UTEParseError",
    "UTEProfile",
    "UTERequest",
    "UTERequestType",
    "UTEResponse",
    "UTEResponseCode",
    "UTE_QUERY_COMMAND",
    "UTE_RESPONSE_COMMAND",
    "UTE_RORG",
]
