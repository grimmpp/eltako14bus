from collections import defaultdict, namedtuple
from enum import IntEnum
import asyncio
import binascii
import random
import yaml

from .util import b2a, b2s, AddressExpression
from .message import *
from .error import *
from .eep import EEP, A5_38_08, A5_12_01, F6_02_01, F6_02_02, H5_3F_7F, A5_10_06



class KeyFunction(IntEnum):
    """Numbers of KeyFunctions from PCT14."""
    NO_FUNCTION = 0
    UNIVERSAL_PUSH_BUTTON = 1
    DIRECTION_PUSH_BUTTON_TOP_ON = 2
    DIRECTION_PUSH_BUTTON_BOTTOM_ON = 3
    CENTRAL_OFF = 4
    CENTRAL_ON = 5
    SCENE_PUSHBUTTON = 6
    SEQUENTIAL_SCENE_PUSH_BUTTON = 7
    LIGHT_ALARM = 8

    DIMMING_VALUE_IN_PERCENTAGE = 10
    STAIRCASE_PUSH_BUTTON = 11
    CENTRAL_UP_DOWN = 12
    
    CENTRAL_UP_DOWN_WITH_DYNAMIC_PRIORITY = 14
    WINDOW_CONTACT = 16
    NO_WINDOW_CONTACT = 17
    NC_WINDOW_CONTACT = 18
    CENTRAL_UP_DOWN_WITH_STATIC_PRIORITY = 19

    CENTRAL_OFF_WITH_STATIC_PRIORITY = 21
    CENTRAL_ON_WITH_STATIC_PRIORITY = 22
    UNIVERSAL_PUSH_BUTTON_ES = 23
    UNIVERSAL_PUSH_BUTTON_ER = 24
    WINDOW_HANDLE_FTKE = 25
    NO_WINDOW_HANDLE = 26
    NC_WINDOW_HANDLE = 27

    FOUR_FOLD_TEST_PUSH_BUTTON = 29
    FOUR_FOLD_PUSH_BUTTON = 30
    OPERATIONS_COMMAND_WITH_TIME_VALUE_TRASMISSION_FROM_CONTROLLER = 31
    DIMMING_VALUE_FROM_CONTROLLER = 32       # for PC/home automation - FUD
    FBH_WITH_BRIGHTNESS_EVALUATION = 33
    FBH_WITHOUT_BRIGHTNESS_EVALUATION = 34
    MOTION_DETECTOR_ACCORDING_TO_EEP_A5_07_01 = 35
    FAH60_WITH_DAYLIGHT_EVALUATION = 36
    FAH60_TWILIGHT_PSUH_BUTTON = 37
    FAH60_TWILIGHT_DIMMER = 38
    FAH60_FOR_CONTROL_OF_ROLLER_SHUTTER = 39

    FWG14MS_WEATHER_STATION = 42
    FIH65B_FOR_CONSTANT_LIGHT_CONTROL = 44

    TARGET_BRIGHTNESS_MEMORY_BUTTON = 47
    WATER_SENSOR_ACCORDING_TO_EEP_A5_30_30 = 48
    WATER_SENSOR_RPS_TELEGRAM = 49
    SMOKE_DETECTOR = 50
    SWITCHING_STATE_FROM_CONTROLLER = 51     # for PC/home automation - FSR

    ACTIVATION_SNOOZE_FUNCTION = 53
    FBH_WITH_BRIGHTNESS_EVALUATION_ONLY_AT_SWITCH_ON_FOR_WARM_LIGHT = 54

    LINKED_ACTUATOR_FEDDBACK = 60
    TEMPERATURE_CONTROLLER_WITH_SETPOINT = 61
    TEMPERATURE_CONTROLLER_WITHOUT_SLIDE_SWITCH = 62
    TEMPERATURE_CONTROLLER_WITH_SLIDE_SWITCH_SUN_MOON = 63
    TEMPERATURE_CONTROLLER_ACCORDING_EEP_A5_10_06_FTR55D = 64    #used for FUTH
    TEMPERATURE_CONTROLLER_SETPOINT = 65     # for PC/home automations - FHK, FAE, ...
    TEMPERATURE_CONTROLLER_ACCORDING_EEP_A5_02_05 = 66
    HUMIDITY_TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_04_02 = 67
    TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_02 = 68
    HUMIDITY_TEMPERATURE_SENSOR_FUTH_ACCORDING_TO_EEP_A5_10_12 = 69
    TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_03 = 70
    TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_03_LIMITED_TEMP_RANGE = 71

    CENTRAL_ON_WITH_LATCHING_OF_PRIORITY = 77
    CENTRAL_OFF_WITH_LATCHING_OF_PRIORITY = 78

    DIRECTION_PUSH_BUTTON_FOR_LOCKING_TURNAROUND_AUTOMATIC = 80
    
    CENTRAL_UP = 82
    CENTRAL_DOWN = 83
    CENTRAL_STOP = 84

    DIRECTION_PUSH_BUTTON_FOR_LOCKING_SHADING_SCENE_1 = 98
    DIRECTION_PUSH_BUTTON_FOR_LOCKING_SHADING_SCENE_2 = 99
    DIRECTION_PUSH_BUTTON_FOR_LOCKING_SHADING_SCENE_3 = 100
    DIRECTION_PUSH_BUTTON_FOR_LOCKING_SHADING_SCENE_4 = 101
    DIRECTION_PUSH_BUTTON_FOR_LOCKING = 102
    FAH60_WITH_DAYLIGHT_EVALUATION_SWITCH_OFF_ONLY = 103
    FAH60_WITH_DAYLIGHT_EVALUATION_SWITCH_ON_ONLY = 104
    SCENE_PUSH_BUTTON = 105

    TIME = 110

    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_09 = 120
    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_0A = 121

    RESOLVE_PRIORITY = 123
    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_09_AS_NCC = 124
    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_09_AS_NOC = 125
    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_0A_AS_NCC = 126
    WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_0A_AS_NOC = 127
    DRIVING_COMMAND_WITH_RUN_TIME_AND_REVERSE_TIME = 128

    HEAT_PUMP = 137     # switch for cooling mode

    HUMIDITY_TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_04_03 = 139

    HUMIDITY_TEMPERATURE_SENSOR_FUTH_TEMP_SETPOINT_ACCORDING_TO_EEP_A5_10_12_BUTH = 149

    VIBRATION_SENSOR_ACCORDING_TO_EEP_A5_14_05 = 156
    BRIGHTNESS_SENSOR_ACCORDING_TO_EEP_A5_06_02_TWILIGHT_SWITCH = 157
    BRIGHTNESS_SENSOR_ACCORDING_TO_EEP_A5_06_03_TWILIGHT_SWITCH = 158
    CENTRAL_OFF_WITH_IMMEDIATE_PRIORITY = 159
    CENTRAL_ON_WITH_IMMEDIATE_PRIORITY = 160
    VIBRATION_SENSOR_ACCORDING_TO_EEP_A5_14_05_WITH_DELAY = 161
    WINDOW_SENSOR_ACCORDING_TO_EEP_A5_14_01 = 162
    WINDOW_SENSOR_ACCORDING_TO_EEP_A5_14_03 = 163



    
    @classmethod
    def get_contect_sensor_list(cls) -> []:
        return [cls.WINDOW_CONTACT, 
                cls.NO_WINDOW_CONTACT,  
                cls.NC_WINDOW_CONTACT,
                cls.WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_09, 
                cls.WINDOW_HANDLE_ACCORDING_TO_EEP_A5_14_0A, 
                cls.WINDOW_HANDLE_FTKE]

    @classmethod
    def get_switch_sensor_list(cls) -> []:
        return [cls.UNIVERSAL_PUSH_BUTTON,
                cls.DIRECTION_PUSH_BUTTON_TOP_ON,
                cls.DIRECTION_PUSH_BUTTON_BOTTOM_ON,
                cls.CENTRAL_ON,
                cls.CENTRAL_OFF,
                cls.SCENE_PUSHBUTTON,
                cls.CENTRAL_UP_DOWN,
                cls.CENTRAL_UP_DOWN_WITH_DYNAMIC_PRIORITY,
                cls.CENTRAL_UP_DOWN_WITH_STATIC_PRIORITY,
                cls.CENTRAL_OFF_WITH_STATIC_PRIORITY,
                cls.CENTRAL_ON_WITH_STATIC_PRIORITY,
                cls.FOUR_FOLD_PUSH_BUTTON,
                cls.FOUR_FOLD_TEST_PUSH_BUTTON,
                cls.HEAT_PUMP ]

    @classmethod
    def get_pc_functions(cls) -> []:
        return [cls.DIMMING_VALUE_FROM_CONTROLLER, 
                cls.SWITCHING_STATE_FROM_CONTROLLER, 
                cls.TEMPERATURE_CONTROLLER_ACCORDING_EEP_A5_10_06_FTR55D, 
                cls.TEMPERATURE_CONTROLLER_SETPOINT]
    
    @classmethod
    def get_fhk_function_group_1(cls) -> []:
        return [cls.NO_FUNCTION,
                cls.TEMPERATURE_CONTROLLER_WITH_SETPOINT,
                cls.TEMPERATURE_CONTROLLER_WITHOUT_SLIDE_SWITCH,
                cls.TEMPERATURE_CONTROLLER_WITH_SLIDE_SWITCH_SUN_MOON,
                cls.TEMPERATURE_CONTROLLER_ACCORDING_EEP_A5_10_06_FTR55D, #used for FUTH
                cls.TEMPERATURE_CONTROLLER_ACCORDING_EEP_A5_02_05,
                cls.HUMIDITY_TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_04_02,
                cls.TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_02,
                cls.TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_03,
                cls.TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_10_03,
                cls.HUMIDITY_TEMPERATURE_SENSOR_ACCORDING_TO_EEP_A5_04_03]

    @classmethod
    def get_fhk_function_group_2(cls) -> []:
        return [cls.NO_FUNCTION,
                cls.HUMIDITY_TEMPERATURE_SENSOR_FUTH_ACCORDING_TO_EEP_A5_10_12,
                cls.HUMIDITY_TEMPERATURE_SENSOR_FUTH_TEMP_SETPOINT_ACCORDING_TO_EEP_A5_10_12_BUTH]

