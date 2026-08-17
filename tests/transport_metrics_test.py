"""Tests for opt-in transport metrics without serial or gateway hardware."""

import threading
import unittest

from eltakobus.transactions import TransactionMetrics
from eltakobus.transport_metrics import TransportMetrics


class FakeClock:
    def __init__(self):
        self.value = 10.0

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class TransportMetricsTest(unittest.TestCase):
    """Verify rates, retries, reconnect history and concurrent recording."""

    def test_snapshot_reports_rates_retries_and_reconnects(self):
        """Cumulative rates and reconnect transitions are deterministic."""

        clock = FakeClock()
        metrics = TransportMetrics(clock=clock, history_limit=4)
        metrics.record_connection(True, reason="initial")
        metrics.record_message("sent", 2)
        metrics.record_message("received")
        metrics.record_transaction(TransactionMetrics(attempts=2, retries=1, elapsed=0.2))
        clock.advance(2.0)
        metrics.record_connection(False, reason="device disappeared")
        metrics.record_reconnect_failure()
        metrics.record_connection(True, reason="device returned")

        snapshot = metrics.snapshot()
        self.assertEqual((2, 1, 1, 1), (
            snapshot.messages_sent,
            snapshot.messages_received,
            snapshot.retries,
            snapshot.transactions,
        ))
        self.assertEqual(1, snapshot.reconnects)
        self.assertEqual(1, snapshot.reconnect_failures)
        self.assertEqual(1.0, snapshot.sent_rate)
        self.assertEqual(0.5, snapshot.received_rate)
        self.assertEqual(["initial", "device disappeared", "device returned"], [
            event.reason for event in snapshot.reconnect_history
        ])

    def test_history_is_bounded_and_snapshot_is_detached(self):
        """Long-running transports retain only the configured recent history."""

        clock = FakeClock()
        metrics = TransportMetrics(clock=clock, history_limit=2)
        for connected, reason in ((True, "one"), (False, "two"), (True, "three")):
            metrics.record_connection(connected, reason=reason)
            clock.advance(1)
        snapshot = metrics.snapshot()
        self.assertEqual(["two", "three"], [event.reason for event in snapshot.reconnect_history])
        self.assertEqual(2, len(snapshot.reconnect_history))

    def test_initial_connection_is_not_counted_as_reconnect(self):
        """The first successful connection is distinct from a reconnect."""

        metrics = TransportMetrics()
        metrics.record_connection(False, reason="worker starting")
        metrics.record_connection(True, reason="initial connection")
        metrics.record_connection(False, reason="device disappeared")
        metrics.record_connection(True, reason="device returned")
        snapshot = metrics.snapshot()
        self.assertEqual(1, snapshot.reconnects)

    def test_repeated_status_callbacks_are_not_transitions(self):
        """Repeated status reports do not create fake reconnect history."""

        metrics = TransportMetrics()
        metrics.record_connection(False, reason="initial")
        metrics.record_connection(False, reason="retrying")
        metrics.record_connection(True, reason="connected")
        metrics.record_connection(True, reason="still connected")
        snapshot = metrics.snapshot()
        self.assertEqual(2, snapshot.connection_events)
        self.assertEqual(0, snapshot.reconnects)
        self.assertEqual(["initial", "connected"], [event.reason for event in snapshot.reconnect_history])

    def test_invalid_events_fail_without_mutating_metrics(self):
        """Invalid caller data is rejected before it can corrupt counters."""

        metrics = TransportMetrics()
        with self.assertRaises(ValueError):
            metrics.record_message("unknown")
        with self.assertRaises(ValueError):
            metrics.record_retry(-1)
        with self.assertRaises(TypeError):
            metrics.record_transaction(object())
        self.assertEqual(0, metrics.snapshot().messages_sent)
        self.assertEqual(0, metrics.snapshot().retries)

    def test_concurrent_recording_is_safe(self):
        """Worker-like concurrent send and receive reporting has no lost updates."""

        metrics = TransportMetrics()

        def record(direction):
            for _ in range(500):
                metrics.record_message(direction)
                metrics.record_retry()

        threads = [threading.Thread(target=record, args=(direction,)) for direction in ("sent", "received")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        snapshot = metrics.snapshot()
        self.assertEqual(500, snapshot.messages_sent)
        self.assertEqual(500, snapshot.messages_received)
        self.assertEqual(1000, snapshot.retries)

    def test_as_dict_is_json_native_and_not_live_state(self):
        """Diagnostic serialization contains plain values and bounded history."""

        metrics = TransportMetrics()
        metrics.record_connection(True)
        encoded = metrics.snapshot().as_dict()
        self.assertIsInstance(encoded["reconnect_history"], list)
        self.assertIs(encoded["connected"], True)
        encoded["reconnect_history"].clear()
        self.assertEqual(1, len(metrics.snapshot().reconnect_history))


if __name__ == "__main__":
    unittest.main()
