"""Tests for passive LAN-gateway discovery without zeroconf or network I/O."""

import ipaddress
import unittest

from eltakobus.const import GatewayDeviceType
from eltakobus.lan_discovery import LanGatewayDiscovery, SERVICE_TYPE_SMARTCONN, SERVICE_TYPE_TCM515


class FakeServiceInfo:
    def __init__(self, *, server="gateway.local.", addresses=(), port=5000, properties=None):
        self.server = server
        self.addresses = [ipaddress.ip_address(address).packed for address in addresses]
        self.port = port
        self.properties = properties or {}


class FakeZeroconf:
    def __init__(self, info):
        self.info = info
        self.closed = False

    def get_service_info(self, service_type, name):
        return self.info.get((service_type, name))

    def close(self):
        self.closed = True


class FakeBrowser:
    def __init__(self, zc, service_type, listener):
        self.service_type = service_type
        self.listener = listener
        self.cancelled = False

    def cancel(self):
        self.cancelled = True


class LanDiscoveryTest(unittest.TestCase):
    """Verify mappings, lifecycle and endpoint filtering with fake browsers."""

    def test_callbacks_resolve_services_and_map_known_products(self):
        smartconn_name = "SmartConn ABC._bsc-sc-socket._tcp.local."
        eul_name = "EUL-42._tcm515._tcp.local."
        virtual_name = "Virtual-Network-Gateway-Adapter-1._bsc-sc-socket._tcp.local."
        info = {
            (SERVICE_TYPE_SMARTCONN, smartconn_name): FakeServiceInfo(addresses=("192.0.2.10",)),
            (SERVICE_TYPE_TCM515, eul_name): FakeServiceInfo(addresses=("192.0.2.11",), port=2325),
            (SERVICE_TYPE_SMARTCONN, virtual_name): FakeServiceInfo(addresses=("192.0.2.12",)),
        }
        zc = FakeZeroconf(info)
        browsers = []

        def browser_factory(z, service_type, listener):
            browser = FakeBrowser(z, service_type, listener)
            browsers.append(browser)
            return browser

        discovery = LanGatewayDiscovery(zeroconf_factory=lambda: zc, browser_factory=browser_factory)
        discovery.start()
        self.assertEqual(2, len(browsers))
        for service_type, name in info:
            browsers[0].listener.add_service(zc, service_type, name)

        services = {service.name: service for service in discovery.services}
        self.assertEqual(GatewayDeviceType.LAN, services[smartconn_name].gateway_device_type)
        self.assertEqual(GatewayDeviceType.LAN, services[eul_name].gateway_device_type)
        self.assertEqual(GatewayDeviceType.LAN_ESP2, services[virtual_name].gateway_device_type)
        self.assertEqual(("192.0.2.11", 2325), services[eul_name].endpoint)
        discovery.stop()
        self.assertTrue(zc.closed)
        self.assertTrue(all(browser.cancelled for browser in browsers))

    def test_update_remove_and_endpoint_search(self):
        name = "SmartConn._bsc-sc-socket._tcp.local."
        changes = []
        discovery = LanGatewayDiscovery(on_change=lambda action, service: changes.append((action, service)))
        service = discovery.add_service(SERVICE_TYPE_SMARTCONN, name, FakeServiceInfo(addresses=("198.51.100.5",), port=1234))
        self.assertEqual(("198.51.100.5", 1234), service.endpoint)
        updated = discovery.update_service(SERVICE_TYPE_SMARTCONN, name, FakeServiceInfo(addresses=("198.51.100.6",), port=4321))
        self.assertEqual(("198.51.100.6", 4321), updated.endpoint)
        self.assertIs(updated, discovery.find_endpoint(gateway_device_type="lan"))
        removed = discovery.remove_service(SERVICE_TYPE_SMARTCONN, name)
        self.assertEqual(updated, removed)
        self.assertIsNone(discovery.find_endpoint())
        self.assertEqual(["add", "update", "remove"], [action for action, _ in changes])

    def test_missing_ipv4_is_not_an_endpoint(self):
        service = LanGatewayDiscovery().add_service(SERVICE_TYPE_TCM515, "EUL._tcm515._tcp.local.", FakeServiceInfo(addresses=("2001:db8::1",)))
        self.assertIsNone(service.endpoint)

    def test_zeroconf_is_lazy_and_not_needed_for_injected_browser(self):
        discovery = LanGatewayDiscovery(zeroconf_factory=lambda: FakeZeroconf({}), browser_factory=lambda z, service_type, listener: FakeBrowser(z, service_type, listener))
        self.assertFalse(discovery.running)
        discovery.start()
        self.assertTrue(discovery.running)
        discovery.stop()


if __name__ == "__main__":
    unittest.main()
