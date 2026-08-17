"""Deterministic in-process bus, replay, and fault injection helpers.

The classes in this module are intended for tests and offline examples.  They
do not open hardware, start threads, or alter the behavior of the serial bus
implementations.  Import them explicitly from :mod:`eltakobus.virtual_bus`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable, Mapping, Optional

from .bus import BusInterface
from .error import ParseError, TimeoutError
from .message import ESP2Message, EltakoTimeout, prettify


RECORDING_FORMAT = "eltako14bus.virtual-bus"
RECORDING_VERSION = 1


class Direction(str, Enum):
    """Direction in which a deterministic fault is applied."""

    SEND = "send"
    RECEIVE = "receive"


class Fault(str, Enum):
    """Faults supported by :class:`VirtualBus`."""

    DROP = "drop"
    DUPLICATE = "duplicate"
    CORRUPT_CHECKSUM = "corrupt_checksum"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"


class ReplayAction(str, Enum):
    """Action stored in a :class:`ReplayEvent`."""

    MESSAGE = "message"
    DISCONNECT = "disconnect"
    RECONNECT = "reconnect"


class VirtualBusDisconnected(ConnectionError):
    """Raised when a send is attempted while the virtual bus is disconnected."""


@dataclass(frozen=True)
class FaultRule:
    """Apply ``fault`` to a 1-based occurrence in one direction.

    Occurrence counters are independent for sent and received frames.  Rules
    therefore remain stable when test code adds traffic in the other direction.
    """

    direction: Direction
    occurrence: int
    fault: Fault

    def __post_init__(self) -> None:
        object.__setattr__(self, "direction", Direction(self.direction))
        object.__setattr__(self, "fault", Fault(self.fault))
        if self.occurrence < 1:
            raise ValueError("FaultRule.occurrence must be at least 1")


def _serialize_frame(message: Any) -> bytes:
    if isinstance(message, (bytes, bytearray, memoryview)):
        return bytes(message)
    serialize = getattr(message, "serialize", None)
    if serialize is None:
        raise TypeError("A virtual bus frame must be bytes or provide serialize()")
    raw = serialize()
    if not isinstance(raw, (bytes, bytearray, memoryview)):
        raise TypeError("serialize() must return bytes")
    return bytes(raw)


@dataclass(frozen=True)
class ReplayEvent:
    """One message or connection transition at a recording-relative time."""

    at: float
    action: ReplayAction
    data: bytes = b""

    def __post_init__(self) -> None:
        object.__setattr__(self, "action", ReplayAction(self.action))
        object.__setattr__(self, "data", bytes(self.data))
        if self.at < 0:
            raise ValueError("ReplayEvent.at must not be negative")
        if self.action is ReplayAction.MESSAGE and not self.data:
            raise ValueError("A message replay event requires frame data")
        if self.action is not ReplayAction.MESSAGE and self.data:
            raise ValueError("Connection replay events cannot contain frame data")

    @classmethod
    def message(cls, at: float, message: Any) -> "ReplayEvent":
        """Create an event from serialized bytes or an ESP2 message object."""

        return cls(at=at, action=ReplayAction.MESSAGE, data=_serialize_frame(message))

    @classmethod
    def disconnect(cls, at: float) -> "ReplayEvent":
        return cls(at=at, action=ReplayAction.DISCONNECT)

    @classmethod
    def reconnect(cls, at: float) -> "ReplayEvent":
        return cls(at=at, action=ReplayAction.RECONNECT)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"at": self.at, "action": self.action.value}
        if self.action is ReplayAction.MESSAGE:
            result["frame"] = self.data.hex()
        return result

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayEvent":
        action = ReplayAction(value["action"])
        frame = bytes.fromhex(value.get("frame", ""))
        return cls(at=float(value["at"]), action=action, data=frame)


def encode_recording(
    events: Iterable[ReplayEvent], *, gateway: Optional[Mapping[str, Any]] = None
) -> dict[str, Any]:
    """Return a JSON-serializable, versioned recording document."""

    result: dict[str, Any] = {
        "format": RECORDING_FORMAT,
        "version": RECORDING_VERSION,
        "events": [event.to_dict() for event in events],
    }
    if gateway is not None:
        result["gateway"] = dict(gateway)
    return result


def decode_recording(recording: Mapping[str, Any]) -> tuple[ReplayEvent, ...]:
    """Validate and decode a recording created by :func:`encode_recording`."""

    if recording.get("format") != RECORDING_FORMAT:
        raise ValueError("Unsupported virtual bus recording format")
    if recording.get("version") != RECORDING_VERSION:
        raise ValueError("Unsupported virtual bus recording version")
    events = tuple(ReplayEvent.from_dict(value) for value in recording.get("events", ()))
    _validate_event_order(events)
    return events


@dataclass(frozen=True)
class _ScriptedResponse:
    data: bytes
    delay: float


def _validate_event_order(events: Iterable[ReplayEvent]) -> None:
    previous = 0.0
    for event in events:
        if event.at < previous:
            raise ValueError("Replay events must be ordered by their 'at' value")
        previous = event.at


class VirtualBus(BusInterface):
    """A deterministic, asyncio-friendly in-process implementation of a bus.

    ``queue_response`` scripts request/response exchanges.  ``inject`` and
    ``replay`` provide unsolicited receive traffic through ``received``.
    Fault rules use independent 1-based send and receive counters, making a
    failure scenario repeatable without randomness.
    """

    def __init__(
        self,
        *,
        latency: float = 0.0,
        response_timeout: float = 0.0,
        faults: Iterable[FaultRule] = (),
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        connected: bool = True,
    ) -> None:
        if latency < 0 or response_timeout < 0:
            raise ValueError("latency and response_timeout must not be negative")

        self.latency = float(latency)
        self.response_timeout = float(response_timeout)
        self.received: asyncio.Queue[Any] = asyncio.Queue()
        self.raw_received: asyncio.Queue[bytes] = asyncio.Queue()
        self.decode_errors: list[ParseError] = []

        # ``attempted_raw`` includes dropped frames. ``sent_raw`` only includes
        # frames that made it through the configured send faults.
        self.attempted_raw: list[bytes] = []
        self.sent_raw: list[bytes] = []
        self.dropped: list[tuple[Direction, int, bytes]] = []

        self._sleeper = sleeper
        self._connected = bool(connected)
        self._callback: Optional[Callable[[Any], None]] = None
        self._status_changed_handler: Optional[Callable[[bool], None]] = None
        self._occurrences = {Direction.SEND: 0, Direction.RECEIVE: 0}
        self._faults: dict[tuple[Direction, int], set[Fault]] = defaultdict(set)
        for rule in faults:
            normalized = rule if isinstance(rule, FaultRule) else FaultRule(*rule)
            self._faults[(normalized.direction, normalized.occurrence)].add(normalized.fault)

        for actions in self._faults.values():
            if Fault.DISCONNECT in actions and Fault.RECONNECT in actions:
                raise ValueError("One occurrence cannot disconnect and reconnect simultaneously")

        self._responses: dict[bytes, deque[_ScriptedResponse]] = defaultdict(deque)
        self._exchange_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._receive_lock = asyncio.Lock()
        self._replay_lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return self._connected

    def is_active(self) -> bool:
        return self._connected

    def set_callback(self, callback: Optional[Callable[[Any], None]]) -> None:
        """Route future injected messages to a synchronous callback or queue."""

        self._callback = callback

    def set_status_changed_handler(
        self, handler: Optional[Callable[[bool], None]]
    ) -> None:
        self._status_changed_handler = handler
        if handler is not None:
            handler(self._connected)

    def disconnect(self) -> None:
        self._set_connected(False)

    def reconnect(self) -> None:
        self._set_connected(True)

    def _set_connected(self, connected: bool) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        if self._status_changed_handler is not None:
            self._status_changed_handler(connected)

    def queue_response(self, request: Any, response: Any, *, delay: float = 0.0) -> None:
        """Append one FIFO response for the serialized request.

        The response is consumed by exactly one exchange attempt.  Queue the
        same request more than once to model retries or changing device state.
        """

        if delay < 0:
            raise ValueError("response delay must not be negative")
        self._responses[_serialize_frame(request)].append(
            _ScriptedResponse(_serialize_frame(response), float(delay))
        )

    async def send(self, request: Any) -> None:
        """Send without waiting for a response, recording the resulting frame."""

        await self._transmit(request)

    async def base_exchange(self, request: Any) -> bytes:
        """Provide the raw-response variant required by :class:`BusInterface`."""

        response = await self.exchange(request)
        return _serialize_frame(response)

    async def exchange(
        self,
        request: Any,
        responsetype: Optional[type] = None,
        *,
        retries: int = 1,
        timeout: Optional[float] = None,
        retry_delay: float = 0.0,
    ) -> Any:
        """Execute a scripted request/response transaction.

        Missing, dropped, or corrupted responses consume an attempt and
        ultimately raise the library's ``TimeoutError``. A disconnected send
        raises ``VirtualBusDisconnected`` immediately. The method serializes
        concurrent exchanges in the same way as a physical half-duplex bus.
        """

        if retries < 1:
            raise ValueError("retries must be at least 1")
        wait = self.response_timeout if timeout is None else float(timeout)
        if wait < 0 or retry_delay < 0:
            raise ValueError("timeout and retry_delay must not be negative")

        async with self._exchange_lock:
            for attempt in range(retries):
                transmitted = await self._transmit(request)
                script = self._responses[transmitted[0]].popleft() if (
                    transmitted and self._responses.get(transmitted[0])
                ) else None

                if script is not None:
                    # Scripted delays model time spent waiting for a response,
                    # so they consume this attempt's timeout budget. Checking
                    # the configured delay before sleeping also keeps injected
                    # sleepers deterministic in tests.
                    if script.delay > wait:
                        if wait:
                            await self._sleeper(wait)
                        if attempt + 1 < retries and retry_delay:
                            await self._sleeper(retry_delay)
                        continue
                    if script.delay:
                        await self._sleeper(script.delay)
                    delivered = await self._receive_frame(
                        script.data, enqueue=False, invoke_callback=False
                    )
                    if delivered:
                        raw, message = delivered[0]
                        for extra_raw, extra_message in delivered[1:]:
                            await self.raw_received.put(extra_raw)
                            await self.received.put(extra_message)
                        return self._coerce_response(raw, message, responsetype)

                if wait:
                    await self._sleeper(wait)
                if attempt + 1 < retries and retry_delay:
                    await self._sleeper(retry_delay)

        raise TimeoutError("Virtual bus transaction timed out")

    async def inject(self, message: Any, *, delay: Optional[float] = None) -> tuple[Any, ...]:
        """Inject one unsolicited frame and return all delivered messages."""

        effective_delay = self.latency if delay is None else float(delay)
        if effective_delay < 0:
            raise ValueError("injection delay must not be negative")
        if effective_delay:
            await self._sleeper(effective_delay)
        delivered = await self._receive_frame(_serialize_frame(message))
        return tuple(message for _, message in delivered)

    async def replay(
        self, events: Iterable[ReplayEvent], *, time_scale: float = 0.0
    ) -> tuple[Any, ...]:
        """Replay ordered events; ``time_scale=0`` runs without wall-clock waits.

        A scale of ``1`` preserves recorded offsets, ``0.5`` runs twice as
        fast, and the default ``0`` keeps only deterministic event ordering.
        """

        if time_scale < 0:
            raise ValueError("time_scale must not be negative")
        normalized = tuple(events)
        _validate_event_order(normalized)
        delivered: list[Any] = []

        async with self._replay_lock:
            previous = 0.0
            for event in normalized:
                delay = (event.at - previous) * time_scale
                if delay:
                    await self._sleeper(delay)
                previous = event.at

                if event.action is ReplayAction.DISCONNECT:
                    self.disconnect()
                elif event.action is ReplayAction.RECONNECT:
                    self.reconnect()
                else:
                    delivered.extend(await self.inject(event.data, delay=0.0))

        return tuple(delivered)

    async def _transmit(self, request: Any) -> tuple[bytes, ...]:
        raw = _serialize_frame(request)
        if self.latency:
            await self._sleeper(self.latency)

        async with self._send_lock:
            occurrence = self._next_occurrence(Direction.SEND)
            actions = self._faults[(Direction.SEND, occurrence)]
            self.attempted_raw.append(raw)
            self._apply_connection_fault(actions)

            if not self._connected:
                self.dropped.append((Direction.SEND, occurrence, raw))
                raise VirtualBusDisconnected("Virtual bus is disconnected")
            if Fault.DROP in actions:
                self.dropped.append((Direction.SEND, occurrence, raw))
                return ()
            if Fault.CORRUPT_CHECKSUM in actions:
                raw = self._corrupt_checksum(raw)

            copies = 2 if Fault.DUPLICATE in actions else 1
            self.sent_raw.extend(raw for _ in range(copies))
            return tuple(raw for _ in range(copies))

    async def _receive_frame(
        self,
        raw: bytes,
        *,
        enqueue: bool = True,
        invoke_callback: bool = True,
    ) -> list[tuple[bytes, Any]]:
        async with self._receive_lock:
            occurrence = self._next_occurrence(Direction.RECEIVE)
            actions = self._faults[(Direction.RECEIVE, occurrence)]
            self._apply_connection_fault(actions)

            if not self._connected or Fault.DROP in actions:
                self.dropped.append((Direction.RECEIVE, occurrence, raw))
                return []
            if Fault.CORRUPT_CHECKSUM in actions:
                raw = self._corrupt_checksum(raw)

            copies = 2 if Fault.DUPLICATE in actions else 1
            delivered: list[tuple[bytes, Any]] = []
            for _ in range(copies):
                if enqueue:
                    await self.raw_received.put(raw)
                try:
                    message = prettify(ESP2Message.parse(raw))
                except ParseError as error:
                    self.decode_errors.append(error)
                    continue

                delivered.append((raw, message))
                if not enqueue:
                    continue
                if invoke_callback and self._callback is not None:
                    self._callback(message)
                else:
                    await self.received.put(message)
            return delivered

    def _apply_connection_fault(self, actions: set[Fault]) -> None:
        if Fault.DISCONNECT in actions:
            self.disconnect()
        elif Fault.RECONNECT in actions:
            self.reconnect()

    def _next_occurrence(self, direction: Direction) -> int:
        self._occurrences[direction] += 1
        return self._occurrences[direction]

    @staticmethod
    def _corrupt_checksum(raw: bytes) -> bytes:
        if not raw:
            return raw
        return raw[:-1] + bytes((raw[-1] ^ 0xFF,))

    @staticmethod
    def _coerce_response(raw: bytes, message: Any, responsetype: Optional[type]) -> Any:
        if responsetype is None or isinstance(message, responsetype):
            return message
        try:
            return responsetype.parse(raw)
        except ParseError:
            try:
                EltakoTimeout.parse(raw)
            except ParseError:
                raise
            raise TimeoutError("Virtual bus received an Eltako timeout")
