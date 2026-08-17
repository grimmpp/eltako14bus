"""Thread-safe, transport-neutral metrics for serial and gateway adapters.

The collector is deliberately opt-in.  Existing transports can report events
from their current send/receive and status callbacks without changing their
public constructors or timing behavior.  It has no dependency on pyserial,
``enocean`` or any gateway implementation.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Literal


Direction = Literal["sent", "received"]


@dataclass(frozen=True, slots=True)
class ConnectionEvent:
    """One observed connection-state transition."""

    timestamp: float
    connected: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class TransportMetricsSnapshot:
    """Immutable cumulative metrics suitable for logs and diagnostics."""

    captured_at: float
    elapsed: float
    messages_sent: int
    messages_received: int
    retries: int
    transactions: int
    connection_events: int
    reconnects: int
    reconnect_failures: int
    connected: bool | None
    sent_rate: float
    received_rate: float
    reconnect_history: tuple[ConnectionEvent, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-compatible representation without exposing state."""

        return {
            "captured_at": self.captured_at,
            "elapsed": self.elapsed,
            "messages_sent": self.messages_sent,
            "messages_received": self.messages_received,
            "retries": self.retries,
            "transactions": self.transactions,
            "connection_events": self.connection_events,
            "reconnects": self.reconnects,
            "reconnect_failures": self.reconnect_failures,
            "connected": self.connected,
            "sent_rate": self.sent_rate,
            "received_rate": self.received_rate,
            "reconnect_history": [
                {
                    "timestamp": event.timestamp,
                    "connected": event.connected,
                    "reason": event.reason,
                }
                for event in self.reconnect_history
            ],
        }


class TransportMetrics:
    """Collect bounded, cumulative transport telemetry.

    ``record_message`` is safe to call from serial worker threads and
    ``record_connection`` is suitable for existing status callbacks.  The
    collector never performs I/O and never raises for a missing transport.
    Rates are cumulative average messages per second since construction, which
    makes them stable and deterministic for diagnostics and tests.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        history_limit: int = 32,
    ) -> None:
        if history_limit < 1:
            raise ValueError("history_limit must be at least one")
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._messages_sent = 0
        self._messages_received = 0
        self._retries = 0
        self._transactions = 0
        self._connection_events = 0
        self._reconnects = 0
        self._reconnect_failures = 0
        self._connected: bool | None = None
        self._ever_connected = False
        self._history: Deque[ConnectionEvent] = deque(maxlen=history_limit)

    def record_message(self, direction: Direction, count: int = 1) -> None:
        """Record one or more successfully handed-off messages."""

        if direction not in ("sent", "received"):
            raise ValueError("direction must be 'sent' or 'received'")
        if count < 0:
            raise ValueError("count must not be negative")
        with self._lock:
            if direction == "sent":
                self._messages_sent += count
            else:
                self._messages_received += count

    def record_retry(self, count: int = 1) -> None:
        """Record bounded retry attempts, independently of message counts."""

        if count < 0:
            raise ValueError("count must not be negative")
        with self._lock:
            self._retries += count

    def record_transaction(self, transaction_metrics: object) -> None:
        """Record retry data from ``transactions.TransactionMetrics``.

        Duck typing keeps this module independent from the transaction layer
        and permits callers to use equivalent metrics objects.
        """

        retries = getattr(transaction_metrics, "retries", None)
        if not isinstance(retries, int) or retries < 0:
            raise TypeError("transaction_metrics.retries must be a non-negative int")
        with self._lock:
            self._transactions += 1
            self._retries += retries

    def record_connection(self, connected: bool, *, reason: str | None = None) -> None:
        """Record a connection transition and infer successful reconnects."""

        timestamp = self._clock()
        with self._lock:
            connected = bool(connected)
            # Status callbacks may repeat the current state while a worker is
            # waiting for a port to return.  Repeated observations are not
            # transitions and must not inflate reconnect history.
            if self._connected is connected:
                return
            if self._ever_connected and self._connected is False and connected:
                self._reconnects += 1
            if connected:
                self._ever_connected = True
            self._connected = connected
            self._connection_events += 1
            self._history.append(ConnectionEvent(timestamp, connected, reason))

    def record_reconnect_failure(self) -> None:
        """Record an unsuccessful reconnect attempt."""

        with self._lock:
            self._reconnect_failures += 1

    def snapshot(self) -> TransportMetricsSnapshot:
        """Return an immutable point-in-time view of all collected metrics."""

        captured_at = self._clock()
        with self._lock:
            elapsed = max(0.0, captured_at - self._started)
            divisor = elapsed if elapsed > 0.0 else 1.0
            return TransportMetricsSnapshot(
                captured_at=captured_at,
                elapsed=elapsed,
                messages_sent=self._messages_sent,
                messages_received=self._messages_received,
                retries=self._retries,
                transactions=self._transactions,
                connection_events=self._connection_events,
                reconnects=self._reconnects,
                reconnect_failures=self._reconnect_failures,
                connected=self._connected,
                sent_rate=self._messages_sent / divisor,
                received_rate=self._messages_received / divisor,
                reconnect_history=tuple(self._history),
            )


__all__ = ["ConnectionEvent", "TransportMetrics", "TransportMetricsSnapshot"]
