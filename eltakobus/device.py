from collections import defaultdict, namedtuple
import asyncio
import binascii
import random
import yaml

from .util import b2a
from .message import *
from .error import UnrecognizedUpdate

class BusObject:
    def __init__(self, response, *, bus=None):
        self.discovery_response = response
        if self.discovery_response.reported_size != self.size:
            # won't happen with the default size implementation, but another class may give a constant here
            raise ValueError("Unexpected size (got %d, expected %d for %r)"%(self.discovery_response.reported_size, self.size, self))
        self.bus = bus
        self.memory = [None] * response.memory_size

    @property
    def version(self):
        high, low = self.discovery_response.model[2:4]
        return (high >> 4, high & 0xf, low >> 4, low & 0xf0)

    address = property(lambda self: self.discovery_response.reported_address)
    size = property(lambda self: self.discovery_response.reported_size)

    def __repr__(self):
        classname = type(self).__name__
        if not hasattr(self, 'discovery_name'):
            classname += " (%02x %02x)"%(self.discovery_response.model[0], self.discovery_response.model[1])
        return "<%s at %d size %d version %s>"%(classname, self.address, self.size, self.version)

    async def read_mem(self):
        """Simple bound wrapper for bus.read_mem"""
        if any(l is None for l in self.memory):
            self.memory = await self.bus.read_mem(self.address, self.discovery_response.memory_size)
        return self.memory

    async def read_mem_line(self, line):
        if self.memory[line] is None:
            response = await self.bus.exchange(EltakoMemoryRequest(self.address, line), EltakoMemoryResponse)
            self.memory[line] = response.value
        return self.memory[line]

    async def write_mem_line(self, row, value):
        select_response = await self.bus.exchange(EltakoMessage(0xf2, self.address))
        if select_response.org != 0xf2:
            raise WriteError("Device selection failed; expected 0xf2, got %r"%select_response)

        write_response = await self.bus.exchange(EltakoMessage(0xf4, row, value))
        if write_response.org != 0xf4:
            raise WriteError("Write failed; expected 0xf4, got %r"%write_response)

    async def show_off(self):
        print("Identifying on the bus")
        await self.bus.exchange(EltakoMessage(0xfd, self.address))
        await asyncio.sleep(3)

    @classmethod
    def annotate_memory(cls, mem):
        return {}

    def interpret_status_update(self, msg):
        """Given an EltakoWrappedRPS or EltakoWrapped4BS, take out status
        information and present it in a class-specific dictionary.

        Messages that do not fit the object raise an UnrecognizedUpdate
        exception if it expects no updates or does not know what to make of
        it."""
        raise UnrecognizedUpdate("Device is not expected to send updates")

class FAM14(BusObject):
    size = 1
    discovery_name = bytes((0x07, 0xff))

    @classmethod
    def annotate_memory(cls, mem):
        return {
                1: MemoryFileNibbleExplanationComment(
                    "AD DR ES S, -- -- -- --",
                    "Base address")
                }

