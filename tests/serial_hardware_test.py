"""Opt-in parallel test for two connected Eltako serial adapters.

This test is skipped unless ELTAKO_SERIAL_HARDWARE_TEST=1 is set. It only
receives existing bus traffic; echo detection is disabled and no messages are
sent by the test.

Use ELTAKO_SERIAL_PORTS with a comma-separated list to override the default
two-port setup when only one adapter is connected.
"""

import asyncio
import json
import logging
import os
import threading
import time
import unittest
from collections import Counter
from pathlib import Path

from eltakobus.serial import RS485SerialInterfaceV2


DEFAULT_PORTS = (
    "/dev/tty.usbserial-AL00FF9B",
    "/dev/tty.usbserial-AQ028YCS",
)
PORTS = tuple(
    port.strip()
    for port in os.environ.get("ELTAKO_SERIAL_PORTS", "").split(",")
    if port.strip()
) or DEFAULT_PORTS


@unittest.skipUnless(
    os.environ.get("ELTAKO_SERIAL_HARDWARE_TEST") == "1",
    "set ELTAKO_SERIAL_HARDWARE_TEST=1 to access real serial hardware",
)
class TestParallelSerialHardware(unittest.TestCase):
    """Run opt-in, read-only checks against whichever configured ports exist."""

    @staticmethod
    def _hardware_test_logger():
        logger = logging.getLogger("eltakobus.serial.hardware_test")
        logger.propagate = False
        if not logger.handlers:
            logger.addHandler(logging.NullHandler())
        return logger

    def _start_connected_buses(self, buses):
        """Start candidates and return only ports that actually connected.

        Missing or inaccessible hardware is deliberately treated as an
        environmental condition. The caller receives the connected subset;
        an empty subset causes the test to be skipped.
        """
        for bus in buses:
            bus.start()

        connected = []
        for bus in buses:
            if bus.is_serial_connected.wait(2):
                connected.append(bus)
            else:
                bus.stop()

        for bus in buses:
            if bus not in connected:
                bus.join(2)

        if not connected:
            self.skipTest("no configured serial hardware is connected")

        return connected

    def test_parallel_receive_queues_read_bus_traffic_without_hanging(self):
        """Read one live frame per connected port with a bounded timeout."""
        buses = [
            RS485SerialInterfaceV2(
                port,
                baud_rate=57600,
                log=self._hardware_test_logger(),
                auto_reconnect=True,
                reconnection_timeout=0.1,
                disabled_echotest=True,
            )
            for port in PORTS
        ]
        buses = self._start_connected_buses(buses)

        timeout = float(os.environ.get("ELTAKO_SERIAL_READ_TIMEOUT", "5"))

        async def read_one_from_each():
            return await asyncio.gather(*(
                asyncio.wait_for(bus.received.get(), timeout)
                for bus in buses
            ))

        try:
            messages = asyncio.run(read_one_from_each())
        finally:
            for bus in buses:
                bus.stop()
            for bus in buses:
                bus.join(5)

        self.assertEqual(len(buses), len(messages))
        self.assertTrue(all(message is not None for message in messages))
        self.assertTrue(all(not bus.is_alive() for bus in buses))

    def test_parallel_passive_soak(self):
        """Collect read-only traffic counts and sample frames for a short soak."""
        duration = float(os.environ.get("ELTAKO_SERIAL_TEST_SECONDS", "30"))
        counters = {port: Counter() for port in PORTS}
        frames = {port: [] for port in PORTS}
        status_events = {port: [] for port in PORTS}
        locks = {port: threading.Lock() for port in PORTS}
        buses = []

        for port in PORTS:
            def callback(message, port=port):
                with locks[port]:
                    counters[port][type(message).__name__] += 1
                    counters[port]["total"] += 1
                    if len(frames[port]) < 100:
                        frames[port].append({
                            "type": type(message).__name__,
                            "hex": message.serialize().hex(),
                        })

            bus = RS485SerialInterfaceV2(
                port,
                baud_rate=57600,
                callback=callback,
                log=self._hardware_test_logger(),
                auto_reconnect=True,
                reconnection_timeout=0.1,
                disabled_echotest=True,
            )
            bus.set_status_changed_handler(
                lambda connected, port=port: status_events[port].append({
                    "connected": connected,
                    "monotonic": time.monotonic(),
                })
            )
            buses.append(bus)

        buses = self._start_connected_buses(buses)
        active_ports = tuple(bus._filename for bus in buses)

        try:
            time.sleep(duration)
        finally:
            for bus in buses:
                bus.stop()
            for bus in buses:
                bus.join(5)

        report_path = os.environ.get("ELTAKO_SERIAL_REPORT")
        if report_path:
            report = {
                "ports": list(active_ports),
                "baud_rate": 57600,
                "duration_seconds": duration,
                "echo_detection": "disabled",
                "writes_performed": False,
                "devices": {
                    port: {
                        "message_counts": dict(counters[port]),
                        "sample_frames": frames[port],
                        "status_events": status_events[port],
                    }
                    for port in active_ports
                },
            }
            Path(report_path).write_text(
                json.dumps(report, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

        for port in active_ports:
            counter = counters[port]
            self.assertFalse(
                next(bus for bus in buses if bus._filename == port).is_alive(),
                port,
            )
            self.assertGreater(counter["total"], 0, (port, dict(counter)))
