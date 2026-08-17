"""Minimal asynchronous dispatcher for native ESP3 semantic packets.

The dispatcher consumes already framed :class:`ESP3Frame` objects.  Serial or
TCP stream framing therefore remains an independent concern.  ESP3 command
responses do not include a transaction identifier, so the command client
serializes response-bearing commands and associates the next response with
the single active command.
"""

from __future__ import annotations

import asyncio
import inspect
import math
from dataclasses import dataclass
from typing import Any

from .esp3_frame import ESP3Frame
from .esp3_packet import (
    ESP3Command,
    ESP3Event,
    ESP3PacketError,
    ESP3Response,
    UnknownESP3Packet,
    decode_esp3_packet,
)
from .radio import RadioTelegram


class ESP3DispatcherError(RuntimeError):
    """Base class for dispatcher lifecycle and transport errors."""


class ESP3DispatcherClosed(ESP3DispatcherError):
    """The dispatcher was closed while an operation was active."""


class ESP3CommandTimeout(TimeoutError):
    """No ESP3 response arrived before the command deadline."""


@dataclass(frozen=True, slots=True)
class ESP3DispatcherDiagnostics:
    """Snapshot of packet routing and recoverable semantic decode errors."""

    received_frames: int
    radio_packets: int
    event_packets: int
    command_responses: int
    unsolicited_responses: int
    unknown_packets: int
    decode_errors: int