class SensorInfo():

    def __init__(self, sensor_id:bytes, dev_type:str, dev_id:int, dev_adr:bytes, key:int, key_func:int, channel:int, in_func_group:int, memory_line:int):
        self.sensor_id = sensor_id
        self.sensor_id_str = b2s(sensor_id)
        self.dev_type = dev_type
        self.dev_id = dev_id
        self.dev_adr = dev_adr
        self.dev_adr_str = b2s(dev_adr)
        self.key = key
        self.key_func = key_func
        self.channel = channel
        self.in_func_group = in_func_group
        self.memory_line = memory_line
    

class BusObject:
    sensor_address_range = None
    discovery_names = []

    def __init__(self, response: EltakoDiscoveryReply, *, bus=None):
        super().__init__()

        self.discovery_response = response
        if self.discovery_response.reported_size != self.size:
            # won't happen with the default size implementation, but another class may give a constant here
            raise ValueError("Unexpected size (got %d, expected %d for %r)"%(self.discovery_response.reported_size, self.size, self))
        self.bus = bus
        self.memory_size = response.memory_size
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
            self.memory = list(await self.bus.read_mem(self.address, self.discovery_response.memory_size))
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

        # Update cache
        self.memory[row] = value

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

    async def get_registered_sensors(self, sensor_range:range, in_func_group:int) -> list[SensorInfo]:
        result = []
        for i in sensor_range:
            mem_line:bytes = await self.read_mem_line(i)
            s_adr:bytes = mem_line[0:4]
            key = int(mem_line[4])
            func = int(mem_line[5])
            ch = int(mem_line[6])

            address_off_set = 0

            if int.from_bytes(s_adr, "big") > 0:
                if ch == 0:
                    result.append(
                        SensorInfo(
                            dev_type = self.__class__.__name__,
                            sensor_id = s_adr,
                            dev_adr = self.address.to_bytes(4, byteorder = 'big'),
                            key = key,
                            dev_id = int(self.address),
                            key_func = func,
                            channel = ch,
                            in_func_group=in_func_group,
                            memory_line=i
                            ))
                else:
                    while ch > 0:
                        if ch & 0x1 == 1:
                            dev_adr:int = self.address + address_off_set

                            result.append(
                                SensorInfo(
                                    dev_type = self.__class__.__name__,
                                    sensor_id = s_adr,
                                    dev_adr = dev_adr.to_bytes(4, byteorder = 'big'),
                                    key = key,
                                    dev_id = int(self.address),
                                    key_func = func,
                                    channel = address_off_set+1,
                                    in_func_group=in_func_group,
                                    memory_line=i
                                    ))
                        ch = ch >> 1
                        address_off_set += 1

        return result
    
    async def get_registered_dali_devices(self, sensor_range:range, in_func_group:int) -> list[SensorInfo]:
        result = []
        for i in sensor_range:
            mem_line:bytes = await self.read_mem_line(i)
            s_adr:bytes = mem_line[0:4]
            key = int(mem_line[4])
            func = int(mem_line[5])
            ch = int(mem_line[6])   # dali group address
            if ch < 15: 
                # translate into channels (channels: 1-16, dali groups: 0-15 + 16 = broadcast
                ch_start = ch + 1
                ch_end = ch + 2
            else:
                ch_start = 1
                ch_end = 17

            if int.from_bytes(s_adr, "big") > 0:

                for ch_i in range(ch_start, ch_end):
                    dev_adr:int = self.address + ch_i -1

                    result.append(
                        SensorInfo(
                            dev_type = self.__class__.__name__,
                            sensor_id = s_adr,
                            dev_adr = dev_adr.to_bytes(4, byteorder = 'big'),
                            key = key,
                            dev_id = int(self.address),
                            key_func = func,
                            channel = ch_i,
                            in_func_group=in_func_group,
                            memory_line=i
                            ))

        return result
    
    async def get_all_sensors(self) -> list[SensorInfo]:
        return []
        # return await self.get_registered_sensors(self.sensor_address_range)


