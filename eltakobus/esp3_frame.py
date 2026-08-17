"""Dependency-free ESP3 frame encoding and incremental stream parsing.

The module deliberately operates below :mod:`eltakobus.esp3`: it only knows
about ESP3 framing and never instantiates optional ``enocean`` package types.
This makes it suitable for serial, TCP, recordings and tests while preserving
the raw DATA and OPTIONAL_DATA sections exactly as received.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable


ESP3_SYNC_BYTE = 0x55
ESP3_PACKET_RADIO_ERP1 = 0x01
_HEADER_SIZE = 6
_DATA_CRC_SIZE = 1
_MAX_DATA_LENGTH = 0xFFFF
_MAX_OPTIONAL_LENGTH = 0xFF


class ESP3PacketType(IntEnum):
    """Known ESP3 packet types; unknown numeric values remain supported."""

    RADIO_ERP1 = 0x01
    RESPONSE = 0x02
    RADIO_SUB_TEL = 0x03
    EVENT = 0x04
    COMMON_COMMAND = 0x05
    SMART_ACK_COMMAND = 0x06
    REMOTE_MAN_COMMAND = 0x07
    RADIO_MESSAGE = 0x09
    RADIO_ADVANCED = 0x0A



class ESP3ParseError(ValueError):
    """Base class for an invalid ESP3 frame found in a byte stream."""


class ESP3HeaderCRCError(ESP3ParseError):
    """The ESP3 header checksum did not match its length/type fields."""


class ESP3DataCRCError(ESP3ParseError):
    """The ESP3 data and optional-data checksum did not match."""


class ESP3FrameSizeError(ESP3ParseError):
    """A declared frame length exceeds the configured parser limits."""


ESP3FrameLengthError = ESP3FrameSizeError


def _as_bytes(name: str, value: bytes | bytearray | memoryview | Iterable[int]) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("%s must be bytes-like" % name)
    try:
        return bytes(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("%s must be bytes-like" % name) from exc


def _byte(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if not 0 <= value <= 0xFF:
        raise ValueError("%s must be between 0 and 255" % name)
    return value


def crc8(data: bytes | bytearray | memoryview | Iterable[int]) -> int:
    """Return the ESP3 CRC-8 value (polynomial ``0x07``, initial value 0)."""

    result = 0
    for value in _as_bytes("data", data):
        result ^= value
        for _ in range(8):
            result = ((result << 1) ^ 0x07) & 0xFF if result & 0x80 else (result << 1) & 0xFF
    return result


@dataclass(frozen=True, slots=True)
class RadioERP1Sections:
    """Lossless logical sections of a ``RADIO_ERP1`` frame."""

    rorg: int
    payload: bytes
    sender: bytes
    status: int
    optional: bytes


@dataclass(frozen=True, slots=True)
class ESP3Frame:
    """Immutable ESP3 packet with exact DATA and OPTIONAL_DATA sections."""

    packet_type: int
    data: bytes = b""
    optional: bytes = b""

    @property
    def optional_data(self) -> bytes:
        """Compatibility alias for the ESP3 OPTIONAL_DATA section."""

        return self.optional

    def __post_init__(self) -> None:
        object.__setattr__(self, "packet_type", _byte("packet_type", self.packet_type))
        object.__setattr__(self, "data", _as_bytes("data", self.data))
        object.__setattr__(self, "optional", _as_bytes("optional", self.optional))
        if len(self.data) > _MAX_DATA_LENGTH:
            raise ESP3FrameSizeError("ESP3 data section exceeds 65535 bytes")
        if len(self.optional) > _MAX_OPTIONAL_LENGTH:
            raise ESP3FrameSizeError("ESP3 optional section exceeds 255 bytes")

    @property
    def is_radio_erp1(self) -> bool:
        """Whether this frame carries an ESP3 ``RADIO_ERP1`` telegram."""

        return self.packet_type == ESP3_PACKET_RADIO_ERP1

    @property
    def radio_erp1(self) -> RadioERP1Sections:
        """Return lossless RADIO_ERP1 sections without shortening optional data."""

        if not self.is_radio_erp1:
            raise ValueError("frame is not an ESP3 RADIO_ERP1 packet")
        if len(self.data) < 7:
            raise ESP3ParseError(
                "RADIO_ERP1 data requires RORG, payload, sender and status"
            )
        return RadioERP1Sections(
            rorg=self.data[0],
            payload=self.data[1:-5],
            sender=self.data[-5:-1],
            status=self.data[-1],
            optional=self.optional,
        )

    def to_bytes(self) -> bytes:
        """Encode the frame with ESP3 framing and both CRC-8 values."""

        header = len(self.data).to_bytes(2, "big") + bytes((len(self.optional), self.packet_type))
        body = self.data + self.optional
        return bytes((ESP3_SYNC_BYTE,)) + header + bytes((crc8(header),)) + body + bytes((crc8(body),))

    def __bytes__(self) -> bytes:
        return self.to_bytes()

    @classmethod
    def from_bytes(cls, raw: bytes | bytearray | memoryview | Iterable[int]) -> "ESP3Frame":
        """Decode exactly one ESP3 wire frame or raise a clear parse error."""

        encoded = _as_bytes("raw", raw)
        if len(encoded) < _HEADER_SIZE + _DATA_CRC_SIZE:
            raise ESP3ParseError("ESP3 frame is shorter than its header")
        if encoded[0] != ESP3_SYNC_BYTE:
            raise ESP3ParseError("ESP3 frame does not start with sync byte 0x55")
        header = encoded[1:5]
        if encoded[5] != crc8(header):
            raise ESP3HeaderCRCError("ESP3 header CRC mismatch")
        data_length = int.from_bytes(header[:2], "big")
        optional_length = header[2]
        expected_length = _HEADER_SIZE + data_length + optional_length + _DATA_CRC_SIZE
        if len(encoded) != expected_length:
            raise ESP3ParseError(
                "ESP3 frame length mismatch: received %d bytes, expected %d" %
                (len(encoded), expected_length)
            )
        body = encoded[_HEADER_SIZE:-1]
        if encoded[-1] != crc8(body):
            raise ESP3DataCRCError("ESP3 data CRC mismatch")
        return cls(header[3], body[:data_length], body[data_length:])


class ESP3FrameParser:
    """Incrementally decode ESP3 frames from arbitrary stream chunks.

    Noise before a sync byte is ignored. Corrupt frames are dropped and their
    errors are retained in :attr:`errors`; later frames remain parseable.
    """

    def __init__(
        self,
        *,
        max_data_length: int = _MAX_DATA_LENGTH,
        max_optional_length: int = _MAX_OPTIONAL_LENGTH,
        max_errors: int = 256,
    ) -> None:
        if not 0 <= max_data_length <= _MAX_DATA_LENGTH:
            raise ValueError("max_data_length must be between 0 and 65535")
        if not 0 <= max_optional_length <= _MAX_OPTIONAL_LENGTH:
            raise ValueError("max_optional_length must be between 0 and 255")
        if isinstance(max_errors, bool) or not isinstance(max_errors, int) or max_errors < 1:
            raise ValueError("max_errors must be a positive integer")
        self.max_data_length = max_data_length
        self.max_optional_length = max_optional_length
        self.max_errors = max_errors
        self._buffer = bytearray()
        self._errors: list[ESP3ParseError] = []
        self.discarded_bytes = 0

    @property
    def buffered_bytes(self) -> bytes:
        """Return an immutable snapshot of the incomplete stream suffix."""

        return bytes(self._buffer)

    @property
    def discarded_noise_bytes(self) -> int:
        """Compatibility alias for discarded stream bytes."""

        return self.discarded_bytes

    @property
    def errors(self) -> list[ESP3ParseError]:
        """Non-destructive snapshot of recoverable parser errors."""

        return list(self._errors)

    def clear_errors(self) -> None:
        """Discard errors already observed by the caller."""

        self._errors.clear()

    def pop_errors(self) -> tuple[ESP3ParseError, ...]:
        """Return and clear errors retained during stream recovery."""

        errors = tuple(self._errors)
        self._errors.clear()
        return errors

    def reset(self) -> None:
        """Discard an incomplete suffix, retained errors and diagnostics."""

        self._buffer.clear()
        self._errors.clear()
        self.discarded_bytes = 0

    def _record_error(self, error: ESP3ParseError) -> None:
        self._errors.append(error)
        if len(self._errors) > self.max_errors:
            del self._errors[:-self.max_errors]

    def feed(self, chunk: bytes | bytearray | memoryview | Iterable[int]) -> list[ESP3Frame]:
        """Consume a stream chunk and return every complete valid frame."""

        self._buffer.extend(_as_bytes("chunk", chunk))
        frames: list[ESP3Frame] = []

        while self._buffer:
            try:
                sync_index = self._buffer.index(ESP3_SYNC_BYTE)
            except ValueError:
                self.discarded_bytes += len(self._buffer)
                self._buffer.clear()
                break
            if sync_index:
                self.discarded_bytes += sync_index
                del self._buffer[:sync_index]
            if len(self._buffer) < _HEADER_SIZE:
                break

            header = bytes(self._buffer[1:5])
            if self._buffer[5] != crc8(header):
                self._record_error(ESP3HeaderCRCError("ESP3 header CRC mismatch"))
                del self._buffer[0]
                self.discarded_bytes += 1
                continue

            data_length = int.from_bytes(header[:2], "big")
            optional_length = header[2]
            if data_length > self.max_data_length or optional_length > self.max_optional_length:
                self._record_error(ESP3FrameSizeError(
                    "ESP3 frame declares data=%d, optional=%d beyond parser limits" %
                    (data_length, optional_length)
                )
                )
                del self._buffer[0]
                self.discarded_bytes += 1
                continue

            frame_length = _HEADER_SIZE + data_length + optional_length + _DATA_CRC_SIZE
            if len(self._buffer) < frame_length:
                break

            encoded = bytes(self._buffer[:frame_length])
            try:
                frame = ESP3Frame.from_bytes(encoded)
            except ESP3DataCRCError as exc:
                self._record_error(exc)
                del self._buffer[:frame_length]
                self.discarded_bytes += frame_length
                continue
            except ESP3ParseError as exc:
                self._record_error(exc)
                del self._buffer[0]
                self.discarded_bytes += 1
                continue
            del self._buffer[:frame_length]
            frames.append(frame)

        return frames


class ESP3StreamParser(ESP3FrameParser):
    """Compatibility spelling with an optional total-frame size limit."""

    def __init__(self, *, maximum_frame_length: int | None = None, **kwargs):
        if maximum_frame_length is not None:
            if maximum_frame_length < _HEADER_SIZE + _DATA_CRC_SIZE:
                raise ValueError("maximum_frame_length is too small")
            kwargs.setdefault("max_data_length", maximum_frame_length)
        super().__init__(**kwargs)


__all__ = [
    "ESP3_SYNC_BYTE", "ESP3_PACKET_RADIO_ERP1", "ESP3ParseError",
    "ESP3HeaderCRCError", "ESP3DataCRCError", "ESP3FrameSizeError",
    "ESP3PacketType", "ESP3Frame", "ESP3FrameParser", "ESP3StreamParser",
    "ESP3FrameLengthError", "RadioERP1Sections", "crc8",
]
