"""Unit tests for the eltakotool.py command-line interface.

These tests exercise argument parsing and the ``fakefam`` command's serial
connection handling without opening a real serial port. Running this module
requires the ``eltakotool`` extra in addition to ``serial``, since
``eltakotool.py`` imports ``xdg.BaseDirectory`` at module scope:

    python -m pip install -e '.[serial,eltakotool]'
"""

import asyncio
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import Mock, patch

import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import eltakotool
from eltakobus.message import EltakoPollForced, ESP2Message


class TestArgParser(unittest.TestCase):

    def setUp(self):
        self.parser = eltakotool.build_arg_parser()

    def test_defaults(self):
        opts = self.parser.parse_args(["--eltakobus", "/dev/ttyX", "enumerate"])
        self.assertEqual(57600, opts.baud_rate)
        self.assertIsInstance(opts.baud_rate, int)
        self.assertEqual(2, opts.serial_lib_version)
        self.assertIsInstance(opts.serial_lib_version, int)
        self.assertFalse(opts.cache)
        self.assertFalse(opts.preread)
        self.assertEqual("info", opts.log_level)

    def test_serial_lib_version_is_int_when_given_explicitly(self):
        # Regression test: without type=int, argparse stored the string "1",
        # which then failed both `== 1` and `== 2` comparisons in main() and
        # left `bus` unassigned, crashing with a NameError.
        opts = self.parser.parse_args(
            ["--eltakobus", "/dev/ttyX", "--serial_lib_version", "1", "enumerate"]
        )
        self.assertEqual(1, opts.serial_lib_version)
        self.assertIsInstance(opts.serial_lib_version, int)

    def test_serial_lib_version_rejects_unknown_backend(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--eltakobus", "/dev/ttyX", "--serial_lib_version", "3", "enumerate"]
            )

    def test_baud_rate_is_int_when_given_explicitly(self):
        opts = self.parser.parse_args(
            ["--eltakobus", "/dev/ttyX", "--baud_rate", "9600", "enumerate"]
        )
        self.assertEqual(9600, opts.baud_rate)
        self.assertIsInstance(opts.baud_rate, int)

    def test_missing_command_leaves_command_none(self):
        opts = self.parser.parse_args(["--eltakobus", "/dev/ttyX"])
        self.assertIsNone(opts.command)

    def test_send_raw_parses_hex_bytes(self):
        opts = self.parser.parse_args(
            ["--eltakobus", "/dev/ttyX", "send_raw"]
            + ["0b", "05", "10", "00", "00", "00", "00", "00", "ff", "dd", "cc"]
        )
        self.assertEqual(
            [0x0b, 0x05, 0x10, 0x00, 0x00, 0x00, 0x00, 0x00, 0xff, 0xdd, 0xcc],
            opts.data,
        )

    def test_send_raw_requires_eleven_bytes(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(
                ["--eltakobus", "/dev/ttyX", "send_raw", "0b", "05"]
            )

    def test_dump_verify_reprogram_default_to_bus_yaml(self):
        for command in ("dump", "verify", "reprogram"):
            with self.subTest(command=command):
                opts = self.parser.parse_args(["--eltakobus", "/dev/ttyX", command])
                self.assertEqual(Path("bus.yaml"), opts.filename)

    def test_show_off_default_searchterm_is_empty(self):
        opts = self.parser.parse_args(["--eltakobus", "/dev/ttyX", "show_off"])
        self.assertEqual("", opts.searchterm)

    def test_benchmark_parses_delay_and_request_options(self):
        """The CLI exposes typed benchmark settings to the command handler."""
        opts = self.parser.parse_args(
            [
                "--eltakobus", "/dev/ttyX", "benchmark", "5",
                "--messages", "20", "--delays", "0,0.005,0.01",
                "--timeout", "0.25", "--minimum-success-rate", "0.9",
            ]
        )
        self.assertEqual(5, opts.address)
        self.assertEqual(20, opts.messages)
        self.assertEqual((0.0, 0.005, 0.01), opts.delays)
        self.assertEqual(0.25, opts.timeout)
        self.assertEqual(0.9, opts.minimum_success_rate)

    def test_fakefam_requires_device_argument(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["--eltakobus", "/dev/ttyX", "fakefam"])

    def test_version_flag_exits_cleanly(self):
        with self.assertRaises(SystemExit) as ctx:
            self.parser.parse_args(["--version"])
        self.assertEqual(0, ctx.exception.code)


class TestConflictingTransportOpts(unittest.TestCase):

    def setUp(self):
        self.parser = eltakotool.build_arg_parser()

    def test_neither_transport_given_is_an_error(self):
        opts = self.parser.parse_args(["enumerate"])
        self.assertIn(
            "Autodiscovery", eltakotool.check_conflicting_transport_opts(opts)
        )

    def test_both_transports_given_is_an_error(self):
        opts = self.parser.parse_args(
            ["--rawuri", "coap://x", "--eltakobus", "/dev/ttyX", "enumerate"]
        )
        self.assertIn(
            "conflicting", eltakotool.check_conflicting_transport_opts(opts)
        )

    def test_exactly_one_transport_given_is_fine(self):
        opts = self.parser.parse_args(["--eltakobus", "/dev/ttyX", "enumerate"])
        self.assertIsNone(eltakotool.check_conflicting_transport_opts(opts))

    def test_lan_scan_command_has_wait_and_json_options(self):
        """LAN discovery is a standalone command and does not require a bus URI."""
        opts = self.parser.parse_args(["lan_scan", "--wait", "0", "--json"])
        self.assertEqual("lan_scan", opts.command)
        self.assertEqual(0, opts.wait)
        self.assertTrue(opts.as_json)

    def test_lan_gateway_scan_uses_injected_discovery_without_network(self):
        """The CLI formatter can be tested with a passive discovery double."""
        class FakeDiscovery:
            def start(self):
                pass

            @property
            def services(self):
                return (SimpleNamespace(
                    name="Virtual-Network-Gateway-Adapter-1",
                    hostname="gateway.local",
                    ipv4_address="192.0.2.10",
                    port=5000,
                    service_type="_bsc-sc-socket._tcp.local.",
                    gateway_device_type=SimpleNamespace(value="lan-gw-esp2"),
                    endpoint=("192.0.2.10", 5000),
                ),)

            def stop(self):
                pass

        with patch("builtins.print") as output:
            result = eltakotool.lan_gateway_scan(
                wait_seconds=0, as_json=True, discovery_factory=FakeDiscovery
            )
        self.assertEqual("lan-gw-esp2", result[0]["gateway_device_type"])
        output.assert_called_once()
        opts = self.parser.parse_args(["--rawuri", "coap://x", "enumerate"])
        self.assertIsNone(eltakotool.check_conflicting_transport_opts(opts))


class BenchmarkBus:
    """Deterministic bus double: short delays lose responses, longer ones pass."""

    def __init__(self):
        self.delay_message = 0.01
        self.requests = []

    async def exchange(self, request, response_type, retries=1, timeout=1.0):
        self.requests.append((request, self.delay_message, retries, timeout))
        await asyncio.sleep(self.delay_message)
        if self.delay_message < 0.005:
            return None
        return ESP2Message(bytes(11))


class TestBenchmark(unittest.TestCase):
    """Verify delay measurement and recommendation without serial hardware."""

    def test_benchmark_returns_rates_and_restores_bus_setting(self):
        """The benchmark records failures, finds the first safe delay, and restores state."""
        bus = BenchmarkBus()

        async def scenario():
            return await eltakotool.benchmark_message_delays(
                bus,
                lambda: EltakoPollForced(5),
                delays=(0.0, 0.005, 0.01),
                messages_per_delay=2,
                timeout=0.1,
            )

        results = asyncio.run(scenario())
        self.assertEqual(0.01, bus.delay_message)
        self.assertEqual([0.0, 0.005, 0.01], [result["delay"] for result in results])
        self.assertEqual([0, 2, 2], [result["successful"] for result in results])
        self.assertTrue(results[1]["recommended"])
        self.assertFalse(results[0]["recommended"])
        self.assertTrue(all(isinstance(request, EltakoPollForced) for request, *_ in bus.requests))

    def test_print_benchmark_results_reports_recommendation(self):
        """CLI formatting prints a readable table and returns the recommendation."""
        results = [{
            "delay": 0.005,
            "successful": 3,
            "timed_out": 1,
            "success_rate": 0.75,
            "messages_per_second": 12.5,
            "recommended": True,
        }]
        with patch("builtins.print") as output:
            recommended = eltakotool.print_benchmark_results(results, minimum_success_rate=0.7)
        self.assertEqual(0.005, recommended)
        self.assertTrue(any("recommended delay" in call.args[0] for call in output.call_args_list))


class TestFakefam(unittest.TestCase):
    """Regression tests for the fakefam() serial/socket fallback logic.

    Before the fix, a successful serial connection fell through into a dead
    ``else`` branch that referenced an undefined ``s`` variable, and the
    unix/tcp socket fallback passed a ``loop=`` keyword argument that modern
    asyncio.start_unix_server()/start_server() reject outright.
    """

    def test_successful_serial_connection_returns_without_error(self):
        seen = {}

        async def fake_create_serial_connection(loop, protocol_factory, device, baudrate):
            protocol_factory()
            seen["baudrate"] = baudrate
            return (Mock(), Mock())

        async def fake_run_fakefam(bus, reader, writer, conn_made=None, conn_end=None):
            seen["ran"] = True

        async def scenario():
            with patch(
                "eltakotool.serial_asyncio.create_serial_connection",
                fake_create_serial_connection,
            ), patch("eltakotool.run_fakefam", fake_run_fakefam):
                await eltakotool.fakefam(object(), "/dev/ttyFAKE", baud_rate=9600)

        asyncio.run(scenario())
        self.assertTrue(seen.get("ran"))
        self.assertEqual(9600, seen["baudrate"])

    def test_falls_back_to_unix_socket_without_invalid_loop_kwarg(self):
        async def fake_create_serial_connection(loop, protocol_factory, device, baudrate):
            raise serial.serialutil.SerialException("no such serial port")

        async def fake_start_unix_server(client_connected_cb, path):
            client_connected_cb.keywords["conn_made"].set_result(None)
            client_connected_cb.keywords["conn_end"].set_result(None)
            return Mock()

        async def scenario():
            with patch(
                "eltakotool.serial_asyncio.create_serial_connection",
                fake_create_serial_connection,
            ), patch(
                "eltakotool.asyncio.start_unix_server", fake_start_unix_server
            ), patch("eltakotool.os.unlink"):
                await eltakotool.fakefam(object(), "/tmp/fakefam.sock")

        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
