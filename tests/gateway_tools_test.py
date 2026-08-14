"""Offline tests for gateway discovery, identity parsing, and diagnostics.

They deliberately do not open a serial port, so CI can run them without hardware.  The tests
also document that passive scanning and active identity probing are separate operations.
"""
import asyncio
import unittest

from eltakobus.const import GatewayDeviceType, baud_rate_for
from eltakobus.diagnostics import probe_devices
from eltakobus.gateway_identity import (
    async_read_identity, fam_usb_base_id_request, format_id, parse_version_response,
)
from eltakobus.gateway_scan import scan_serial_ports
from eltakobus.message import EltakoDiscoveryReply
from eltakobus.error import TimeoutError


class FakePort:
    device = "/dev/ttyUSB-test"
    manufacturer = "EnOcean GmbH"
    product = "USB 300"
    serial_number = "TEST123"
    interface = "if01"


class FakeBus:
    async def exchange(self, request, response_type, retries=1):
        if request.address == 2:
            raise TimeoutError("no response")
        return EltakoDiscoveryReply(1, 1, 1, bytes.fromhex("04044200"), False)


class IdentityBus:
    async def exchange(self, request, response_type, retries=1, timeout=1.0):
        class Response:
            body = bytes((0, 0, 0xA0, 0x02, 0x8C, 0x5C, 0, 0, 0, 0, 0))
        return Response()


class GatewayToolsTest(unittest.TestCase):
    def test_scan_is_passive_and_suggests_esp3_for_usb300(self):
        """Descriptor scanning must work without opening the fake port."""
        result = scan_serial_ports(device_globs=(), by_id_dir="/does/not/exist",
                                   by_path_dir="/does/not/exist", ports=[FakePort()])
        self.assertEqual(result[0].device, "/dev/ttyUSB-test")
        self.assertIn(GatewayDeviceType.USB300.value, result[0].suggested_device_types)
        self.assertEqual(result[0].serial_number, "TEST123")

    def test_identity_parsers(self):
        """ESP2/ESP3 identity payloads are parsed deterministically offline."""
        self.assertEqual(format_id(bytes.fromhex("A0 02 8C 5C")), "A0-02-8C-5C")
        payload = bytes(range(16)) + b"ESP3 test\0" + bytes(6)
        self.assertEqual(parse_version_response(payload)["chip_id"], "08-09-0A-0B")
        self.assertEqual(fam_usb_base_id_request().serialize()[2:4], bytes.fromhex("AB 58"))

    def test_gateway_constants_preserve_stable_values(self):
        """Portable constants keep the stable names and baud-rate semantics."""
        self.assertEqual(GatewayDeviceType.find("fam14"), GatewayDeviceType.FAM14)
        self.assertTrue(GatewayDeviceType.is_bus_gateway("fgw14usb"))
        self.assertEqual(baud_rate_for("fam-usb"), 9600)

    def test_probe_records_success_and_timeout(self):
        """A diagnostic scan reports missing devices without aborting the complete run."""
        results = asyncio.run(probe_devices(FakeBus(), [1, 2]))
        self.assertEqual([item.discovered for item in results], [True, False])
        self.assertEqual(results[1].error, "timeout")

    def test_active_identity_uses_existing_bus(self):
        """FAM-USB identity reads reuse the caller's interface instead of reopening it."""
        identity = asyncio.run(async_read_identity(IdentityBus(), "fam-usb"))
        self.assertEqual(identity["base_id"], "A0-02-8C-5C")


if __name__ == "__main__":
    unittest.main()
