"""Serial transports over a real pseudo-terminal.

These tests open an actual serial device through serialx (a pty pair), so they
exercise the serialx calls themselves rather than a mock. They need a POSIX
system with ``pty`` support and are skipped elsewhere.
"""

import asyncio
import os
import sys
import threading
import unittest

try:
    import pty
    import tty
except ImportError:  # pragma: no cover - Windows
    pty = None

from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest
from eltakobus.serial import RS485SerialInterface, RS485SerialInterfaceV2


def discovery_reply():
    return EltakoDiscoveryReply(
        reported_address=1,
        reported_size=1,
        memory_size=127,
        model=bytes.fromhex("04044200"),
        is_fam=False,
    )


class FakeDevice(threading.Thread):
    """Answers every 14-byte request on the pty master, or echoes it."""

    def __init__(self, master, answer=None):
        super().__init__(daemon=True)
        self.master = master
        self.answer = answer
        self.stopped = threading.Event()

    def run(self):
        buffer = b""
        while not self.stopped.is_set():
            try:
                data = os.read(self.master, 256)
            except OSError:
                return
            if self.answer is None:
                os.write(self.master, data)
                continue
            buffer += data
            while len(buffer) >= 14:
                buffer = buffer[14:]
                os.write(self.master, self.answer)


@unittest.skipIf(pty is None or sys.platform == "win32", "needs POSIX pty support")
class SerialxPtyTest(unittest.TestCase):
    def open_pty(self):
        master, slave = pty.openpty()
        tty.setraw(master)
        tty.setraw(slave)
        self.addCleanup(os.close, slave)
        self.addCleanup(os.close, master)
        return master, os.ttyname(slave)

    def start_v2(self, path, **kwargs):
        bus = RS485SerialInterfaceV2(path, auto_reconnect=False, delay_message=0, **kwargs)
        bus.start()
        self.addCleanup(lambda: (bus.stop(), bus.join(3)))
        self.assertTrue(bus.is_serial_connected.wait(5))
        return bus

    def test_v2_exchange_over_real_serial_port(self):
        master, path = self.open_pty()
        device = FakeDevice(master, discovery_reply().serialize())
        device.start()
        self.addCleanup(device.stopped.set)
        bus = self.start_v2(path, disabled_echotest=True)

        reply = asyncio.run(bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply, timeout=2))

        self.assertEqual(discovery_reply().serialize(), reply.serialize())

    def test_v2_echo_detection(self):
        master, path = self.open_pty()
        device = FakeDevice(master)  # echoes everything
        device.start()
        self.addCleanup(device.stopped.set)

        self.assertTrue(self.start_v2(path).suppress_echo)

    def test_v2_echo_detection_without_echo_times_out_cleanly(self):
        _, path = self.open_pty()

        self.assertFalse(self.start_v2(path).suppress_echo)

    def test_legacy_asyncio_interface_over_real_serial_port(self):
        master, path = self.open_pty()
        device = FakeDevice(master, discovery_reply().serialize())
        device.start()
        self.addCleanup(device.stopped.set)

        async def scenario():
            bus = RS485SerialInterface(path, suppress_echo=False)
            task = asyncio.create_task(bus.run(asyncio.get_running_loop()))
            try:
                await asyncio.sleep(0.2)
                return await asyncio.wait_for(
                    bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply), 3
                )
            finally:
                task.cancel()

        reply = asyncio.run(scenario())
        self.assertEqual(discovery_reply().serialize(), reply.serialize())


if __name__ == "__main__":
    unittest.main()