class FUD14(BusObject):
    size = 1
    discovery_name = bytes((0x04, 0x04))

    async def find_direct_command_address(self):
        for memory_id in range(12, 128):
            line = await self.read_mem_line(memory_id)
            sender = line[:4]
            function = line[5]
            if function == 32:
                return sender
        return None

    async def set_state(self, dim, total_ramp_time=0):
        """Send a telegram to set the dimming state to dim (from 0 to 255). Total ramp time is the the time in seconds """
        sender = await self.find_direct_command_address()
        if sender is None:
            raise RuntimeError("Can't send without any configured universal remote")

        dim = max(min(int(dim), 255), 0)
        total_ramp_time = max(min(int(total_ramp_time), 255), 1)
        # total_ramp_time = 0 should mean "no ramping", but in practice still
        # ramps and sometimes slowly

        await self.bus.send(ESP2Message(b"\x0b\x07\x02" + bytes([dim, total_ramp_time]) + b"\x09" + sender + b"\0"))

    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrapped4BS):
            try:
                msg = EltakoWrapped4BS.parse(msg.serialize())
            except ParseError:
                raise UnrecognizedUpdate("Not a 4BS update: %s" % msg)

        if msg.address != bytes((0, 0, 0, self.address)):
            raise UnrecognizedUpdate("4BS not originating from this device")

        # parsing this as A5-38-08 telegram
        if msg.data[0] != 0x02:
            raise UnrecognizedUpdate("Telegram should be of subtype for dimming")

        # Bits should be data (0x08), absolute (not 0x04), don't store (not 0x02), and on or off fitting the dim value (0x01)
        expected_3 = 0x09 if msg.data[1] != 0 else 0x08
        if msg.data[3] != expected_3:
            raise UnrecognizedUpdate("Odd set bits for dim value %s: 0x%02x" % (msg.data[1], msg.data[3]))

        return {
                "dim": msg.data[1], # The dim value is reported in 0..100 range, even though the db2 byte says absolute.
                "ramping_speed": msg.data[2],
                }

    async def show_off(self):
        await super().show_off()

        print("Querying dimmer state")
        response = await(self.bus.exchange(EltakoPollForced(self.address), EltakoWrapped4BS))

        parsed = self.interpret_status_update(response)

        print("Dimmer value is %d"%parsed['dim'])
        print("Ramping speed is %ds to 100%%"%parsed['ramping_speed'])

        print("Reading out input programming")
        sender = await self.find_direct_command_address()
        if sender is not None:
            dimming = min(random.randint(0, 10) ** 2 + random.randint(0, 3), 100)
            print("I'e found a programmed universal dimmer state input, sending value %d"%dimming)
            await self.set_state(dimming)

    @classmethod
    def annotate_memory(cls, mem):
        return {
                8: MemoryFileStartOfSectionComment("function group 1"),
                9: MemoryFileStartOfSectionComment("function group 2"),
                12: [
                    MemoryFileStartOfSectionComment("function group 4"),
                    MemoryFileNibbleExplanationComment(
                         "AD DR ES S, KY FN SP %%",
                         "key (5 = left, 6 = right), function (eg. 32 = A5-38-08), speed, percent"),
                    ],
                }


class FSR14(BusObject):
    async def find_direct_command_address(self, channel):
        """Find RPS telegram details (sender, (db0 to turn off, db0 to turn
        on)) to send to switch the given channel"""
        target_bitset = 1 << channel
        for memory_id in range(12, 128):
            line = await self.read_mem_line(memory_id)
            sender = line[:4]
            function = line[5]
            key = line[4]
            channels = line[6]

            if channels != target_bitset:
                continue

            db0_for_switching = { # (function, key) to (off, on)
                    (3, 6): (0x70, 0x50), # directional buttons enable on down, right keys
                    (3, 5): (0x30, 0x10), # directional buttons enable on down, left keys
                    (2, 6): (0x50, 0x70), # directional buttons enable on up, right keys
                    (2, 5): (0x10, 0x30), # directional buttons enable on up, left keys
                    }
            db0 = db0_for_switching.get((function, key))
            if db0 is not None:
                return sender, db0
        return None, None

    async def set_state(self, channel, state: bool):
        command = await self.find_direct_command_address(channel)
        if command is None:
            raise RuntimeError("Can't send without any configured universal remote")

        sender, db0s = command
        db0 = db0s[state]

        await self.bus.send(ESP2Message(b"\x0b\x05" + bytes([db0]) + b"\0\0\0" + sender + b"\30"))

    async def show_off(self):
        await super().show_off()

        want_switch_channel = random.randint(0, self.size - 1)

        for subchannel in range(self.size):
            print("Querying state of channel %d"%subchannel)
            response = await(self.bus.exchange(EltakoPollForced(self.address + subchannel), EltakoWrappedRPS))
            parsed = self.interpret_status_update(response)
            print("Channel is at %d"%parsed[subchannel])

            if subchannel == want_switch_channel:
                want_switch_currentstate = state

        print("Trying to switch subchannel %d, reading out input programming"%want_switch_channel)

        command = await self.find_direct_command_address(want_switch_channel)
        if command is not None:
            print("Found suitable programming for direct switching of subchannel from %d to %d"%(want_switch_currentstate, not want_switch_currentstate))
            await self.set_state(want_switch_channel, not want_switch_currentstate)
        else:
            print("No suitable programming found for switching the subchannel")

    @classmethod
    def annotate_memory(cls, mem):
        return {
                2: MemoryFileNibbleExplanationComment("R0 R1 R2 R3", "(bool)Rn = 'restore channel n on power-up"),
                8: MemoryFileStartOfSectionComment("function group 1"),
                12: [
                    MemoryFileStartOfSectionComment("function group 2"),
                    MemoryFileNibbleExplanationComment(
                         "AD DR ES S, KY FN CH 00",
                         "key (5 = left, 6 = right), function (3 = bottom enable, 2 = upper enable), ch = affected channels as bits"),
                    ],
                }

    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrappedRPS):
            try:
                msg = EltakoWrappedRPS.parse(msg.serialize())
            except ParseError:
                raise UnrecognizedUpdate("Not an RPS update: %s" % msg)

        subchannel = msg.address[3] - self.address
        if subchannel not in range(self.size):
            raise UnrecognizedUpdate("RPS not originating from this device")
        if msg.address[:3] != bytes((0, 0, 0)):
            raise UnrecognizedUpdate("RPS not originating from the bus")

        state = {0x50: False, 0x70: True}.get(msg.data[0])
        if state is None:
            raise UnrecognizedUpdate("Telegram is not a plain on or off message")

        return {subchannel: state}