class FAM14(BusObject):
    size = 1
    discovery_names = [ bytes((0x07, 0xff)), bytes((0x08, 0xff)) ]
    sensor_address_range = range(0,0)

    @classmethod
    def annotate_memory(cls, mem):
        return {
            1: MemoryFileNibbleExplanationComment(
                    "AD DR ES S, -- -- -- --",
                    "Base address")
        }
                
    async def get_base_id(self) -> str:
        """Gets base id from FAM14 memory."""
        mem_line = await self.read_mem_line(1)
        return b2s(mem_line[0:4])
    
    async def get_base_id_in_bytes(self) -> bytes:
        """Gets base id from FAM14 memory."""
        mem_line = await self.read_mem_line(1)
        return mem_line[0:4]

    async def get_base_id_in_int(self) -> int:
        """Gets base id from FAM14 memory."""
        mem_line = await self.read_mem_line(1)
        return int.from_bytes(mem_line[0:4], "big") 


class DimmerStyle(BusObject):
    """Devices that work just the same as a FUD14. FSG14_1_10V appears to
    behave the same way in the known areas as that -- all GUIs options in the
    PCT tool even look the same."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._explicitly_configured_command_address = {}

    async def find_direct_command_address(self, channel):
        """Find a GVFS source address (an AddressExpression) that can configure
        the given subchannel"""
        if channel in self._explicitly_configured_command_address:
            # Taking this as a shortcut allows things to work smoothly even if
            # a group-addressed A5_38_08 is present early in the configuration
            return self._explicitly_configured_command_address[channel]
        for memory_id in range(*self.programmable_dimmer):
            line = await self.read_mem_line(memory_id)
            sender = line[:4]
            function = line[5]
            line_channel = line[6]
            if function == 32 and line_channel == channel:
                return AddressExpression((sender, None))
        return None

    async def ensure_direct_command_addresses(self):
        # Choosing (0, 0, 0, address) because that's where they send from --
        # but in EltakoWrapped messages. So this address should, for other
        # purposes, be free.
        for subchannel in range(self.size):
            source_address = AddressExpression((bytes((0, 0, 0, self.address + subchannel)), None))
            await self.ensure_programmed(subchannel, source_address, A5_38_08)
            self._explicitly_configured_command_address[subchannel] = source_address

    async def ensure_programmed(self, subchannel, source: AddressExpression, profile: EEP) -> bool:
        if not self.has_subchannels:
            # In a FUD14 and similar, the subchannel field is a ramp speed (and
            # 0 seems not to mean "instant")
            subchannel = 1

        if profile is A5_38_08:
            a = source.plain_address()
            # programmed as function 32 (GFVS house automation), subchannel may be ramp speed
            expected_line = a + bytes((0, 32, subchannel, 0))
        elif profile is F6_02_01:
            a, discriminator = source
            if discriminator == 'left':
                # programmed as function 3, key is 5 for left. Last bytes set to
                # 1,0 as by the PCT
                expected_line = a + bytes((5, 3, subchannel, 0))
            elif discriminator == 'right':
                # key 6 for right, rest as above
                expected_line = a + bytes((6, 3, subchannel, 0))
            else:
                raise ValueError("Unknown discriminator on address %s" % (source,))
        else:
            raise ValueError("It is unknown how this profile could be programmed in.")

        first_empty = None
        for memory_id in range(*self.programmable_dimmer):
            line = await self.read_mem_line(memory_id)
            if line == expected_line:
                self.bus.log.debug("%s: Found programming for profile %s in line %d", self, profile, memory_id)
                return False
            if not any(line) and first_empty is None:
                first_empty = memory_id
        if first_empty is None:
            raise RuntimeError("No free memory to configure this function")
        self.bus.log.info("%s: Writing programming for profile %s in line %d", self, profile, first_empty)
        await self.write_mem_line(first_empty, expected_line)
        return True

    async def set_state(self, channel, dim, total_ramp_time=0):
        """Send a telegram to set the dimming state to dim (from 0 to 255). Total ramp time is the the time in seconds """
        sender = await self.find_direct_command_address(channel)
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

        subchannel = msg.address[3] - self.address
        if subchannel < 0 or subchannel >= self.size or any(msg.address[:3]):
            raise UnrecognizedUpdate("4BS not originating from this device")

        # parsing this as A5-38-08 telegram
        if msg.data[0] != 0x02:
            raise UnrecognizedUpdate("Telegram should be of subtype for dimming")

        # Bits should be data (0x08), absolute (not 0x04), don't store (not 0x02), and on or off fitting the dim value (0x01)
        expected_3 = 0x09 if msg.data[1] != 0 else 0x08
        if msg.data[3] != expected_3:
            raise UnrecognizedUpdate("Odd set bits for dim value %s: 0x%02x" % (msg.data[1], msg.data[3]))

        return {
                "channel": subchannel,
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
        sender = await self.find_direct_command_address(0)
        if sender is not None:
            sender = sender.plain_address()
            dimming = min(random.randint(0, 10) ** 2 + random.randint(0, 3), 100)
            print("I'e found a programmed universal dimmer state input, sending value %d"%dimming)
            await self.set_state(dimming)

    @classmethod
    def annotate_memory(cls, mem):
        return {
                8: MemoryFileStartOfSectionComment("function group 1"),
                9: MemoryFileStartOfSectionComment("function group 2"),
                12: [
                    MemoryFileStartOfSectionComment("function group 3"),
                    MemoryFileNibbleExplanationComment(
                         "AD DR ES S, KY FN SP %%",
                         "key (5 = left, 6 = right), function (eg. 32 = A5-38-08), speed, percent"),
                    ],
                }

class FUD14(DimmerStyle):
    size = 1
    discovery_names = [ bytes((0x04, 0x04)) ]
    has_subchannels = False
    sensor_address_range = range(8, 127)
    range_func_group_1 = range(8,9)
    range_func_group_2 = range(9,12)
    range_func_group_3 = range(12,127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_dimmer = (12, self.memory_size)
        self.gfvs_code = KeyFunction.DIMMING_VALUE_FROM_CONTROLLER

    async def get_all_sensors(self) -> list[SensorInfo]:
        result = []
        result.extend( await self.get_registered_sensors(self.range_func_group_1, 1 ))
        result.extend( await self.get_registered_sensors(self.range_func_group_2, 2 ))
        result.extend( await self.get_registered_sensors(self.range_func_group_3, 3 ))
        return result

class FUD14_800W(FUD14):
    size = 1
    discovery_names = [ bytes((0x04, 0x05)) ]
    has_subchannels = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_dimmer = (12, self.memory_size)
        self.gfvs_code = KeyFunction.DIMMING_VALUE_FROM_CONTROLLER


class HasProgrammableRPS:
    """Mix-in for being programmable with RPS buttons, especially own configured commands

    This can be mixed in to any bus object that has a range of programmable
    slots that follow the FSR14 function group 2 style.
    """

    gfvs_code = 51  # default function to be used by home automation

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._explicitly_configured_command_address = {}

    async def find_direct_command_address(self, channel):
        """Find RPS telegram details (as an AddressExpression with left or
        right as discriminator) to send to switch the given channel"""

        if channel in self._explicitly_configured_command_address:
            return self._explicitly_configured_command_address[channel]

        target_bitset = 1 << channel
        for memory_id in range(*self.programmable_rps):
            line = await self.read_mem_line(memory_id)
            sender = line[:4]
            function = line[5]
            key = line[4]
            channels = line[6]

            if channels != target_bitset:
                continue

            known_functions = { # (function, key) to (EEP, discriminator)
                    (3, 6): (F6_02_01, "right"), # directional buttons enable on down, right keys
                    (3, 5): (F6_02_01, "left"), # directional buttons enable on down, left keys
                    (2, 6): (F6_02_02, "right"), # directional buttons enable on up, right keys
                    (2, 5): (F6_02_02, "left"), # directional buttons enable on up, left keys
                    }
            eep, discriminator = known_functions.get((function, key), (None, None))
            # Not trying to do anything of F6_02_02 -- the "direct commands" we use are F6_02_01 ones.
            if eep is F6_02_01:
                return AddressExpression((sender, discriminator))
        return None, None

    async def ensure_direct_command_addresses(self):
        # Choosing (0, 0, 0, address) because that's where they send from --
        # but in EltakoWrapped messages. So this address should, for other
        # purposes, be free.
        for subchannel in range(self.size):
            source_address = AddressExpression((bytes((0, 0, 0, self.address + subchannel)), "left"))
            await self.ensure_programmed(subchannel, source_address, F6_02_01)
            self._explicitly_configured_command_address[subchannel] = source_address

    async def ensure_programmed(self, subchannel, source: AddressExpression, profile: EEP) -> bool:
        """
        Checks if entry is already present and if not it writes it into the memory at a free place.

        :returns: True if entry was written, False if enrity already exists
        """
        memory_range = self.programmable_rps
        if profile in [F6_02_01, F6_02_02]:
            a, discriminator = source
            #default left
            if discriminator == "right":
                # programmed as function 3, key is 6 for right
                expected_line = a + bytes((6, 3, 1 << subchannel, 0))
            else:
                # programmed as function 3, key is 5 for left
                expected_line = a + bytes((5, 3, 1 << subchannel, 0))

        elif profile in [A5_38_08, H5_3F_7F]:
            a, discriminator = source
            # 51 GFVS = House Automation SW
            expected_line = a + bytes((0, self.gfvs_code, 1 << subchannel, 0))
            
        elif profile in [A5_10_06]:
            a, discriminator = source
            # 65 GFVS = House Automation SW
            expected_line = a + bytes((0, self.gfvs_code, 1 << subchannel, 0))
            memory_range = (self.programmable_rps[0]+subchannel, self.programmable_rps[0]+subchannel)
        else:
            raise ValueError("It is unknown how this profile could be programmed in.")

        first_empty = None
        if memory_range[0] == memory_range[1]:
            first_empty = memory_range[0] # force
        else:
            for memory_id in range(*memory_range):
                line = await self.read_mem_line(memory_id)
                if line == expected_line:
                    self.bus.log.debug("%s: Found programming for subchannel %s and profile %s in line %d", self, subchannel, profile, memory_id)
                    return False
                if not any(line) and first_empty is None:
                    first_empty = memory_id
        if first_empty is None:
            raise RuntimeError("No free memory to configure this function")
        self.bus.log.info("%s: Writing programming for profile %s in line %d", self, profile, first_empty)
        await self.write_mem_line(first_empty, expected_line)
        return True

    async def set_state(self, channel, state: bool):
        command = await self.find_direct_command_address(channel)
        if command is None:
            raise RuntimeError("Can't send without any configured universal remote")

        sender, discriminator = command
        if discriminator == 'left':
            db0 = (0x30, 0x10)[state]
        elif discriminator == 'right':
            db0 = (0x70, 0x50)[state]

        await self.bus.send(ESP2Message(b"\x0b\x05" + bytes([db0]) + b"\0\0\0" + sender + b"\30"))

class FSR14(BusObject, HasProgrammableRPS):
    sensor_address_range = range(8, 127)
    sensors_func_group_1 = range(8,12)
    sensors_func_group_2 = range(12,127)
    gfvs_code = KeyFunction.SWITCHING_STATE_FROM_CONTROLLER
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_rps = (12, self.memory_size)
        

    async def show_off(self):
        await super().show_off()

        want_switch_channel = random.randint(0, self.size - 1)

        print("Will try to switch subchannel %d later" % want_switch_channel)

        for subchannel in range(self.size):
            print("Querying state of channel %d"%subchannel)
            response = await(self.bus.exchange(EltakoPollForced(self.address + subchannel), EltakoWrappedRPS))
            parsed = self.interpret_status_update(response)
            print("Channel is at %d"%parsed[subchannel])

            if subchannel == want_switch_channel:
                want_switch_currentstate = parsed[subchannel]

        print("eading out input programming")

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
    
    async def get_all_sensors(self) -> list[SensorInfo]:
        result = []
        result.extend( await self.get_registered_sensors(self.sensors_func_group_1, 1) )
        result.extend( await self.get_registered_sensors(self.sensors_func_group_2, 2) )
        return result

class FSR14_1x(FSR14):
    discovery_names = [ bytes((0x04, 0x01)) ]
    size = 1

class FSR14_2x(FSR14):
    discovery_names = [ bytes((0x04, 0x02)) ]
    size = 2

class FSR14M_2x(FSR14):
    discovery_names = [ bytes((0x04, 0x0b)) ]
    size = 2

class FSR14_4x(FSR14):
    discovery_names = [ bytes((0x04, 0x01)) ]
    size = 4

class F4SR14_LED(FSR14):
    discovery_names = [ bytes((0x04, 0x09)) ]
    size = 4

class FSB14(BusObject, HasProgrammableRPS):
    size = 2
    discovery_names = [ bytes((0x04, 0x06)) ]
    sensor_address_range = range(17, 127)
    range_func_group_1 = range(16,17)
    range_func_group_2 = range(17,127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_rps = (17, self.memory_size)
        self.gfvs_code = KeyFunction.OPERATIONS_COMMAND_WITH_TIME_VALUE_TRASMISSION_FROM_CONTROLLER

    @classmethod
    def annotate_memory(cls, mem):
        return {
                17: [MemoryFileStartOfSectionComment("function group 2"),
                    MemoryFileNibbleExplanationComment(
                         "AD DR ES S, KY FN CH ??",
                         "key (5 = left, 6 = right), function (3 = bottom open, 2 = upper open), ch = affected channels as bits, ?? = maybe driving time (00 for switches)"),
                    ]
                }

    def interpret_status_update(self, msg):
        if not isinstance(msg, EltakoWrapped4BS) and not isinstance(msg, EltakoWrappedRPS):
            try:
                msg = EltakoWrapped4BS.parse(msg.serialize())
            except ParseError:
                try:
                    msg = EltakoWrappedRPS.parse(msg.serialize())
                except ParseError:
                    raise UnrecognizedUpdate("Not recognizable update: %s" % msg)

        try:
            channel = {
                    bytes((0, 0, 0, self.address)): 0,
                    bytes((0, 0, 0, self.address + 1)): 1,
                    }[msg.address]
        except KeyError:
            raise UnrecognizedUpdate("Address not recognized")

        if isinstance(msg, EltakoWrappedRPS):
            states = {
                    0x01: "moving up",
                    0x02: "moving down",
                    0x70: "top",
                    0x50: "bottom",
                    }
            try:
                return (channel, states[msg.data[0]])
            except KeyError:
                raise UnrecognizedUpdate("Unknown data value in RPS: %s" % msg.data[0])
        else:
            # They are known but not implemented, as their information content
            # is only moved time, which is not usable without a persistent
            # model and known timing parameters
            pass

    async def show_off(self):
        await super().show_off()

        response = await self.bus.exchange(EltakoBusUnlock())
        print("Unlocked:", response)

        await asyncio.sleep(10)

        print("Moving down")
        sender = bytes((0, 0, 0, 9))
        # 30 = up for the taught in left side "open up", 10 = down
        msg = RPSMessage(sender, status=0x30, data=bytes((0x10,)), outgoing=True)
        print(msg, msg.serialize().hex())
        await self.bus.send(msg)

        while True:
            msg = await self.bus.received.get()
            msg = prettify(msg)
            if isinstance(msg, EltakoPoll):
                continue

            if (isinstance(msg, EltakoWrapped4BS) or isinstance(msg, EltakoWrappedRPS)) and msg.address == bytes((0, 0, 0, self.address)): # channel 1
                print(msg)
                try:
                    interpreted = self.interpret_status_update(msg)
                    print(interpreted)
                except Exception as e:
                    print("Something went wrong", repr(e), e)

    async def get_all_sensors(self) -> list[SensorInfo]:
        result = []
        result.extend( await self.get_registered_sensors(self.range_func_group_1, 1) )
        result.extend( await self.get_registered_sensors(self.range_func_group_2, 2) )
        return result

class F3Z14D(BusObject):
    discovery_names = [ bytes((0x04, 0x67)) ]
    size = 3

class FMZ14(BusObject, HasProgrammableRPS):
    discovery_names = [ bytes((0x04, 0x0e)) ]
    size = 1
    sensor_address_range = range(8, 8+47)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_rps = (8, self.memory_size)
        self.gfvs_code = KeyFunction.SWITCHING_STATE_FROM_CONTROLLER

    async def get_all_sensors(self) -> list[SensorInfo]:
        return await self.get_registered_sensors(self.sensor_address_range, 1)

class FWG14MS(BusObject):
    discovery_names = [ bytes((0x04, 0x1a)) ]
    size = 1

class FSU14(BusObject):
    discovery_names = [ bytes((0x07, 0x14)) ]
    size = 8
    async def show_off(self):
        await super().show_off()

        hour = random.randint(0, 23)
        minutes = random.randint(0, 59)
        print("Setting clock to %02d:%02d"%(hour, minutes))
        await self.write_mem_line(0x5d, b"\x16\x01\x01\x08" + bytes((((hour // 10) << 4) + (hour % 10), ((minutes // 10) << 4) + (minutes % 10))) + b"\x00\x01")

        await asyncio.sleep(3)

class FMSR14(BusObject):
    discovery_names = [ bytes((0x05, 0x15)) ]
    size = 5

class FWZ14_65A(BusObject):
    discovery_names = [ bytes((0x04, 0x66)) ]
    size = 1

    @classmethod
    def annotate_memory(cls, mem):
        return {
                1: MemoryFileNibbleExplanationComment(".. .. .. .. ..  SUM kWh", "accumulated counter value as sent in DT=0 DIV=0 telegram"),
                5: MemoryFileNibbleExplanationComment("S0 S1 S2 S3 .. .. .. ..", "Serial number as sent in DT=1 DIV=3 TI=8 messages (once as with DB3..1 = S1 S0 00, once as S3 S2 01)")
                }

    async def read_serial(self):
        return b2a((await self.read_mem_line(5))[:4])

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
    discovery_names = [ bytes((0x04, 0x07)) ]
    size = 1
    has_subchannels = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_rps = (12, self.memory_size)
        self.gfvs_code = 32

class FGW14_USB(BusObject):
    discovery_names = [ bytes((0x04, 0xfe)) ]
    size = 1

class FDG14(DimmerStyle):
    discovery_names = [ bytes((0x04, 0x34)) ]
    size = 16
    has_subchannels = True
    dim_mask_scene_1_range = range(2,4)
    dim_mask_scene_2_range = range(4,6)
    dim_mask_scene_3_range = range(6,8)
    dim_mask_scene_4_range = range(8,10)
    sensor_address_range = range(14, 127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_dimmer = (14, self.memory_size)
        self.gfvs_code = 32

    async def get_all_sensors(self) -> list[SensorInfo]:
        return await self.get_registered_dali_devices(self.sensor_address_range, 1)

    # Known oddities: Announces with 0e byte at payload[3] of the
    # EltakoDiscoveryReply.
    #
    # It also reports as a device at offset +8, probably for compatibility with
    # FAMs that don't know of the address expansion trick. Enumeration might
    # find this odd when trying to read its memory (but enumeration that's not
    # only there for debugging should skip ahead by size anyway, and not run
    # into this).

    @classmethod
    def annotate_memory(cls, mem):
        return {
                2: MemoryFileStartOfSectionComment("16 dimmer values (0-100, or 101 for 'MASK') for light scene 1"),
                4: MemoryFileStartOfSectionComment("16 dimmer values for light scene 2"),
                6: MemoryFileStartOfSectionComment("16 dimmer values for light scene 3"),
                8: MemoryFileStartOfSectionComment("16 dimmer values for light scene 4"),

                # FIXME: Find out where "send confirmation as dimmer telegram"
                # is stored, and provide a way to ensure that

                14: [
                    MemoryFileStartOfSectionComment("function group 1"),
                    MemoryFileNibbleExplanationComment(
                         "AD DR ES S, KY FN DG V ",
                         "key (5 = left, 6 = right), function (eg. 32 = A5-38-08), DG = Dali Group (0x10 = broadcast), v = value (e.g. dimming in percentage, brightness)"),
                    ],
                }


class FD2G14(FDG14):
    discovery_names = [ bytes((0x04, 0x82)) ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    
class FAE14SSR(BusObject, HasProgrammableRPS):
    size = 2
    discovery_names = [ bytes((0x04, 0x16)) ]
    thermostat_address_range = range(8,10)
    temp_sensor_range = range(10,12)
    smart_home_controller_address_range = range(12,14)
    sensor_address_range = range(14, 127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.programmable_rps = self.smart_home_controller_address_range
        self.gfvs_code = KeyFunction.TEMPERATURE_CONTROLLER_SETPOINT

    @classmethod
    def annotate_memory(cls, mem):
        return {
                1: MemoryFileNibbleExplanationComment(
                    "AD DR ES S, -- -- -- --", "Base address"),
                4: MemoryFileNibbleExplanationComment(
                    "-- RV -- -- -- -- -- --",
                    "RV = return value, 1. bit channel 1 & 2. bit channel 2 "),
                5: MemoryFileNibbleExplanationComment(
                    "-- -- -- -- dt dt -- --", "temp offset channel 1 & 2"),
                7: MemoryFileNibbleExplanationComment(
                    "a  a  hc tp hc tp  tt tt", ""),
                cls.thermostat_address_range[0]: MemoryFileStartOfSectionComment("function group 1 / Temp Controller"),
                cls.temp_sensor_range[0]: MemoryFileStartOfSectionComment("function group 2 / Temp Sensor"),
                cls.smart_home_controller_address_range[0]: MemoryFileStartOfSectionComment("function group 3 / Smart Home SW"),
                cls.sensor_address_range[0]: MemoryFileStartOfSectionComment("function group 3 / switches, contacts, ..."),
                }
    
    async def get_all_sensors(self) -> list[SensorInfo]:
        result = []
        result.extend( await self.get_registered_sensors(self.thermostat_address_range, 1 ))
        result.extend( await self.get_registered_sensors(self.temp_sensor_range, 2 ))
        result.extend( await self.get_registered_sensors(self.smart_home_controller_address_range, 3 ))
        result.extend( await self.get_registered_sensors(self.sensor_address_range, 4 ))
        return result

class FHK14(FAE14SSR):
    size=2
    discovery_names = [ bytes((0x04, 0x18)) ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class F4HK14(FHK14, HasProgrammableRPS):
    size = 4
    discovery_names = [ bytes((0x04, 0x18)) ]
    thermostat_address_range = range(8,12)
    temp_sensor_range = range(12,16)
    smart_home_controller_address_range = range(16,20)
    sensor_address_range = range(20, 127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


class FTD14(BusObject):
    size=1
    discovery_names = [ bytes((0x04, 0xa0)) ]
    sensor_address_range = range(8, 127)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    async def get_base_id(self) -> str:
        """Gets base id from memory."""
        mem_line = await self.read_mem_line(1)
        return b2s(mem_line[0:4])
    
    async def get_base_id_in_bytes(self) -> bytes:
        """Gets base id from memory."""
        mem_line = await self.read_mem_line(1)
        return mem_line[0:4]

    async def get_base_id_in_int(self) -> int:
        """Gets base id from memory."""
        mem_line = await self.read_mem_line(1)
        return int.from_bytes(mem_line[0:4], "big") 
    
    async def get_all_sensors(self) -> list[SensorInfo]:
        result = []
        result.extend( await self.get_registered_sensors(self.sensor_address_range, 1) )
        return result



known_objects = [FAM14, FUD14, FUD14_800W, FSB14, FSR14_1x, FSR14_2x, FSR14M_2x, FSR14_4x, F4SR14_LED, F3Z14D, FMZ14, FWG14MS, FSU14, FMSR14, FWZ14_65A, FSG14_1_10V, FGW14_USB, FDG14, FD2G14, FHK14, F4HK14, FAE14SSR, FTD14]
# sorted so the first match of (discovery name is a prefix, size matches) can be used
sorted_known_objects = sorted(known_objects, key=lambda o: len(o.discovery_names[0]) + 0.5 * (o.size is not None), reverse=True)

async def create_busobject(bus, id):
    response = await bus.exchange(EltakoDiscoveryRequest(address=id), EltakoDiscoveryReply, retries=5)

    if response == None:
        return
    
    assert id == response.reported_address, "Queried for ID %s, received %s" % (id, prettify(response))

    for o in sorted_known_objects:
        if response.model[0:2] in o.discovery_names and (o.size is None or o.size == response.reported_size):
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
