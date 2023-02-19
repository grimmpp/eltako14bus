from collections import defaultdict, namedtuple
import asyncio
import binascii
import random
import yaml

from .util import b2a
from .message import *
from .error import UnrecognizedUpdate
from .eep import EEP, AddressExpression, A5_38_08, A5_12_01, F6_02_01, F6_02_02

class BusObject:
    def __init__(self, address, *, bus=None):
        super().__init__()

        self.address = address
        self.bus = bus
        self._programming = {}

    @property
    def address(self):
        return self._address

    @property
    def programming(self):
        return self._programming

    def set_programming(self, value):
        self._programming = value
        
    @property
    def eep(self):
        return self._eep

    def set_eep(self, value):
        self._eep = value

    def __repr__(self):
        classname = type(self).__name__
        return "<%s at %d>"%(classname, self.address)

    def interpret_status_update(self, msg):
        """Given an EltakoWrappedRPS or EltakoWrapped4BS, take out status
        information and present it in a class-specific dictionary.

        Messages that do not fit the object raise an UnrecognizedUpdate
        exception if it expects no updates or does not know what to make of
        it."""
        raise UnrecognizedUpdate("Device is not expected to send updates")

class FAM14(BusObject):
    pass

class DimmerStyle(BusObject):
    """Devices that work just the same as a FUD14. FSG14_1_10V appears to
    behave the same way in the known areas as that -- all GUIs options in the
    PCT tool even look the same."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._explicitly_configured_command_address = {}
    
    async def find_direct_command_address(self):
        """Find a GVFS source address (an AddressExpression) that can control the device"""
        return None

    async def set_state(self, dim, total_ramp_time=0):
        """Send a telegram to set the dimming state to dim (from 0 to 255). Total ramp time is the the time in seconds """
        sender = await self.find_direct_command_address()
        if sender is None:
            raise RuntimeError("Can't send without any configured universal remote")
        sender = sender.plain_address()

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

class FUD14(DimmerStyle):
    programmable_dimmer = (12, 128)

class FUD14_800W(DimmerStyle):
    programmable_dimmer = (12, 128)

class HasProgrammableRPS:
    """Mix-in for being programmable with RPS buttons, especially own configured commands

    This can be mixed in to any bus object that has a range of programmable
    slots that follow the FSR14 function group 2 style.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._explicitly_configured_command_address = {}

    async def find_direct_command_address(self):
        """Find RPS telegram details (as an AddressExpression with left or
        right as discriminator) to send to switch the device"""
        return None

    async def set_state(self, state: bool):
        command = await self.find_direct_command_address()
        if command is None:
            raise RuntimeError("Can't send without any configured universal remote")

        sender, discriminator = command
        if discriminator == 'left':
            db0 = (0x30, 0x10)[state]
        elif discriminator == 'right':
            db0 = (0x70, 0x50)[state]

        await self.bus.send(ESP2Message(b"\x0b\x05" + bytes([db0]) + b"\0\0\0" + sender + b"\30"))

class FSR14(BusObject, HasProgrammableRPS):
    programmable_rps = (12, 128)

    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrappedRPS):
            try:
                msg = EltakoWrappedRPS.parse(msg.serialize())
            except ParseError:
                raise UnrecognizedUpdate("Not an RPS update: %s" % msg)

        if msg.address[:3] != bytes((0, 0, 0)):
            raise UnrecognizedUpdate("RPS not originating from the bus")

        state = {0x50: False, 0x70: True}.get(msg.data[0])
        if state is None:
            raise UnrecognizedUpdate("Telegram is not a plain on or off message")

        return {"state": state}

class FSR14_1x(FSR14):
    pass

class FSR14_2x(FSR14):
    pass

class FSR14_4x(FSR14):
    pass

class F4SR14_LED(FSR14):
    pass

class FSB14(BusObject, HasProgrammableRPS):
    programmable_rps = (17, 128)

    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrapped4BS) and not isinstance(msg, EltakoWrappedRPS):
            try:
                msg = EltakoWrapped4BS.parse(msg.serialize())
            except ParseError:
                try:
                    msg = EltakoWrappedRPS.parse(msg.serialize())
                except ParseError:
                    raise UnrecognizedUpdate("Not recognizable update: %s" % msg)

        if isinstance(msg, EltakoWrappedRPS):
            states = {
                    0x01: "moving up",
                    0x02: "moving down",
                    0x70: "top",
                    0x50: "bottom",
                    }
            try:
                return {"state:": states[msg.data[0]]}
            except KeyError:
                raise UnrecognizedUpdate("Unknown data value in RPS: %s" % msg.data[0])
        else:
            # They are known but not implemented, as their information content
            # is only moved time, which is not usable without a persistent
            # model and known timing parameters
            pass


class F3Z14D(BusObject):
    pass

class FMZ14(BusObject):
    pass

class FWG14MS(BusObject):
    pass

class FSU14(BusObject):
    pass

class FMSR14(BusObject):
    pass

class FWZ14_65A(BusObject):
    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrapped4BS):
            try:
                msg = EltakoWrapped4BS.parse(msg.serialize())
            except ParseError:
                raise UnrecognizedUpdate("Not a 4BS update: %s" % msg)

        if msg.address != bytes((0, 0, 0, self.address)):
            raise UnrecognizedUpdate("4BS not originating from this device")

        if msg.data[3] == 0x8f:
            # Device is sending its serial number, which is better obtained
            # from memory
            return {}

        return A5_12_01.decode(msg.data)

class FSG14_1_10V(DimmerStyle):
    programmable_dimmer = (12, 128)

class FGW14_USB(BusObject):
    pass

class FDG14(DimmerStyle):
    programmable_dimmer = (14, 128)

    # Known oddities: Announces with 0e byte at payload[3] of the
    # EltakoDiscoveryReply.
    #
    # It also reports as a device at offset +8, probably for compatibility with
    # FAMs that don't know of the address expansion trick. Enumeration might
    # find this odd when trying to read its memory (but enumeration that's not
    # only there for debugging should skip ahead by size anyway, and not run
    # into this).

class Sensor(BusObject):
    def interpret_status_update(self, msg):
        if self.eep is None:
            raise UnrecognizedUpdate("The EEP was not set for this device. Please do so in the configuration.")

        return self.eep.decode(msg.data)

known_objects = [FAM14, FUD14, FUD14_800W, FSB14, FSR14_1x, FSR14_2x, FSR14_4x, F4SR14_LED, F3Z14D, FMZ14, FWG14MS, FSU14, FMSR14, FWZ14_65A, FSG14_1_10V, FGW14_USB, FDG14, Sensor]

async def create_busobject(bus, address, type):
    for o in known_objects:
        if o.__name__ == type:
            return o(address, bus=bus)
    else:
        return BusObject(address, bus=bus)
