from collections import defaultdict, namedtuple
import asyncio
import binascii
import random
import yaml

from .util import b2a
from .message import *
from .error import UnrecognizedUpdate
from .eep import EEP, AddressExpression, A5_38_08, A5_12_01, F6_02_01, F6_02_02, A5_13_01

class BusObject:
    def __init__(self, address, *, bus=None):
        super().__init__()

        self._address = address
        self.bus = bus
        self._programming = {}

    @property
    def address(self):
        return self._address

    @property
    def programming(self):
        return self._programming

    @programming.setter
    def programming(self, value):
        self._programming = value
        
    @property
    def eep(self):
        return self._eep

    @eep.setter
    def eep(self, value):
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

class RelayStyle(BusObject, HasProgrammableRPS):
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

class CoverStyle(BusObject, HasProgrammableRPS):
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

class SensorStyle(BusObject):
    def interpret_status_update(self, msg):
        if self.eep is None:
            raise UnrecognizedUpdate("The EEP was not set for this device. Please do so in the configuration.")

        return self.eep.decode(msg.data)

class WeatherSensorStyle(SensorStyle):
    _eep = A5_13_01

class ElectricityMeterSensorStyle(SensorStyle):
    _eep = A5_12_01
    
class GasMeterSensor(SensorStyle):
    _eep = A5_12_02

class WaterMeterSensor(SensorStyle):
    _eep = A5_12_02

class FAM14(BusObject):
    pass

class FSR14(RelayStyle):
    pass

class FUD14(DimmerStyle):
    programmable_dimmer = (12, 128)

class FSB14(CoverStyle):
    pass

class F3Z14D(BusObject):
    pass

class FMZ14(BusObject):
    pass

class FWG14MS(WeatherSensorStyle):
    pass

class FSU14(BusObject):
    pass

class FMSR14(BusObject):
    pass

class FWZ14(ElectricityMeterSensorStyle):
    pass

class FSG14(DimmerStyle):
    programmable_dimmer = (12, 128)

class FGW14(BusObject):
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

known_objects = [FAM14, FUD14, FSB14, FSR14, F3Z14D, FMZ14, FWG14MS, FSU14, FMSR14, FWZ14, FSG14, FGW14, FDG14, Sensor]

async def create_busobject(bus, address, type):
    for o in known_objects:
        if o.__name__.lower() == type.lower():
            return o(address, bus=bus)
    else:
        return BusObject(address, bus=bus)
