"""Explicit, policy-controlled sessions for generic UTE teach-in.

Constructing a :class:`UTETeachInSession` has no side effects.  A response is
only sent when an application calls :meth:`respond` with a concrete decision,
or calls :meth:`process_once` with an explicit policy callback.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional

from .radio import RadioTelegram
from .ute import (
    UTEParseError,
    UTERequest,
    UTEResponse,
    UTEResponseCode,
    UTE_RESPONSE_COMMAND,
    UTE_RORG,
)


class UTESessionStatus(str, Enum):
    """Result of one explicit UTE policy decision."""

    RESPONSE_SENT = "response_sent"
    NO_RESPONSE_REQUIRED = "no_response_required"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class UTESessionResult:
    """Observable result of processing one UTE query."""

    request: UTERequest
    status: UTESessionStatus
    decision: Optional[UTEResponseCode] = None
    response: Optional[UTEResponse] = None

    @property
    def sent(self) -> bool:
        """Whether a response was handed to the transport."""

        return self.status is UTESessionStatus.RESPONSE_SENT


UTEPolicy = Callable[[UTERequest], Any]


class UTETeachInSession:
    """Receive UTE queries and apply only caller-provided decisions.

    The transport contract is intentionally small: it must provide async
    ``send(message)`` and either async ``receive()`` or an ``asyncio.Queue``-like
    ``received.get()``.  Non-UTE and malformed telegrams are preserved in
    :attr:`unmatched`; malformed UTE telegrams are also listed in
    :attr:`parse_errors`.

    The session has no receiver task and does nothing in the background.
    Applications sharing a transport should put a dispatcher in front of this
    class so that only one component owns the physical receive stream.
    """

    def __init__(
        self,
        transport: Any,
        *,
        local_sender: bytes,
        unmatched_queue: Optional[asyncio.Queue[Any]] = None,
    ) -> None:
        if not callable(getattr(transport, "send", None)):
            raise TypeError("transport must provide async send(message)")
        if not callable(getattr(transport, "receive", None)) and not callable(
            getattr(getattr(transport, "received", None), "get", None)
        ):
            raise TypeError(
                "transport must provide async receive() or received.get()"
            )
        if isinstance(local_sender, (str, int)):
            raise TypeError("local_sender must be bytes-like")
        try:
            normalized_sender = bytes(local_sender)
        except (TypeError, ValueError) as exc:
            raise TypeError("local_sender must be bytes-like") from exc
        if len(normalized_sender) != 4:
            raise ValueError("local_sender must contain exactly four bytes")

        self.transport = transport
        self.local_sender = normalized_sender
        self.unmatched: asyncio.Queue[Any] = unmatched_queue or asyncio.Queue()
        self.parse_errors: list[UTEParseError] = []
        self._receive_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()

    async def wait_for_request(self, *, timeout: Optional[float] = None) -> UTERequest:
        """Wait for the next valid UTE query while preserving other traffic."""

        if timeout is not None and timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        loop = asyncio.get_running_loop()
        deadline = None if timeout is None else loop.time() + timeout

        async with self._receive_lock:
            while True:
                remaining = None if deadline is None else max(0.0, deadline - loop.time())
                message = await self._receive(remaining)
                if not isinstance(message, RadioTelegram) or message.rorg != UTE_RORG:
                    await self.unmatched.put(message)
                    continue
                if (
                    len(message.payload) == 7
                    and message.payload[0] & 0x0F == UTE_RESPONSE_COMMAND
                ):
                    try:
                        UTEResponse.from_telegram(message)
                    except UTEParseError as exc:
                        self.parse_errors.append(exc)
                    await self.unmatched.put(message)
                    continue
                try:
                    return UTERequest.from_telegram(message)
                except UTEParseError as exc:
                    self.parse_errors.append(exc)
                    await self.unmatched.put(message)

    async def respond(
        self,
        request: UTERequest,
        decision: UTEResponseCode,
    ) -> UTESessionResult:
        """Send one explicitly selected response when the query requests it."""

        if not isinstance(request, UTERequest):
            raise TypeError("request must be a UTERequest")
        if isinstance(decision, bool):
            raise TypeError("decision must not be a boolean")
        try:
            selected = UTEResponseCode(decision)
        except (TypeError, ValueError) as exc:
            raise ValueError("decision must be a valid UTEResponseCode") from exc

        if not request.response_expected:
            return UTESessionResult(
                request=request,
                status=UTESessionStatus.NO_RESPONSE_REQUIRED,
                decision=selected,
            )

        response = request.build_response(self.local_sender, selected)
        telegram = response.to_telegram()
        async with self._send_lock:
            send_result = self.transport.send(telegram)
            if not inspect.isawaitable(send_result):
                raise TypeError("transport.send(message) must be async")
            await send_result
        return UTESessionResult(
            request=request,
            status=UTESessionStatus.RESPONSE_SENT,
            decision=selected,
            response=response,
        )

    async def process_once(
        self,
        *,
        policy: UTEPolicy,
        timeout: Optional[float] = None,
        decision_timeout: Optional[float] = 0.45,
    ) -> UTESessionResult:
        """Wait for one query and evaluate an explicitly supplied policy.

        The policy may be synchronous or asynchronous and must return a
        :class:`UTEResponseCode`, or ``None`` to leave the request untouched.
        No fallback acceptance or rejection is sent if the policy fails or
        exceeds ``decision_timeout``.
        """

        if not callable(policy):
            raise TypeError("policy must be callable")
        if decision_timeout is not None and decision_timeout <= 0:
            raise ValueError("decision_timeout must be greater than zero")

        request = await self.wait_for_request(timeout=timeout)
        decision_awaitable = self._evaluate_policy(policy, request)
        if decision_timeout is None:
            decision = await decision_awaitable
        else:
            decision = await asyncio.wait_for(decision_awaitable, decision_timeout)
        if decision is None:
            return UTESessionResult(
                request=request,
                status=UTESessionStatus.IGNORED,
            )
        return await self.respond(request, decision)

    @staticmethod
    async def _evaluate_policy(policy: UTEPolicy, request: UTERequest) -> Any:
        """Evaluate sync policies off-loop and await async policy results."""

        if inspect.iscoroutinefunction(policy):
            return await policy(request)
        decision = await asyncio.to_thread(policy, request)
        if inspect.isawaitable(decision):
            return await decision
        return decision

    async def _receive(self, timeout: Optional[float]) -> Any:
        receiver = getattr(self.transport, "receive", None)
        awaitable = receiver() if callable(receiver) else self.transport.received.get()
        if not inspect.isawaitable(awaitable):
            raise TypeError("transport receive operation must be async")
        if timeout is None:
            return await awaitable
        return await asyncio.wait_for(awaitable, timeout)


__all__ = [
    "UTEPolicy",
    "UTESessionResult",
    "UTESessionStatus",
    "UTETeachInSession",
]
