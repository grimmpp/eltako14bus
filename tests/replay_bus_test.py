"""Offline regression tests based on the recorded AQ028YCS bus session.

These tests replay real discovery, memory, status, command, and passive
receive data without opening a serial port. They protect the device and
message layers from regressions while keeping the default test suite
independent of an Eltako installation.
"""

import asyncio
import json
import unittest
from pathlib import Path

from eltakobus.device import get_bus_object_by_discovery_message
from eltakobus.message import (
    EltakoDiscoveryReply,
    EltakoDiscoveryRequest,
    EltakoMemoryRequest,
    EltakoMemoryResponse,
    EltakoPoll,
    EltakoPollForced,
    EltakoWrapped4BS,
    ESP2Message,
    prettify,
)


REPORT = Path(__file__).parent / "resources" / "hardware_test_AQ028YCS_report.json"
PASSIVE_REPORT = Path(__file__).parent / "resources" / "hardware_test_AQ028YCS_passive_report.json"
SWITCH_REPORT = Path(__file__).parent / "resources" / "hardware_test_AQ028YCS_switch_report.json"


class RecordedAQ028YCSBus:
    """Small deterministic BusInterface-like replay of the hardware dump."""

    def __init__(self, report):
        self.records = {record["address"]: record for record in report["devices"]}
        self.dim = 89
        self.sent = []

    async def exchange(self, request, responsetype=None, **kwargs):
        if isinstance(request, EltakoDiscoveryRequest):
            record = self.records.get(request.address)
            if record is None:
                return None
            return EltakoDiscoveryReply(
                reported_address=record["address"],
                reported_size=record["size"],
                memory_size=record["memory_max_row"],
                model=bytes.fromhex(record["model"]),
                is_fam=False,
            )

        if isinstance(request, EltakoMemoryRequest):
            record = self.records[request.address]
            return EltakoMemoryResponse(
                request.row,
                bytes.fromhex(record["memory"][request.row]),
            )

        if isinstance(request, EltakoPollForced) and request.address == 5:
            return EltakoWrapped4BS(
                address=bytes((0, 0, 0, 5)),
                status=0,
                data=bytes((2, self.dim, 0, 9 if self.dim else 8)),
            )

        return None

    async def send(self, message):
        self.sent.append(message)
        # The replay does not need to parse the command. The test updates the
        # recorded state explicitly before polling the simulated response.

    async def read_mem(self, address, known_memory_size=None):
        record = self.records[address]
        max_row = record["memory_max_row"] if known_memory_size is None else known_memory_size
        return tuple(
            bytes.fromhex(record["memory"][row])
            for row in range(max_row + 1)
        )


