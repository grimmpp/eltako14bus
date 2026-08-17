"""Opt-in, transport-neutral request/response transactions.

This module deliberately does not change the legacy ``BusInterface`` API.
It wraps a small async transport contract instead: a transport must provide
``async send(request)`` and either ``async receive()`` or a ``received``
``asyncio.Queue``.  A single dispatcher consumes that receive stream, matches
responses to pending requests, and republishes unrelated telegrams.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Optional, TypeVar

from .error import (
    CommandRejected,
    CommandTimeout,
    NotImplementedError as EltakoNotImplementedError,
    TransactionCancelled,
    UnsupportedCommand,
)


MessageT = TypeVar("MessageT")
Matcher = Callable[[Any], bool]
UnmatchedCallback = Callable[[Any], Any]
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class TransactionOptions:
    """Bounded wait and retry policy for one transaction.

    ``retries`` is the number of *additional* attempts after the first send;
    it is therefore zero by default.  The total number of sends is always at
    most ``retries + 1``.
    """

    timeout: float = 1.0
    retries: int = 0
    retry_delay: float = 0.0

    def __post_init__(self) -> None:
        if self.timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if self.retries < 0:
            raise ValueError("retries must not be negative")
        if self.retry_delay < 0:
            raise ValueError("retry_delay must not be negative")


@dataclass(frozen=True)
class TransactionMetrics:
    """Monotonic timing and bounded-attempt information for a transaction."""

    attempts: int
    retries: int
    elapsed: float


@dataclass(frozen=True)
class TransactionResult(Generic[MessageT]):
    """A successfully matched transaction response and its metrics."""

    response: MessageT
    metrics: TransactionMetrics

    @property
    def attempts(self) -> int:
        """Number of sends performed, retained as a convenient shorthand."""

        return self.metrics.attempts

    @property
    def elapsed(self) -> float:
        """Elapsed monotonic seconds from the first send to completion."""

        return self.metrics.elapsed


@dataclass
class _Waiter:
    matcher: Matcher
    rejecter: Optional[Matcher]
    future: asyncio.Future[Any]


class TransactionManager:
    """Match responses from a shared async receive stream to sent requests.

    The manager is intentionally opt-in.  It can be layered over new
    transports without changing existing serial/TCP implementations.  At most
    one pending transaction receives a matching message; the oldest matching
    waiter wins.  Messages that do not match any pending transaction are
    preserved in :attr:`unmatched` and passed to ``unmatched_callback``.
    """

    def __init__(
        self,
        transport: Any,
        *,
        unmatched_queue: Optional[asyncio.Queue[Any]] = None,
        unmatched_callback: Optional[UnmatchedCallback] = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(getattr(transport, "send", None)):
            raise UnsupportedCommand("Transaction transport must provide async send(request)")
        if not callable(getattr(transport, "receive", None)) and not callable(
            getattr(getattr(transport, "received", None), "get", None)
        ):
            raise UnsupportedCommand(
                "Transaction transport must provide async receive() or received.get()"
            )

        self.transport = transport
        self.unmatched: asyncio.Queue[Any] = unmatched_queue or asyncio.Queue()
        self.unmatched_callback = unmatched_callback
        self._clock = clock
        self._pending: list[_Waiter] = []
        self._pending_lock = asyncio.Lock()
        self._start_lock = asyncio.Lock()
        self._receiver_task: Optional[asyncio.Task[None]] = None
        self._receiver_error: Optional[BaseException] = None
        self._owner_loop: Optional[asyncio.AbstractEventLoop] = None
        self._closed = False

    async def __aenter__(self) -> "TransactionManager":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self.aclose()

    async def start(self) -> None:
        """Start the receive dispatcher once in the current event loop."""

        loop = asyncio.get_running_loop()
        async with self._start_lock:
            if self._closed:
                raise UnsupportedCommand("Transaction manager is closed")
            if self._owner_loop is not None and self._owner_loop is not loop:
                raise RuntimeError("TransactionManager cannot span event loops")
            self._owner_loop = loop
            if self._receiver_task is None:
                self._receiver_task = loop.create_task(
                    self._receive_loop(), name="eltakobus-transaction-receiver"
                )

    async def aclose(self) -> None:
        """Stop the dispatcher and fail outstanding waiters without consuming data."""

        self._closed = True
        receiver = self._receiver_task
        self._receiver_task = None
        if receiver is not None:
            receiver.cancel()
            # Consume every terminal receiver outcome.  In particular, a
            # transport failure must not be re-raised from cleanup after it
            # has already been delivered to active transactions.
            await asyncio.gather(receiver, return_exceptions=True)
        async with self._pending_lock:
            waiters, self._pending = self._pending, []
        for waiter in waiters:
            if not waiter.future.done():
                waiter.future.set_exception(TransactionCancelled("Transaction manager was closed"))

    async def request(
        self,
        request: Any,
        *,
        matcher: Matcher,
        options: TransactionOptions = TransactionOptions(),
        rejecter: Optional[Matcher] = None,
    ) -> TransactionResult[Any]:
        """Send ``request`` and wait for a request-specific matching response.

        A matching ``rejecter`` takes precedence over ``matcher`` and raises
        :class:`~eltakobus.error.CommandRejected`.  On task cancellation the
        pending waiter is removed before :class:`TransactionCancelled` is
        raised; a late response is consequently preserved as unmatched data.
        """

        if not callable(matcher):
            raise TypeError("matcher must be callable")
        if rejecter is not None and not callable(rejecter):
            raise TypeError("rejecter must be callable")
        if not isinstance(options, TransactionOptions):
            raise TypeError("options must be a TransactionOptions instance")

        await self.start()
        started = self._clock()
        attempts = 0
        loop = asyncio.get_running_loop()

        for attempt in range(options.retries + 1):
            attempts += 1
            deadline = self._clock() + options.timeout
            future: asyncio.Future[Any] = loop.create_future()
            waiter = _Waiter(matcher=matcher, rejecter=rejecter, future=future)
            await self._add_waiter(waiter)
            try:
                send_result = self.transport.send(request)
                if not inspect.isawaitable(send_result):
                    raise UnsupportedCommand("Transaction transport send() must be async")
                await self._send_with_deadline(send_result, future, deadline)
                response = await asyncio.wait_for(
                    asyncio.shield(future), self._remaining(deadline)
                )
            except asyncio.TimeoutError:
                await self._remove_waiter(waiter)
                if attempt == options.retries:
                    metrics = self._metrics(started, attempts)
                    error = CommandTimeout(
                        "Transaction timed out after %d attempt(s)" % attempts
                    )
                    error.metrics = metrics
                    raise error
            except asyncio.CancelledError as exc:
                await self._remove_waiter(waiter)
                raise TransactionCancelled("Transaction was cancelled") from exc
            except (NotImplementedError, EltakoNotImplementedError) as exc:
                await self._remove_waiter(waiter)
                raise UnsupportedCommand("Transport does not support this command") from exc
            except CommandRejected as exc:
                await self._remove_waiter(waiter)
                exc.metrics = self._metrics(started, attempts)
                raise
            except Exception:
                await self._remove_waiter(waiter)
                raise
            else:
                await self._remove_waiter(waiter)
                return TransactionResult(response=response, metrics=self._metrics(started, attempts))

            if options.retry_delay:
                try:
                    await asyncio.sleep(options.retry_delay)
                except asyncio.CancelledError as exc:
                    raise TransactionCancelled("Transaction was cancelled") from exc

        raise AssertionError("unreachable: bounded transaction loop exhausted")

    async def _add_waiter(self, waiter: _Waiter) -> None:
        async with self._pending_lock:
            if self._closed:
                raise TransactionCancelled("Transaction manager was closed")
            if self._receiver_error is not None:
                raise self._receiver_error
            self._pending.append(waiter)

    async def _remove_waiter(self, waiter: _Waiter) -> None:
        async with self._pending_lock:
            try:
                self._pending.remove(waiter)
            except ValueError:
                pass

    async def _receive_loop(self) -> None:
        try:
            while True:
                message = await self._receive_one()
                await self._dispatch(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # A failed receive stream cannot satisfy any current or future
            # transaction.  Preserve the transport exception and wake every
            # active waiter immediately instead of making requests expire at
            # their normal command timeout.
            self._receiver_error = exc
            async with self._pending_lock:
                waiters, self._pending = self._pending, []
            for waiter in waiters:
                if not waiter.future.done():
                    waiter.future.set_exception(exc)
            _LOGGER.warning(
                "Transaction receive stream failed; active requests were aborted",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def _receive_one(self) -> Any:
        receive = getattr(self.transport, "receive", None)
        if callable(receive):
            value = receive()
        else:
            value = self.transport.received.get()
        if not inspect.isawaitable(value):
            raise UnsupportedCommand("Transaction transport receive operation must be async")
        return await value

    async def _dispatch(self, message: Any) -> None:
        selected: Optional[_Waiter] = None
        rejected = False
        async with self._pending_lock:
            for waiter in self._pending:
                if waiter.future.done():
                    continue
                if waiter.rejecter is not None and self._matches(
                    waiter.rejecter, message, "rejecter"
                ):
                    selected, rejected = waiter, True
                    break
                if self._matches(waiter.matcher, message, "matcher"):
                    selected = waiter
                    break

        if selected is None:
            await self.unmatched.put(message)
            callback = self.unmatched_callback
            if callback is not None:
                try:
                    result = callback(message)
                    if inspect.isawaitable(result):
                        await result
                except Exception:
                    # A telemetry callback must not stop dispatching protocol
                    # traffic or make a future transaction hang.
                    _LOGGER.exception("Unmatched transaction callback failed")
            return

        if rejected:
            error = CommandRejected("Transaction request was rejected by its response")
            error.response = message
            if not selected.future.done():
                selected.future.set_exception(error)
        elif not selected.future.done():
            selected.future.set_result(message)

    def _metrics(self, started: float, attempts: int) -> TransactionMetrics:
        return TransactionMetrics(
            attempts=attempts,
            retries=max(0, attempts - 1),
            elapsed=max(0.0, self._clock() - started),
        )

    def _remaining(self, deadline: float) -> float:
        """Return the positive time left in the current attempt."""

        remaining = deadline - self._clock()
        if remaining <= 0:
            raise asyncio.TimeoutError
        return remaining

    async def _send_with_deadline(
        self,
        send_result: Any,
        response_future: asyncio.Future[Any],
        deadline: float,
    ) -> None:
        """Bound sending while still observing receiver-side failures."""

        send_task = asyncio.ensure_future(send_result)
        try:
            done, _ = await asyncio.wait(
                (send_task, response_future),
                timeout=self._remaining(deadline),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise asyncio.TimeoutError

            # A receiver failure is delivered through the response future. It
            # must abort even a send operation that is currently blocked.
            if response_future in done:
                if response_future.cancelled():
                    raise TransactionCancelled("Transaction response was cancelled")
                receiver_error = response_future.exception()
                if receiver_error is not None:
                    raise receiver_error

            await asyncio.wait_for(send_task, self._remaining(deadline))
        except BaseException:
            if not send_task.done():
                send_task.cancel()
            await asyncio.gather(send_task, return_exceptions=True)
            raise

    @staticmethod
    def _matches(predicate: Matcher, message: Any, kind: str) -> bool:
        """Run caller predicates without allowing one bad predicate to kill dispatch."""

        try:
            return bool(predicate(message))
        except Exception:
            _LOGGER.exception("Transaction %s failed for incoming message", kind)
            return False