class ESP3Dispatcher:
    """Decode and route frames from one asynchronous ESP3 frame transport.

    The transport must expose async ``send(frame)`` and either async
    ``receive()`` or an ``asyncio.Queue``-like ``received.get()``.  Public
    queues are intentionally unbounded: protocol input must not deadlock while
    a command response is waiting. Applications should drain the streams they
    use and observe :attr:`diagnostics`.
    """

    def __init__(self, transport: Any) -> None:
        if not callable(getattr(transport, "send", None)):
            raise TypeError("ESP3 transport must provide async send(frame)")
        if not callable(getattr(transport, "receive", None)) and not callable(
            getattr(getattr(transport, "received", None), "get", None)
        ):
            raise TypeError(
                "ESP3 transport must provide async receive() or received.get()"
            )

        self.transport = transport
        self.packets: asyncio.Queue[Any] = asyncio.Queue()
        self.radio: asyncio.Queue[RadioTelegram] = asyncio.Queue()
        self.events: asyncio.Queue[ESP3Event] = asyncio.Queue()
        self.responses: asyncio.Queue[ESP3Response] = asyncio.Queue()
        self.unknown: asyncio.Queue[UnknownESP3Packet] = asyncio.Queue()
        self.errors: asyncio.Queue[tuple[ESP3Frame, ESP3PacketError]] = asyncio.Queue()

        self.command_client = ESP3CommandClient(self)
        self._receiver_task: asyncio.Task[None] | None = None
        self._owner_loop: asyncio.AbstractEventLoop | None = None
        self._start_lock = asyncio.Lock()
        self._response_waiter: asyncio.Future[ESP3Response] | None = None
        self._closed = False
        self._failure: BaseException | None = None
        self._terminal_error: BaseException | None = None
        self._terminal_event = asyncio.Event()
        self._received_frames = 0
        self._radio_packets = 0
        self._event_packets = 0
        self._command_responses = 0
        self._unsolicited_responses = 0
        self._unknown_packets = 0
        self._decode_errors = 0

    async def __aenter__(self) -> "ESP3Dispatcher":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()

    @property
    def diagnostics(self) -> ESP3DispatcherDiagnostics:
        """Return immutable counters without consuming any queue."""

        return ESP3DispatcherDiagnostics(
            received_frames=self._received_frames,
            radio_packets=self._radio_packets,
            event_packets=self._event_packets,
            command_responses=self._command_responses,
            unsolicited_responses=self._unsolicited_responses,
            unknown_packets=self._unknown_packets,
            decode_errors=self._decode_errors,
        )

    async def start(self) -> None:
        """Start exactly one receive task in the current event loop."""

        loop = asyncio.get_running_loop()
        async with self._start_lock:
            if self._closed:
                raise ESP3DispatcherClosed("ESP3 dispatcher is closed")
            if self._owner_loop is not None and self._owner_loop is not loop:
                raise RuntimeError("ESP3Dispatcher cannot span event loops")
            self._owner_loop = loop
            if self._receiver_task is None:
                self._receiver_task = loop.create_task(
                    self._receive_loop(), name="eltakobus-esp3-dispatcher"
                )

    async def aclose(self) -> None:
        """Stop reception and fail an outstanding command immediately."""

        self._closed = True
        closed = ESP3DispatcherClosed("ESP3 dispatcher was closed")
        self._set_terminal(closed)
        self._fail_waiter(closed)
        task, self._receiver_task = self._receiver_task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def send_frame(self, frame: ESP3Frame) -> None:
        """Send one native frame through the transport."""

        if not isinstance(frame, ESP3Frame):
            raise TypeError("frame must be an ESP3Frame")
        await self.start()
        if self._failure is not None:
            raise self._failure
        result = self.transport.send(frame)
        if not inspect.isawaitable(result):
            raise TypeError("ESP3 transport send(frame) must be async")
        await result

    async def receive_packet(self) -> Any:
        """Wait for the next unsolicited non-error semantic packet."""

        return await self._receive_queue(self.packets)

    async def receive_radio(self) -> RadioTelegram:
        """Wait for the next RADIO_ERP1 telegram."""

        return await self._receive_queue(self.radio)

    async def receive_event(self) -> ESP3Event:
        """Wait for the next ESP3 event."""

        return await self._receive_queue(self.events)

    async def execute(
        self, command: ESP3Command, *, timeout: float = 1.0
    ) -> ESP3Response:
        """Convenience proxy to the serialized command client."""

        return await self.command_client.execute(command, timeout=timeout)

    async def _receive_one(self) -> ESP3Frame:
        receive = getattr(self.transport, "receive", None)
        result = receive() if callable(receive) else self.transport.received.get()
        if not inspect.isawaitable(result):
            raise TypeError("ESP3 transport receive operation must be async")
        frame = await result
        if not isinstance(frame, ESP3Frame):
            raise TypeError("ESP3 transport yielded a non-ESP3Frame value")
        return frame

    async def _receive_loop(self) -> None:
        try:
            while True:
                frame = await self._receive_one()
                self._received_frames += 1
                try:
                    packet = decode_esp3_packet(frame)
                except ESP3PacketError as exc:
                    self._decode_errors += 1
                    await self.errors.put((frame, exc))
                    continue
                await self._route(packet)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failure = exc
            self._set_terminal(exc)
            self._fail_waiter(exc)

    async def _route(self, packet: Any) -> None:
        if isinstance(packet, ESP3Response):
            waiter = self._response_waiter
            if waiter is not None and not waiter.done():
                self._command_responses += 1
                waiter.set_result(packet)
            else:
                self._unsolicited_responses += 1
                await self.responses.put(packet)
                await self.packets.put(packet)
            return

        if isinstance(packet, RadioTelegram):
            self._radio_packets += 1
            await self.radio.put(packet)
        elif isinstance(packet, ESP3Event):
            self._event_packets += 1
            await self.events.put(packet)
        elif isinstance(packet, UnknownESP3Packet):
            self._unknown_packets += 1
            await self.unknown.put(packet)
        await self.packets.put(packet)

    def _fail_waiter(self, error: BaseException) -> None:
        waiter = self._response_waiter
        if waiter is not None and not waiter.done():
            waiter.set_exception(error)

    def _set_terminal(self, error: BaseException) -> None:
        if self._terminal_error is None:
            self._terminal_error = error
            self._terminal_event.set()

    async def _receive_queue(self, queue: asyncio.Queue[Any]) -> Any:
        """Wait for queued data or fail promptly when reception terminates."""

        await self.start()
        if not queue.empty():
            return queue.get_nowait()
        if self._terminal_event.is_set():
            assert self._terminal_error is not None
            raise self._terminal_error

        queue_task = asyncio.create_task(queue.get())
        terminal_task = asyncio.create_task(self._terminal_event.wait())
        try:
            done, _ = await asyncio.wait(
                (queue_task, terminal_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if queue_task in done:
                return queue_task.result()
            if not queue.empty():
                return queue.get_nowait()
            assert self._terminal_error is not None
            raise self._terminal_error
        finally:
            for task in (queue_task, terminal_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(queue_task, terminal_task, return_exceptions=True)


class ESP3CommandClient:
    """Serialize ESP3 commands and correlate the next response safely."""

    def __init__(self, dispatcher: ESP3Dispatcher) -> None:
        self.dispatcher = dispatcher
        self._command_lock = asyncio.Lock()

    async def execute(
        self, command: ESP3Command, *, timeout: float = 1.0
    ) -> ESP3Response:
        """Send one command and wait for its response within ``timeout``."""

        if not isinstance(command, ESP3Command):
            raise TypeError("command must be an ESP3Command")
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)):
            raise TypeError("timeout must be a number")
        timeout = float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be a finite number greater than zero")

        async with self._command_lock:
            await self.dispatcher.start()
            if self.dispatcher._failure is not None:
                raise self.dispatcher._failure
            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout
            waiter: asyncio.Future[ESP3Response] = loop.create_future()
            self.dispatcher._response_waiter = waiter
            send_task = loop.create_task(
                self.dispatcher.send_frame(command.to_frame()),
                name="eltakobus-esp3-command-send",
            )
            try:
                try:
                    done, _ = await asyncio.wait(
                        (send_task, waiter),
                        timeout=max(0.0, deadline - loop.time()),
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        raise asyncio.TimeoutError

                    if waiter in done:
                        if waiter.exception() is not None:
                            raise waiter.exception()  # type: ignore[misc]
                        await asyncio.wait_for(
                            send_task, max(0.0, deadline - loop.time())
                        )
                        return waiter.result()

                    await send_task
                    return await asyncio.wait_for(
                        asyncio.shield(waiter),
                        max(0.0, deadline - loop.time()),
                    )
                except asyncio.TimeoutError as exc:
                    raise ESP3CommandTimeout(
                        "ESP3 command 0x%02X timed out after %.3f seconds" %
                        (command.command_code, timeout)
                    ) from exc
            finally:
                if not send_task.done():
                    send_task.cancel()
                await asyncio.gather(send_task, return_exceptions=True)
                if self.dispatcher._response_waiter is waiter:
                    self.dispatcher._response_waiter = None
                if not waiter.done():
                    waiter.cancel()


__all__ = [
    "ESP3DispatcherError",
    "ESP3DispatcherClosed",
    "ESP3CommandTimeout",
    "ESP3DispatcherDiagnostics",
    "ESP3Dispatcher",
    "ESP3CommandClient",
]