class TestRecordedAQ028YCSBus(unittest.TestCase):
    """Verify that recorded FAM14 data still behaves like a live bus."""

    @classmethod
    def setUpClass(cls):
        with REPORT.open() as stream:
            cls.report = json.load(stream)

    def test_recorded_discovery_contains_all_eight_devices(self):
        """Discovery replay creates the eight device classes seen on the bus."""
        async def scenario():
            bus = RecordedAQ028YCSBus(self.report)
            devices = []
            for address in sorted(bus.records):
                response = await bus.exchange(EltakoDiscoveryRequest(address))
                devices.append(get_bus_object_by_discovery_message(response, bus=bus))
            return devices

        devices = asyncio.run(scenario())
        self.assertEqual(8, len(devices))
        self.assertEqual(
            ["FSR14_4x", "FUD14", "FSB14", "FAE14SSR", "FMZ14",
             "FAE14SSR", "FGW14_USB", "FUD14_800W"],
            [type(device).__name__ for device in devices],
        )

    def test_complete_recorded_memory_is_readable(self):
        """Every recorded memory row can be read and has no failed rows."""
        async def scenario():
            bus = RecordedAQ028YCSBus(self.report)
            result = []
            for address, record in sorted(bus.records.items()):
                response = await bus.exchange(EltakoDiscoveryRequest(address))
                device = get_bus_object_by_discovery_message(response, bus=bus)
                memory = await device.read_mem()
                result.append((address, len(memory), memory[0].hex()))
            return result

        result = asyncio.run(scenario())
        self.assertEqual(
            [(1, 128, "01047f0804017200"),
             (5, 128, "05017f0c04044200"),
             (6, 136, "0602870804065700"),
             (8, 128, "08027f0804165100"),
             (10, 128, "0a017f08040e2200"),
             (11, 128, "0b027f0804165100"),
             (13, 128, "0d017f0804fe1a00"),
             (14, 128, "0e017f0804053800")],
            result,
        )

        self.assertEqual(1032, sum(length for _, length, _ in result))
        self.assertTrue(all(not record["failed_rows"] for record in self.report["devices"]))

    def test_every_recorded_discovery_and_memory_frame_round_trips(self):
        """Every recorded discovery value and memory row remains ESP2-valid."""
        for record in self.report["devices"]:
            discovery = EltakoDiscoveryReply(
                reported_address=record["address"],
                reported_size=record["size"],
                memory_size=record["memory_max_row"],
                model=bytes.fromhex(record["model"]),
                is_fam=False,
            )
            parsed_discovery = EltakoDiscoveryReply.parse(discovery.serialize())
            self.assertEqual(record["address"], parsed_discovery.reported_address)
            self.assertEqual(record["model"], parsed_discovery.model.hex())

            self.assertEqual(record["memory_rows_read"], len(record["memory"]))
            for row, memory in enumerate(record["memory"]):
                response = EltakoMemoryResponse(row, bytes.fromhex(memory))
                parsed_response = EltakoMemoryResponse.parse(response.serialize())
                self.assertEqual(row, parsed_response.row)
                self.assertEqual(memory, parsed_response.value.hex())

    def test_recorded_fud_status_and_switch_command(self):
        """FUD14 status interpretation and generated dim command stay stable."""
        async def scenario():
            bus = RecordedAQ028YCSBus(self.report)
            response = await bus.exchange(EltakoDiscoveryRequest(5))
            device = get_bus_object_by_discovery_message(response, bus=bus)
            await device.read_mem()

            status = await bus.exchange(EltakoPollForced(5), EltakoWrapped4BS)
            initial = device.interpret_status_update(status)
            direct_command = await device.find_direct_command_address(1)

            await device.set_state(1, 0, total_ramp_time=1)
            command = bus.sent[-1]
            bus.dim = 0
            after = device.interpret_status_update(
                await bus.exchange(EltakoPollForced(5), EltakoWrapped4BS)
            )
            return initial, direct_command, command, after

        initial, direct_command, command, after = asyncio.run(scenario())
        self.assertEqual({"channel": 0, "dim": 89, "ramping_speed": 0}, initial)
        self.assertEqual("00-00-B0-05", str(direct_command))
        self.assertEqual(bytes.fromhex("0b07020001090000b00500"), command.serialize()[2:-1])
        self.assertEqual({"channel": 0, "dim": 0, "ramping_speed": 0}, after)

    def test_passive_hardware_samples_are_replayable(self):
        """All captured raw ESP2 samples remain parseable and lossless."""
        with PASSIVE_REPORT.open() as stream:
            report = json.load(stream)

        self.assertEqual(57600, report["baud_rate"])
        self.assertFalse(report["writes_performed"])
        self.assertEqual(275, report["devices"][report["ports"][0]]["message_counts"]["total"])

        samples = report["devices"][report["ports"][0]]["sample_frames"]
        parsed = [prettify(ESP2Message.parse(bytes.fromhex(sample["hex"]))) for sample in samples]

        self.assertEqual(len(samples), len(parsed))
        self.assertTrue(all(isinstance(message, EltakoPoll) for message in parsed))
        self.assertEqual(
            [sample["type"] for sample in samples],
            [type(message).__name__ for message in parsed],
        )
        self.assertEqual(
            [sample["hex"] for sample in samples],
            [message.serialize().hex() for message in parsed],
        )
        self.assertEqual(
            [5, 6, 7, 8, 9, 10, 11, 12, 14, 1, 2, 3, 4],
            [message.address for message in parsed[:13]],
        )

    def test_recorded_switch_report_matches_replayed_fud_state(self):
        """The recorded switch experiment agrees with the offline FUD replay."""
        with SWITCH_REPORT.open() as stream:
            switch = json.load(stream)

        self.assertEqual(5, switch["address"])
        self.assertEqual("FUD14", switch["device"])
        self.assertEqual(switch["initial_dim"], switch["initial_status"]["dim"])
        self.assertEqual(switch["requested_dim"], switch["observed_dim"])
        self.assertEqual(switch["restored_dim"], switch["restore_status"]["dim"])
        self.assertTrue(switch["restored"])
