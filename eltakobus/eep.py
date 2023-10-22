from enum import Enum
from .error import NotImplementedError, WrongOrgError
from .message import RPSMessage, Regular1BSMessage, Regular4BSMessage
import re

class EEP:
    __sublasses_by_string = {}

    @classmethod
    def decode_message(cls, msg):
        raise NotImplementedError

    def encode_message(self, address):
        raise NotImplementedError
    

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        
        if re.match("^([0-9a-zA-Z]{2})_([0-9a-zA-Z]{2})_([0-9a-zA-Z]{2})$", cls.__name__):
            cls.eep_string = cls.__name__.replace("_", "-")
            cls.__sublasses_by_string[cls.eep_string] = cls

    @classmethod
    def find(cls, eep_string):
        eep = cls.__sublasses_by_string[eep_string]
        
        if eep == None:
            raise NotImplementedError
        else:
            return eep

# ======================================
# MARK: - Rocker switch
# ======================================

class _RockerSwitch(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        
        rocker_first_action = (msg.data[0] & 0xE0) >> 5
        energy_bow = (msg.data[0] & 0x10) >> 4
        rocker_second_action = (msg.data[0] & 0x0E) >> 1
        second_action = msg.data[0] & 0x01
        
        return cls(rocker_first_action, energy_bow, rocker_second_action, second_action)

    def encode_message(self, address):
        data = bytearray([0])
        data[0] = data[0] | self.second_action
        data[0] = data[0] | (self.rocker_second_action << 1)
        data[0] = data[0] | (self.energy_bow << 4)
        data[0] = data[0] | (self.rocker_first_action << 5)
        
        status = 0x30
        
        return RPSMessage(address, status, data, True)

    @property
    def rocker_first_action(self):
        return self._rocker_first_action

    @property
    def energy_bow(self):
        return self._energy_bow

    @property
    def rocker_second_action(self):
        return self._rocker_second_action

    @property
    def second_action(self):
        return self._second_action

    def __init__(self, rocker_first_action, energy_bow, rocker_second_action, second_action):
        self._rocker_first_action = rocker_first_action
        self._energy_bow = energy_bow
        self._rocker_second_action = rocker_second_action
        self._second_action = second_action

class F6_02_01(_RockerSwitch):
    """2-part Rocker switch, Application Style 1 (European, bottom switches
    on)"""
    
class F6_02_02(_RockerSwitch):
    """2-part Rocker switch, Application Style 2 (US, top switches on)"""

# ======================================
# MARK: - Window handle
# ======================================

class _WindowHandle(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        
        movement = msg.data[0]
        
        return cls(movement)

    def encode_message(self, address):
        data = bytearray([0])
        data[0] = self.movement
        
        status = 0x20
        
        return RPSMessage(address, status, data, True)

    @property
    def movement(self):
        return self._movement

    def __init__(self, movement):
        self._movement = movement

class F6_10_00(_WindowHandle):
    """Windows handle"""
    
# ======================================
# MARK: - Single input contact
# ======================================

class _SingleInputContact(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x06:
            raise WrongOrgError
        
        learn_button = (msg.data[0] & 0x08) >> 3
        contact = msg.data[0] & 0x01
        
        return cls(learn_button, contact)

    def encode_message(self, address):
        data = bytearray([0])
        data[0] = data[0] | self.contact
        data[0] = data[0] | (self.learn_button << 3)

        status = 0x00
        
        return Regular1BSMessage(address, status, data, True)

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def contact(self):
        return self._contact

    def __init__(self, learn_button, contact):
        self._learn_button = learn_button
        self._contact = contact

class D5_00_01(_SingleInputContact):
    """Single input contact"""

# ======================================
# MARK: - Light, Temperature and Occupancy sensor
# ======================================

class _LightTemperatureOccupancySensor(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        occupancy_button = msg.data[3] & 0x01
        pir_status = (msg.data[3] & 0x02) >> 1
        learn_button = (msg.data[3] & 0x08) >> 3
        
        temperature = cls.temp_min + ((msg.data[2] / 255.0) * (cls.temp_max - cls.temp_min))
        illumination = cls.illu_min + ((msg.data[1] / 255.0) * (cls.illu_max - cls.illu_min))
        supply_voltage = cls.volt_min + ((msg.data[0] / 255.0) * (cls.volt_max - cls.volt_min))
        
        return cls(supply_voltage, illumination, temperature, learn_button, pir_status, occupancy_button)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[3] = data[3] | self.occupancy_button
        data[3] = data[3] | (self.pir_status << 1)
        data[3] = data[3] | (self.learn_button << 3)
        
        data[2] = int(((self.temperature - cls.temp_min) / (cls.temp_max - cls.temp_min)) * 255.0)
        data[1] = int(((self.illumination - cls.illu_min) / (cls.illu_max - cls.illu_min)) * 255.0)
        data[0] = int(((self.supply_voltage - cls.volt_min) / (cls.volt_max - cls.volt_min)) * 255.0)

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)

    @property
    def supply_voltage(self):
        return self._supply_voltage
        
    @property
    def illumination(self):
        return self._illumination
        
    @property
    def temperature(self):
        return self._temperature
        
    @property
    def learn_button(self):
        return self._learn_button

    @property
    def pir_status(self):
        return self._pir_status

    @property
    def occupancy_button(self):
        return self._occupancy_button

    def __init__(self, supply_voltage, illumination, temperature, learn_button, pir_status, occupancy_button):
        self._supply_voltage = supply_voltage
        self._illumination = illumination
        self._temperature = temperature
        self._learn_button = learn_button
        self._pir_status = pir_status
        self._occupancy_button = occupancy_button

class A5_08_01(_LightTemperatureOccupancySensor):
    """Light, Temperature and Occupancy sensor"""
    temp_min = 0.0
    temp_max = 51.0
    illu_min = 0.0
    illu_max = 510.0
    volt_min = 0.0
    volt_max = 5.1

# ======================================
# MARK: - Central Command
# ======================================

class _CentralCommand(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        command = msg.data[0]
        
        if command == 0x01:
            time = ((msg.data[1] << 8) | msg.data[2]) / 10.0
            learn_button = (msg.data[3] & 0x08) >> 3
            lock = (msg.data[3] & 0x04) >> 2
            delay_or_duration = (msg.data[3] & 0x02) >> 1
            switching_command = msg.data[3] & 0x01
            
            switching = CentralCommandSwitching(time, learn_button, lock, delay_or_duration, switching_command)
            
            return cls(command=command, switching=switching)
        elif command == 0x02:
            dimming_value = msg.data[1]
            ramping_time = msg.data[2]
            learn_button = (msg.data[3] & 0x08) >> 3
            dimming_range = (msg.data[3] & 0x04) >> 2
            store_final_value = (msg.data[3] & 0x02) >> 1
            switching_command = msg.data[3] & 0x01
            
            dimming = CentralCommandDimming(dimming_value, ramping_time, learn_button, dimming_range, store_final_value, switching_command)
            
            return cls(command=command, dimming=dimming)
        else:
            raise NotImplementedError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[0] = self.command

        if self.command == 0x01:
            data[3] = self.switching.switching_command
            data[3] = data[3] | (self.switching.delay_or_duration << 1)
            data[3] = data[3] | (self.switching.lock << 2)
            data[3] = data[3] | (self.switching.learn_button << 3)
            data[2] = int(self.switching.time * 10) & 0xFF
            data[1] = int(self.switching.time * 10) >> 8
        elif self.command == 0x02:
            data[3] = self.dimming.switching_command
            data[3] = data[3] | (self.dimming.store_final_value << 1)
            data[3] = data[3] | (self.dimming.dimming_range << 2)
            data[3] = data[3] | (self.dimming.learn_button << 3)
            data[2] = self.dimming.ramping_time
            data[1] = self.dimming.dimming_value
        else:
            raise NotImplementedError

        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def command(self):
        return self._command
        
    @property
    def switching(self):
        return self._switching
        
    @property
    def dimming(self):
        return self._dimming
        
    def __init__(self, command, switching=None, dimming=None):
        self._command = command
        self._switching = switching
        self._dimming = dimming

class CentralCommandSwitching:
    @property
    def time(self):
        return self._time

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def lock(self):
        return self._lock

    @property
    def delay_or_duration(self):
        return self._delay_or_duration

    @property
    def switching_command(self):
        return self._switching_command

    def __init__(self, time, learn_button, lock, delay_or_duration, switching_command):
        self._time = time
        self._learn_button = learn_button
        self._lock = lock
        self._delay_or_duration = delay_or_duration
        self._switching_command = switching_command

class CentralCommandDimming:
    @property
    def dimming_value(self):
        return self._dimming_value

    @property
    def ramping_time(self):
        return self._ramping_time

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def dimming_range(self):
        return self._dimming_range

    @property
    def store_final_value(self):
        return self._store_final_value

    @property
    def switching_command(self):
        return self._switching_command

    def __init__(self, dimming_value, ramping_time, learn_button, dimming_range, store_final_value, switching_command):
        self._dimming_value = dimming_value
        self._ramping_time = ramping_time
        self._learn_button = learn_button
        self._dimming_range = dimming_range
        self._store_final_value = store_final_value
        self._switching_command = switching_command

class A5_38_08(_CentralCommand):
    """Central Command Gateway"""

# ======================================
# MARK: - Eltako Gateway Switching
# ======================================

class _EltakoSwitchingCommand(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        
        state = (msg.data[0] & 0x20) >> 5
        
        return cls(state)

    def encode_message(self, address):
        data = bytearray([0])
        data[0] = 0x50 | (self.state << 5)
        
        status = 0x30
        
        return RPSMessage(address, status, data, True)

    @property
    def state(self):
        return self._state

    def __init__(self, state):
        self._state = state

class M5_38_08(_EltakoSwitchingCommand):
    """Eltako Gateway Switching - This is implemented pretty rudimentary"""


# ======================================
# MARK: - Heating and Cooling
# ======================================

class _HeatingCooling(EEP):

    class Heater_Mode(Enum):
        NORMAL = 0
        STAND_BY_2_DEGREES = 1
        NIGHT_SET_BACK_4_DEGREES = 2
        OFF = 3

    @classmethod
    def decode_message(cls, msg):
        if msg.org == 0x07:

            night_setback = msg.data[0] % 2 == 0
            temp = msg.data[1]/255.0*40.0
            set_point_temp = msg.data[2]/255.0*40.0
            d3 = msg.data[3]
            mode = cls.Heater_Mode.NORMAL
            if d3 == 25:
                mode = cls.Heater_Mode.NIGHT_SET_BACK_4_DEGREES
            elif d3 == 12:
                mode = cls.Heater_Mode.STAND_BY_2_DEGREES
            elif d3 == 0 and set_point_temp == 0:
                mode = cls.Heater_Mode.OFF

            return cls(mode, set_point_temp, temp, night_setback)
        else:
            raise WrongOrgError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])

        data[0] = 15
        if self.stand_by:
            data[0] = 14

        data[1] = self.temp/40.0*255.0

        data[2] = self.set_point_temp/40.0*255.0
        
        data[3] = 0
        if self.mode == _HeatingCooling.Heater_Mode.NIGHT_SET_BACK_4_DEGREES:
            data[3] = 25
        elif self.mode == _HeatingCooling.Heater_Mode.STAND_BY_2_DEGREES:
            data[3] = 12
        elif self.mode == _HeatingCooling.Heater_Mode.OFF:
            data[2] = 0
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def mode(self):
        return self._mode
    
    @property
    def set_point_temp(self):
        return self._set_point_temp
    
    @property
    def temp(self):
        return self._temp
    
    @property
    def stand_by(self):
        return self._stand_by

    def __init__(self, mode: Heater_Mode, set_point_temp: int, temp: int, stand_by: bool):
        self._mode  = mode
        self._set_point_temp = set_point_temp
        self._temp = temp
        self._stand_by = stand_by


class A5_10_06(_HeatingCooling):
    """Heating and Cooling"""

#TODO: to be implemanted
class A5_10_12(EEP):
    """Temperature Controller Command"""

# ======================================
# MARK: - Weather station
# ======================================

class _WeatherStation(EEP):
    temp_min = -40.0
    temp_max = 80.0
    
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        identifier = (msg.data[3] & 0xF0) >> 4
        learn_button = (msg.data[3] & 0x08) >> 3

        if identifier == 0x01:
            dawn_sensor = (msg.data[0] / 255.0) * 999.0
            temperature = cls.temp_min + ((msg.data[1] / 255.0) * (cls.temp_max - cls.temp_min))
            wind_speed = (msg.data[2] / 255.0) * 70.0
            day_night = (msg.data[3] & 0x04) >> 2
            rain_indication = (msg.data[3] & 0x02) >> 1
            
            return cls(identifier=identifier, learn_button=learn_button, dawn_sensor=dawn_sensor, temperature=temperature, wind_speed=wind_speed, day_night=day_night, rain_indication=rain_indication)
        elif identifier == 0x02:
            sun_west = (msg.data[0] / 255.0) * 150.0
            sun_south = (msg.data[1] / 255.0) * 150.0
            sun_east = (msg.data[2] / 255.0) * 150.0
            hemisphere = (msg.data[3] & 0x04) >> 2
            
            return cls(identifier=identifier, learn_button=learn_button, sun_west=sun_west, sun_south=sun_south, sun_east=sun_east, hemisphere=hemisphere)
        else:
            raise NotImplementedError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        if self.identifier == 0x01:
            data[3] = data[3] | (self.rain_indication << 1)
            data[3] = data[3] | (self.day_night << 2)
            data[3] = data[3] | (self.learn_button << 3)
            data[2] = int((self.wind_speed / 70.0) * 255.0)
            data[1] = int(((self.temperature - cls.temp_min) / (cls.temp_max - cls.temp_min)) * 255.0)
            data[0] = int((self.dawn_sensor / 999.0) * 255.0)
        elif self.identifier == 0x02:
            data[3] = data[3] | self.hemisphere
            data[3] = data[3] | (self.learn_button << 3)
            data[2] = int((self.sun_east / 150.0) * 255.0)
            data[1] = int((self.sun_south / 150.0) * 255.0)
            data[0] = int((self.sun_west / 150.0) * 255.0)
        else:
            raise NotImplementedError

        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def dawn_sensor(self):
        return self._dawn_sensor

    @property
    def temperature(self):
        return self._temperature

    @property
    def wind_speed(self):
        return self._wind_speed

    @property
    def identifier(self):
        return self._identifier

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def day_night(self):
        return self._day_night

    @property
    def rain_indication(self):
        return self._rain_indication

    @property
    def sun_west(self):
        return self._sun_west

    @property
    def sun_south(self):
        return self._sun_south

    @property
    def sun_east(self):
        return self._sun_east

    @property
    def hemisphere(self):
        return self._hemisphere

    def __init__(self, identifier, learn_button,
        dawn_sensor=None, temperature=None, wind_speed=None, day_night=None, rain_indication=None,
        sun_west=None, sun_south=None, sun_east=None, hemisphere=None):
        self._dawn_sensor = dawn_sensor
        self._temperature = temperature
        self._wind_speed = wind_speed
        self._identifier = identifier
        self._learn_button = learn_button
        self._day_night = day_night
        self._rain_indication = rain_indication
        self._sun_west = sun_west
        self._sun_south = sun_south
        self._sun_east = sun_east
        self._hemisphere = hemisphere

class A5_13_01(_WeatherStation):
    """Weather station"""

# ======================================
# MARK: -  temperature + humidity sensor
# ======================================
class _TemperatureAndHumiditySensor(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        # 0 .. 100%
        humidity = (msg.data[1] /255.0) * 100
        # -20°C .. +60°C
        temperature = (msg.data[2] / 255.0 ) * 80.0 - 20.0
        

        return cls(temperature,humidity)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        data[0] = 0x00
        data[1] = int((self.humidity / 100.0) * 255.0)
        data[2] = int(((self.temperature + 20.0) / 80.0) * 255.0)
        data[3] = 0x00
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def temperature(self):
        return self._temperature
    
    @property
    def humidity(self):
        return self._humidity
    
    def __init__(self, temperature, humidity):
        self._temperature = temperature
        self._humidity = humidity

class A5_04_02(_TemperatureAndHumiditySensor):
    """Temperature and Humidity Sensor"""

# ======================================
# MARK: - Automated Meter Reading
# ======================================

class _AutomatedMeterReading(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        meter_reading = (msg.data[0] << 16) | (msg.data[1] << 8) | msg.data[2]
        measurement_channel = msg.data[3] >> 4
        learn_button = (msg.data[3] & 0x08) >> 3
        data_type = (msg.data[3] & 0x04) >> 2
        divisor = msg.data[3] & 0x03
        
        return cls(meter_reading, measurement_channel, learn_button, data_type, divisor)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[0] = (self.meter_reading & 0xFF0000) >> 16
        data[1] = (self.meter_reading & 0x00FF00) >> 8
        data[2] = (self.meter_reading & 0x0000FF)
        data[3] = data[3] | (self.learn_button << 4)
        data[3] = data[3] | (self.measurement_channel << 3)
        data[3] = data[3] | (self.data_type << 2)
        data[3] = data[3] | self.divisor

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)

    @property
    def meter_reading(self):
        return self._meter_reading

    @property
    def measurement_channel(self):
        return self._measurement_channel

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def data_type(self):
        return self._data_type

    @property
    def divisor(self):
        return self._divisor

    def __init__(self, meter_reading, measurement_channel, learn_button, data_type, divisor):
        self._meter_reading = meter_reading
        self._measurement_channel = measurement_channel
        self._learn_button = learn_button
        self._data_type = data_type
        self._divisor = divisor

class A5_12_01(_AutomatedMeterReading):
    """Automated Meter Reading - Electricity"""

class A5_12_02(_AutomatedMeterReading):
    """Automated Meter Reading - Gas"""

class A5_12_03(_AutomatedMeterReading):
    """Automated Meter Reading - Water"""

# ======================================
# MARK: - Eltako Shutter Status
# ======================================

class _EltakoShutterStatus(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org == 0x05:
            state = msg.data[0]
            return cls(state=state)
        elif msg.org == 0x07:
            time = msg.data[0] << 8 | msg.data[1]
            direction = msg.data[2]
            return cls(time=time, direction=direction)
        else:
            raise WrongOrgError

    def encode_message(self, address):
        if state is not None:
            data = bytearray([0])
            data[0] = self.state
            
            status = 0x30
            
            return RPSMessage(address, status, data, True)
        else:
            data = bytearray([0, 0, 0, 0])
            data[0] = self.time >> 8
            data[1] = self.time & 0xFF
            data[2] = self.direction
            data[3] = 0x0A
            
            status = 0x00

            return Regular4BSMessage(address, status, data, True)

    @property
    def state(self):
        return self._state
        
    @property
    def time(self):
        return self._time

    @property
    def direction(self):
        return self._direction

    def __init__(self, state=None, time=None, direction=None):
        self._state = state
        self._time = time
        self._direction = direction

class G5_3F_7F(_EltakoShutterStatus):
    """Eltako Shutters"""

# ======================================
# MARK: - Eltako Shutter Command
# ======================================

class _EltakoShutterCommand(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        time = msg.data[1]
        command = msg.data[2]
        learn_button = (msg.data[3] & 0x08) >> 3

        return cls(time, command, learn_button)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[1] = self.time
        data[2] = self.command
        data[3] = data[3] | (self.learn_button << 3)

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)

    @property
    def time(self):
        return self._time

    @property
    def command(self):
        return self._command

    @property
    def learn_button(self):
        return self._learn_button

    def __init__(self, time, command, learn_button):
        self._time = time
        self._command = command
        self._learn_button = learn_button

class H5_3F_7F(_EltakoShutterCommand):
    """Eltako Shutter Command"""
