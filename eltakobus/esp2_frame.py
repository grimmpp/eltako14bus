"""Incremental framing for the fixed-size Eltako ESP2 telegram format.

ESP2 telegrams are always fourteen bytes: ``A5 5A``, eleven body bytes and a
modulo-256 checksum over the body.  This module deliberately returns raw
validated frames; callers decide whether to construct a generic
``ESP2Message`` or a more specific message type.
"""

from __future__ import annotations

from collections.abc import Iterable

from .error import ParseError


ESP2_SYNC = b"\xA5\x5A"
ESP2_FRAME_LENGTH = 14


class ESP2FrameParser:
    """Recover validated ESP2 frames from arbitrary byte chunks.

    The parser accepts byte-at-a-time input, multiple frames per read and
    garbage or corrupted frames between valid frames.  It retains only a
    partial candidate frame, so a corrupt length cannot create an unbounded
    allocation.
    """

    def __init__(self, *, max_errors: int = 256):
        if isinstance(max_errors, bool) or not isinstance(max_errors, int) or max_errors < 1:
            raise ValueError("max_errors must be a positive integer")
        self._buffer = bytearray()
        self._errors: list[ParseError] = []
        self.max_errors = max_errors
        self.discarded_bytes = 0

    @property
    def buffered_bytes(self) -> bytes:
        return bytes(self._buffer)

    @property
    def errors(self) -> tuple[ParseError, ...]:
        return tuple(self._errors)

    def pop_errors(self) -> tuple[ParseError, ...]:
        errors = tuple(self._errors)
        self._errors.clear()
        return errors

    def reset(self) -> None:
        self._buffer.clear()
        self._errors.clear()
        self.discarded_bytes = 0

    def _record_error(self, error: ParseError) -> None:
        self._errors.append(error)
        if len(self._errors) > self.max_errors:
            del self._errors[:-self.max_errors]

    def feed(self, chunk: bytes | bytearray | memoryview | Iterable[int]) -> list[bytes]:
        if isinstance(chunk, (str, int)):
            raise TypeError("chunk must be bytes-like or an iterable of integers")
        try:
            self._buffer.extend(bytes(chunk))
        except (TypeError, ValueError) as exc:
            raise TypeError("chunk must be bytes-like") from exc

        frames: list[bytes] = []
        while self._buffer:
            sync_index = self._buffer.find(ESP2_SYNC)
            if sync_index < 0:
                # Keep a possible first sync byte for a split preamble.
                keep = 1 if self._buffer[-1:] == ESP2_SYNC[:1] else 0
                self.discarded_bytes += len(self._buffer) - keep
                del self._buffer[:len(self._buffer) - keep]
                break
            if sync_index:
                self.discarded_bytes += sync_index
                del self._buffer[:sync_index]
            if len(self._buffer) < ESP2_FRAME_LENGTH:
                break

            candidate = bytes(self._buffer[:ESP2_FRAME_LENGTH])
            try:
                # Import locally to keep this framing layer free of parser
                # policy while reusing the canonical checksum validation.
                from .message import ESP2Message
                ESP2Message.parse(candidate)
            except ParseError as exc:
                self._record_error(exc)
                del self._buffer[0]
                self.discarded_bytes += 1
                continue
            del self._buffer[:ESP2_FRAME_LENGTH]
            frames.append(candidate)
        return frames


__all__ = ["ESP2_SYNC", "ESP2_FRAME_LENGTH", "ESP2FrameParser"]
