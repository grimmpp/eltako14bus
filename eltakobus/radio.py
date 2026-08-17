"""Dependency-free native representation of ESP3 RADIO_ERP1 telegrams.

The legacy message classes in :mod:`eltakobus.message` model the fixed-size
ESP2 wire format.  ``RadioTelegram`` complements them with an immutable model
that can retain all RADIO_ERP1 fields, including VLD payloads and ESP3 optional
data.  It intentionally exposes read-only legacy attribute aliases so current
EEP decoders can consume it without depending on an ESP3 implementation.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, Tuple


class TelegramDirection(str, Enum):
    """Direction of a telegram relative to the local gateway."""

    INCOMING = "incoming"
    OUTGOING = "outgoing"


_ESP2_ORG_TO_RORG = {
    0x05: 0xF6,  # RPS
    0x06: 0xD5,  # 1BS
    0x07: 0xA5,  # 4BS
    0xD2: 0xD2,  # VLD has no lossless ESP2 wire representation
}
_RORG_TO_ESP2_ORG = {rorg: org for org, rorg in _ESP2_ORG_TO_RORG.items()}
_FIXED_PAYLOAD_LENGTHS = {0xF6: 1, 0xD5: 1, 0xA5: 4}


def _byte_value(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if not 0 <= value <= 0xFF:
        raise ValueError("%s must be between 0 and 255" % name)
    return int(value)


def _bytes_value(name: str, value: Any, length: Optional[int] = None) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("%s must be bytes-like" % name)
    try:
        normalized = bytes(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("%s must be bytes-like" % name) from exc
    if length is not None and len(normalized) != length:
        raise ValueError("%s must contain exactly %d bytes" % (name, length))
    return normalized


@dataclass(frozen=True, slots=True)
class RadioTelegram:
    """Immutable, protocol-neutral ESP3 RADIO_ERP1 telegram.

    ``rorg`` uses native ESP3 values such as ``0xF6`` (RPS), ``0xA5`` (4BS)
    and ``0xD2`` (VLD).  ``payload`` excludes RORG, sender and status bytes.

    ESP3 optional metadata is either completely absent or complete.  Supplying
    ``raw_optional_data`` alone derives the individual metadata fields.  When
    both forms are supplied they must describe exactly the same seven bytes.
    RSSI is represented as a non-positive dBm value; the ESP3 wire byte stores
    its positive magnitude.
    """

    rorg: int
    payload: bytes
    sender: bytes
    status: int
    direction: TelegramDirection = TelegramDirection.INCOMING
    destination: Optional[bytes] = None
    subtelegram_count: Optional[int] = None
    rssi_dbm: Optional[int] = None
    security_level: Optional[int] = None
    raw_optional_data: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "rorg", _byte_value("rorg", self.rorg))
        object.__setattr__(self, "status", _byte_value("status", self.status))
        object.__setattr__(self, "payload", _bytes_value("payload", self.payload))
        object.__setattr__(self, "sender", _bytes_value("sender", self.sender, 4))
        object.__setattr__(
            self, "raw_optional_data",
            _bytes_value("raw_optional_data", self.raw_optional_data),
        )

        try:
            direction = TelegramDirection(self.direction)
        except (TypeError, ValueError) as exc:
            raise ValueError("direction must be 'incoming' or 'outgoing'") from exc
        object.__setattr__(self, "direction", direction)

        payload_length = len(self.payload)
        if not 1 <= payload_length <= 14:
            raise ValueError("RADIO_ERP1 payload must contain between 1 and 14 bytes")
        expected_length = _FIXED_PAYLOAD_LENGTHS.get(self.rorg)
        if expected_length is not None and payload_length != expected_length:
            raise ValueError(
                "RORG 0x%02X requires a %d-byte payload" %
                (self.rorg, expected_length)
            )

        raw = self.raw_optional_data
        if raw and len(raw) != 7:
            raise ValueError("RADIO_ERP1 optional data must contain exactly 7 bytes")

        supplied = (
            self.destination,
            self.subtelegram_count,
            self.rssi_dbm,
            self.security_level,
        )
        if raw:
            derived = (raw[1:5], raw[0], -raw[5], raw[6])
            names = (
                "destination", "subtelegram_count", "rssi_dbm",
                "security_level",
            )
            for name, current, parsed in zip(names, supplied, derived):
                if current is not None and current != parsed:
                    raise ValueError(
                        "%s conflicts with raw_optional_data" % name
                    )
                object.__setattr__(self, name, parsed)
        elif any(value is not None for value in supplied):
            if any(value is None for value in supplied):
                raise ValueError(
                    "ESP3 optional metadata must be supplied completely or omitted"
                )

        if self.destination is not None:
            object.__setattr__(
                self, "destination",
                _bytes_value("destination", self.destination, 4),
            )
            if (isinstance(self.subtelegram_count, bool) or
                    not isinstance(self.subtelegram_count, int)):
                raise TypeError("subtelegram_count must be an integer")
            if not 0 <= self.subtelegram_count <= 0xFF:
                raise ValueError("subtelegram_count must be between 0 and 255")
            if (isinstance(self.rssi_dbm, bool) or
                    not isinstance(self.rssi_dbm, int)):
                raise TypeError("rssi_dbm must be an integer")
            if not -255 <= self.rssi_dbm <= 0:
                raise ValueError("rssi_dbm must be between -255 and 0")
            if (isinstance(self.security_level, bool) or
                    not isinstance(self.security_level, int)):
                raise TypeError("security_level must be an integer")
            if not 0 <= self.security_level <= 4:
                raise ValueError("security_level must be between 0 and 4")

            generated = bytes((self.subtelegram_count,)) + self.destination + bytes((
                -self.rssi_dbm,
                self.security_level,
            ))
            if raw and generated != raw:
                raise ValueError("optional metadata conflicts with raw_optional_data")

    @property
    def org(self) -> int:
        """Return the legacy ESP2 ORG value used by existing EEP decoders."""

        return _RORG_TO_ESP2_ORG.get(self.rorg, self.rorg)

    @property
    def data(self) -> bytes:
        """Read-only compatibility alias for ``payload``."""

        return self.payload

    @property
    def address(self) -> bytes:
        """Read-only compatibility alias for ``sender``."""

        return self.sender

    @property
    def outgoing(self) -> bool:
        """Read-only legacy direction flag."""

        return self.direction is TelegramDirection.OUTGOING

    @classmethod
    def from_legacy_message(cls, message: Any) -> "RadioTelegram":
        """Create a telegram from an existing ESP2 radio or VLD object.

        The adapter accepts the public radio-message shape (``org``, ``data``,
        ``address`` and ``status``), including wrapped Eltako radio telegrams.
        ESP3-only optional metadata cannot be recovered from a legacy object
        and is therefore left absent.
        """

        try:
            org = int(message.org)
            rorg = _ESP2_ORG_TO_RORG[org]
            payload = message.data
            sender = message.address
            status = message.status
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise TypeError("message is not a supported ESP2/VLD radio object") from exc
        direction = (
            TelegramDirection.OUTGOING
            if bool(getattr(message, "outgoing", False))
            else TelegramDirection.INCOMING
        )
        return cls(rorg, payload, sender, status, direction)

    def to_legacy_message(self, *, allow_metadata_loss: bool = False) -> Any:
        """Return the corresponding existing ESP2/VLD message object.

        RADIO_ERP1 optional metadata has no place in the legacy classes.  The
        conversion therefore rejects metadata-bearing telegrams unless the
        caller explicitly opts into that loss.
        """

        if self.destination is not None and not allow_metadata_loss:
            raise ValueError(
                "legacy conversion would discard ESP3 optional metadata; "
                "pass allow_metadata_loss=True to confirm"
            )

        from .message import (
            RPSMessage, Regular1BSMessage, Regular4BSMessage, VLDMessage,
        )

        message_types = {
            0xF6: RPSMessage,
            0xD5: Regular1BSMessage,
            0xA5: Regular4BSMessage,
            0xD2: VLDMessage,
        }
        try:
            message_type = message_types[self.rorg]
        except KeyError as exc:
            raise ValueError(
                "RORG 0x%02X has no existing ESP2/VLD representation" % self.rorg
            ) from exc
        return message_type(
            self.sender,
            self.status,
            self.payload,
            outgoing=self.outgoing,
        )

    @classmethod
    def from_esp3_fields(
        cls,
        data: Any,
        optional_data: Any = b"",
        *,
        direction: TelegramDirection = TelegramDirection.INCOMING,
    ) -> "RadioTelegram":
        """Parse the data and optional sections of a RADIO_ERP1 packet."""

        data_bytes = _bytes_value("data", data)
        if not 7 <= len(data_bytes) <= 20:
            raise ValueError(
                "RADIO_ERP1 data must contain RORG, 1..14 payload bytes, "
                "sender and status"
            )
        optional_bytes = _bytes_value("optional_data", optional_data)
        return cls(
            rorg=data_bytes[0],
            payload=data_bytes[1:-5],
            sender=data_bytes[-5:-1],
            status=data_bytes[-1],
            direction=direction,
            raw_optional_data=optional_bytes,
        )

    @classmethod
    def from_esp3_packet(
        cls,
        packet: Any,
        *,
        direction: TelegramDirection = TelegramDirection.INCOMING,
    ) -> "RadioTelegram":
        """Create a telegram from an enocean-compatible packet object.

        No third-party package is imported.  The packet only needs ``data``
        and ``optional`` attributes.  If present, ``packet_type`` must be the
        numeric RADIO_ERP1 value ``1`` and ``rorg`` must match the first data
        byte.
        """

        try:
            data = _bytes_value("packet.data", packet.data)
            optional = _bytes_value(
                "packet.optional", getattr(packet, "optional", b"") or b"",
            )
        except AttributeError as exc:
            raise TypeError("packet must expose a data attribute") from exc

        packet_type = getattr(packet, "packet_type", None)
        if packet_type is not None and int(packet_type) != 1:
            raise ValueError("packet is not ESP3 RADIO_ERP1")
        packet_rorg = getattr(packet, "rorg", None)
        if packet_rorg is not None:
            if not data or int(packet_rorg) != data[0]:
                raise ValueError("packet.rorg does not match packet.data")
        return cls.from_esp3_fields(data, optional, direction=direction)

    def to_esp3_fields(self) -> Tuple[bytes, bytes]:
        """Return lossless ``(data, optional_data)`` RADIO_ERP1 sections.

        Parsed captures may legitimately be incomplete and therefore have no
        optional section. This method preserves that state for inspection and
        capture/replay. It does *not* make such a telegram valid for outbound
        ESP3 transmission; use :meth:`to_esp3_packet`, which requires complete
        optional data by default.
        """

        data = bytes((self.rorg,)) + self.payload + self.sender + bytes((self.status,))
        if self.raw_optional_data:
            optional = self.raw_optional_data
        elif self.destination is not None:
            optional = bytes((self.subtelegram_count,)) + self.destination + bytes((
                -self.rssi_dbm,
                self.security_level,
            ))
        else:
            optional = b""
        return data, optional

    def to_esp3_packet(
        self,
        packet_factory: Callable[[bytes, bytes], Any],
        *,
        allow_incomplete_optional_data: bool = False,
    ) -> Any:
        """Build an outbound packet through a caller-supplied factory.

        RADIO_ERP1 packets normally require the seven-byte optional section.
        ``RadioTelegram`` nevertheless permits absent optional data so that
        truncated captures can be retained faithfully. Refuse to turn such a
        capture into an invalid outbound packet unless the caller explicitly
        passes ``allow_incomplete_optional_data=True``. That escape hatch is
        intended only for adapters which provide the optional section later.
        """

        if not callable(packet_factory):
            raise TypeError("packet_factory must be callable")
        data, optional = self.to_esp3_fields()
        if not optional and not allow_incomplete_optional_data:
            raise ValueError(
                "outbound RADIO_ERP1 packets require seven bytes of optional "
                "data; pass allow_incomplete_optional_data=True only when the "
                "transport supplies them"
            )
        return packet_factory(data, optional)


__all__ = ["RadioTelegram", "TelegramDirection"]