class FSR14_1x(FSR14):
    discovery_name = bytes((0x04, 0x01))
    size = 1

class FSR14_2x(FSR14):
    discovery_name = bytes((0x04, 0x02))
    size = 2

class FSR14_4x(FSR14):
    discovery_name = bytes((0x04, 0x01))
    size = 4

class F4SR14_LED(BusObject):
    discovery_name = bytes((0x04, 0x09))
    size = 4

class F3Z14D(BusObject):
    discovery_name = bytes((0x04, 0x67))
    size = 3

class FMZ14(BusObject):
    discovery_name = bytes((0x04, 0x0e))
    size = 1

class FWG14MS(BusObject):
    discovery_name = bytes((0x04, 0x1a))
    size = 1

class FSU14(BusObject):
    discovery_name = bytes((0x07, 0x14))
    size = 8
    async def show_off(self):
        await super().show_off()

        hour = random.randint(0, 23)
        minutes = random.randint(0, 59)
        print("Setting clock to %02d:%02d"%(hour, minutes))
        await self.write_mem_line(0x5d, b"\x16\x01\x01\x08" + bytes((((hour // 10) << 4) + (hour % 10), ((minutes // 10) << 4) + (minutes % 10))) + b"\x00\x01")

        await asyncio.sleep(3)

class FMSR14(BusObject):
    discovery_name = bytes((0x05, 0x15))
    size = 5

class FWZ14_65A(BusObject):
    discovery_name = bytes((0x04, 0x66))
    size = 1

    @classmethod
    def annotate_memory(cls, mem):
        return {
                1: MemoryFileNibbleExplanationComment(".. .. .. .. ..  SUM kWh", "accumulated counter value as sent in DT=0 DIV=0 telegram"),
                5: MemoryFileNibbleExplanationComment("S0 S1 S2 S3 .. .. .. ..", "Serial number as sent in DT=1 DIV=3 TI=8 messages (once as with DB3..1 = S1 S0 00, once as S3 S2 01)")
                }

known_objects = [FAM14, FUD14, FSR14_1x, FSR14_2x, FSR14_4x, F4SR14_LED, F3Z14D, FMZ14, FWG14MS, FSU14, FMSR14, FWZ14_65A]
# sorted so the first match of (discovery name is a prefix, size matches) can be used
sorted_known_objects = sorted(known_objects, key=lambda o: len(o.discovery_name) + 0.5 * (o.size is not None), reverse=True)

async def create_busobject(bus, id):
    response = await bus.exchange(EltakoMessage(org=0xf0, address=id), EltakoDiscoveryReply)

    assert id == response.reported_address

    for o in sorted_known_objects:
        if response.model.startswith(o.discovery_name) and (o.size is None or o.size == response.reported_size):
            return o(response, bus=bus)
    else:
        return BusObject(response, bus=bus)


class MemoryFile(defaultdict):
    """In-memory representation of a YAML file suitable for storing, editing,
    verifying and flashing device memory contents

    The YAML file is a dict of dicts, mapping bus ids and memory lines (or
    memory ranges for compression) to binascii hexdumps. The MemoryFile behaves
    the same, but with binary strings as values."""

    def __init__(self):
        defaultdict.__init__(self, lambda: {})
        self.comments = {}
        self.linecomments = {}

    async def add_device(self, dev: BusObject):
        mem = await dev.read_mem()
        self[dev.address] = dict(enumerate(mem))

        self.comments[dev.address] = repr(dev)
        self.linecomments[dev.address] = dev.annotate_memory(mem)

    @classmethod
    def load(cls, f):
        result = cls()
        fromfile = yaml.load(f)
        result = cls()
        for k1, v1 in fromfile.items():
            for k2, v2 in v1.items():
                if isinstance(k2, int):
                    k2 = [k2]
                else:
                    start, end = k2.split('-', 1)
                    start, end = int(start), int(end)
                    k2 = range(start, end + 1)
                for k2entry in k2:
                    result[k1][k2entry] = binascii.unhexlify(v2.replace(' ', ''))
        return result

    def store(self, f):
        for_file = {}
        linecomments_for_file = {}
        for k1, v1 in self.items():
            for_file[k1] = dict()
            linecomments_for_file[k1] = dict()
            last_start = None
            last = None
            for k2, v2 in v1.items():
                if last != v2 or k2 in self.linecomments[k1]:
                    if last is not None:
                        # flush
                        if last_start == k2 - 1:
                            last_key = last_start
                        else:
                            last_key = "%d-%d"%(last_start, k2 - 1)
                        for_file[k1][last_key] = last
                        linecomments_for_file[k1][last_key] = self.linecomments[k1].get(last_start, [])
                    last_start = k2
                last = v2
            # flush end
            if last_start == k2:
                last_key = last_start
            else:
                last_key = "%d-%d"%(last_start, k2)
            for_file[k1][last_key] = last
            linecomments_for_file[k1][last_key] = self.linecomments[k1].get(last_start, [])

        # to get "uncompressed" dumps:
        # for_file = self

        for k1, v1 in for_file.items():
            if k1 in self.comments:
                print("%d: # %s"%(k1, self.comments[k1]), file=f)
            else:
                print("%d:"%k1, file=f)

            for k2, v2 in v1.items():
                lc = linecomments_for_file[k1][k2]
                if not isinstance(lc, list):
                    lc = [lc]
                for c in lc:
                    if isinstance(c, MemoryFileStartOfSectionComment):
                        print("    # ------ %s"%c, file=f)
                for c in lc:
                    if isinstance(c, MemoryFileNibbleExplanationComment):
                        print("    #        % -23s -- %s"%c, file=f)
                suffixcomments = " " + ", ".join(str(c) for c in lc if isinstance(c, MemoryFileStateComment))
                print("    % -8s %s%s"%("%s:"%k2, b2a(v2), suffixcomments.rstrip()), file=f)
            print(file=f)

class MemoryFileComment: pass
class MemoryFileStartOfSectionComment(str, MemoryFileComment): pass
class MemoryFileNibbleExplanationComment(namedtuple("_nibbleexp", "nibbles explanation"), MemoryFileComment): pass
class MemoryFileStateComment(str, MemoryFileComment): pass