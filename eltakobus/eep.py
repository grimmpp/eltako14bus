from enum import Enum

from eltakobus.util import DefaultEnum
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


class _switch_button(EEP):
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        
        button_pushed = msg.data[0] == 0x10
        
        return cls(button_pushed)

    def encode_message(self, address):
        data = bytearray([0])

        if self._button_pushed:
            data[0] = 0x10
        
        status = 0x20
        
        return RPSMessage(address, status, data, True)
    
    @property
    def button_pushed(self):
        return self._button_pushed
    
    def __init__(self, button_pushed:bool=True):
        self._button_pushed = button_pushed


class F6_01_01(_switch_button):
    """one button switch"""


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

class WindowHandlePosition(int, Enum):
    CLOSED = 0
    OPEN = 1
    TILT = 2

    @classmethod
    def get_position(cls, movement:int):
        # left  to down 0b1111
        # right to down 0b1111
        if movement == 0xF: 
            return WindowHandlePosition.CLOSED
        # up to left    0b11X0
        # down to left  0b11X0
        # up to right   0b11X0
        # down to right 0b11X0
        elif movement == 0xC or movement == 0xE:
            return WindowHandlePosition.OPEN
        # right to up 0b1101
        # left to up  0b1101
        elif movement == 0xD:
            return WindowHandlePosition.TILT
        
        raise Exception(f"Movement data ({movement}) not handled")

class _WindowHandle(EEP):

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        
        movement = msg.data[0]
        
        handle_position = WindowHandlePosition.get_position(movement >> 4)

        return cls(movement, handle_position)

    def encode_message(self, address):
        data = bytearray([0])
        data[0] = self.movement
        
        status = 0x20
        
        return RPSMessage(address, status, data, True)

    @property
    def movement(self):
        return self._movement
    
    @property
    def handle_position(self):
        return self._handle_position

    def __init__(self, movement:int=0, handle_position:WindowHandlePosition=WindowHandlePosition.CLOSED):
        self._movement = movement
        self._handle_position = handle_position

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

    def __init__(self, learn_button:int=1, contact:int=9):
        self._learn_button = learn_button
        self._contact = contact

class D5_00_01(_SingleInputContact):
    """Single input contact"""

# ======================================
# MARK: - Light, Temperature and Occupancy sensor
# ======================================

class _LightTemperatureOccupancySensor(EEP):
    temp_min = 0.0
    temp_max = 51.0
    illu_min = 0.0
    illu_max = 510.0
    volt_min = 0.0
    volt_max = 5.1

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
        
        data[2] = int(((self.temperature - self.temp_min) / (self.temp_max - self.temp_min)) * 255.0)
        data[1] = int(((self.illumination - self.illu_min) / (self.illu_max - self.illu_min)) * 255.0)
        data[0] = int(((self.supply_voltage - self.volt_min) / (self.volt_max - self.volt_min)) * 255.0)

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
    def current_temperature(self):
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

    def __init__(self, supply_voltage:int=0, illumination:int=0, temperature:int=0, learn_button:int=1, pir_status:int=0, occupancy_button:int=0):
        self._supply_voltage = supply_voltage
        self._illumination = illumination
        self._temperature = temperature
        self._learn_button = learn_button
        self._pir_status = pir_status
        self._occupancy_button = occupancy_button

class A5_08_01(_LightTemperatureOccupancySensor):
    """Light, Temperature and Occupancy sensor"""
    

class VOC_Unit(Enum):

    def __new__(cls, index:int, label:str):
        obj = object.__new__(cls)
        obj._value_ = index
        obj._label = label
        return obj
    
    @property
    def index(self) -> int:
        return self._value_

    @property
    def label(self) -> str:
        return self._label

    PPB = (0, "ppb")
    MGM3 = (1, "µg/m3")


class VOC_SubstancesType(Enum):

    def __new__(cls, index:int, name_de:str, name_en:str, formula:str, unit:str):
        obj = object.__new__(cls)
        obj._value_ = index
        obj._name = name_en
        obj._name_de = name_de
        obj._name_en = name_en
        obj._formula = formula
        obj._unit = unit
        return obj

    @property
    def index(self) -> int:
        return self._value_

    @property
    def name(self) -> str:
        return self._name

    @property
    def name_de(self) -> str:
        return self._name_de

    @property
    def name_en(self) -> str:
        return self._name_en

    @property
    def unit(self) -> str:
        return self._unit
    
    @property
    def formula(self) -> str:
        return self._formula

    # index, de-name, en-name, formula, unit
    VOCT_TOTAL = 0, 'VOCT Total', 'VOCT Total', '', VOC_Unit.PPB.label
    Formaldehyde = 1, 'Formaldehyd', 'Formaldehyde', 'CH2O', ''
    BENZENE = 2, 'Benzol', 'Benzene', 'C6H6', ''
    STYRENE = 3, 'Styren', 'Styrene', 'C8H8', ''
    TOLUENE = 4, 'Toluol', 'Toluene', 'IUPAC', ''
    TETRACHLOROETHYLENE = 5, 'Tetrachlorethen', 'Tetrachloroethylene', 'C4CI4', ''
    XYLENE = 6, 'Hexan', 'Xylene', 'C8H10', ''
    HEXANE  = 7, 'Styren', 'Hexane', 'C6H14', ''
    OCTANE = 8, 'Octane', 'Octane', 'C8H18', ''
    CYCLOPENTANE  = 9, 'Cyclopentan', 'Cyclopentane', 'C5H10', ''
    METHANOL = 10, 'Methanol', 'Methanol', 'CH3OH', ''
    ETHANOL = 11, 'Ethanol', 'Ethanol', 'C2H6O', ''
    PENTANOL_1 = 12, '1-Pentanol', '1-Pentanol', 'C5H12O', ''
    ACETONE = 13, 'Aceton', 'Acetone', 'C3H6O', ''
    ETHYLENE_OXIDE = 14, 'Ethylenoxid', 'ethylene Oxide', 'C2H4O', ''
    ACETALDEHYDE = 15, 'Acetaldehyd', 'Acetaldehyde ue', 'CH3-CHO', ''
    ACETIC_ACID = 16, 'Essigsäure', 'Acetic Acid', 'CH3COOH', ''
    PROPIOICE_ACID = 17, 'Propionsäure', 'Propionice Acid', 'C3H6O2', ''
    VALERIC_ACID = 18, 'Valeriansäure', 'Valeric Acid', 'C5H10O2', ''
    BUTYRIC_ACID = 19, 'Buttersäure', 'Butyric Acid', 'C4H8O2', ''
    AMMONIAC = 20, 'Ammoniak', 'Ammoniac', 'NH3', ''
    HYDROGEN_SULFIDE = 22, 'Schwefelwasserstoff', 'Hydrogen Sulfide', 'H2S', ''
    DIMETHYLSULFIDE = 23, 'Dimethylsulfid', 'Dimethylsulfide', 'C2H6S', ''
    BUTYL_ALCOHOL = 24, '1-Butanol', '2-Butanol butyl Alcohol', 'C4H10O', ''
    METHYLPROPANOL_2 = 25, '2-Methyl-1-propanol', '2-Methylpropanol', 'C4H10O', ''
    DIETHYL_ETHER = 26, 'Diethylether', 'Diethyl ether', 'C2H52O', ''
    NAPHTHALENE = 27, 'Naphthalin', 'Naphthalene', 'C10H8', ''
    PHENYLCYCLOHEXENE_4 = 28, '4-Phenylcyclohexene', '4-Phenylcyclohexene', 'C12H14', ''
    LIMONENE = 29, 'Limonenen', 'Limonene', 'C10H16', ''
    TRICHLOROETHYLENE = 30, 'Trichlorethen', 'Trichloroethylene', 'C2HCl3', ''
    ISOVALERIC = 31, 'Isovaleriansäure', 'Isovaleric acid', 'C5H10O2', ''
    INDOLE = 32, 'Indol', 'Indole', 'C8H7N', ''
    CADAVERINE = 33, 'Cadaverin', 'Cadaverine', 'C5H14N2', ''
    PUTRESCINE = 34, 'Putrescin', 'Putrescine', 'C4H12N2', ''
    CAPROIC_ACID = 35, 'Capronsäure', 'Caproic acid', 'C6H12O2', ''
    OZONE = 255, 'Ozon', 'Ozone', 'O3', ''


class _AirQualitySensor(EEP):

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        concentration:float = msg.data[0] * 255 + msg.data[1]
        
        voc_substance_type = None
        for t in VOC_SubstancesType:
            if t.index == int(msg.data[2]):
                voc_substance_type = t

        learn_button = (msg.data[3] & 0x08) >> 3

        if (msg.data[3] & 0x04) == 0:
            voc_substance_unit = VOC_Unit.PPB
        else:
            voc_substance_unit = VOC_Unit.MGM3

        multi:float = 0.01 * 10** int(msg.data[3] & 0x3)
        
        return cls(concentration*multi, voc_substance_type, voc_substance_unit, learn_button)

    def encode_message(self, address):
        raise Exception("NOT IMPLEMENTED!")

    def __init__(self, concentration:float=0, voc_type:VOC_SubstancesType=VOC_SubstancesType.VOCT_TOTAL, voc_unit:VOC_Unit=VOC_Unit.PPB, learn_button:int=1):
        self._concentration = concentration
        self._voc_type = voc_type
        self._voc_unit = voc_unit
        self._learn_button = learn_button
        
    @property
    def concentration(self):
        return self._concentration

    @property
    def voc_type(self) -> VOC_SubstancesType:
        return self._voc_type
    
    @property
    def voc_unit(self) -> VOC_Unit:
        return self._voc_unit
    
    @property
    def concentration(self) -> float:
        return self._concentration

class A5_09_0C(_AirQualitySensor):
    """Air quality sensor"""

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

class _TempControl(EEP):
    max_cur_temp:float = 40
    min_des_temp:float = 8
    max_des_temp:float = 30
    usr:float = 255.0 # unscaled range 

    @classmethod
    def decode_message(cls, msg):
        if msg.org == 0x07:

            
            # reversed range (from 40° to 0°)
            current_temp = ((cls.usr - msg.data[2]) / cls.usr) * cls.max_cur_temp
            # range from 8° to 30°
            target_temp = (msg.data[1] / cls.usr) * (cls.max_des_temp - cls.min_des_temp)

            return cls(target_temp, current_temp)
        else:
            raise WrongOrgError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])

        # reversed range (from 40° to 0°)
        data[2] = int((self.max_cur_temp - self.current_temperature) / self.max_cur_temp * self.usr)
        # range from 8° to 30°
        data[1] = int(self.target_temperature / (self.max_des_temp - self.min_des_temp) * self.usr)
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)
    
    @property
    def target_temperature(self):
        return self._target_temp
    
    @property
    def current_temperature(self):
        return self._current_temp
    
    def __init__(self, target_temp:float=0, current_temp:float=0):
        self._target_temp = target_temp
        self._current_temp = current_temp


class A5_10_03(_TempControl):
    """Thermostat - current and desired temperature"""

class _HeatingCooling(EEP):
    min_temp:float = 0
    max_temp:float = 40
    usr:float = 255.0 # unscaled range 

    class ControllerPriority(DefaultEnum):
        ## TT = Target Temperature
        ## CT = Current Temperature
        AUTO = (1, 0x0E, 'Auto')                      # 00-TT-00-0E   no Priority (thermostat and controller have same prio)
        HOME_AUTOMATION = (2, 0x08, 'Home Assistant') # 00-TT-00-08   only values from softare controller, registered in actuator, are considered 
        THERMOSTAT = (3, 0x0E, 'Thermostat')          # 00-00-00-0E   only values from thermostat, registered in actuator, are considered (disables softeare controller)
        LIMIT = (4, 0x0A, 'Limited Thermostat Range (±3°K)') # 00-TT-00-0A   Controller defines target temperature and thermostat can change it in a range of -3 to + 3 degree
        ACTUATOR_ACK = (5, 0x0F, 'Actuator Response') # 00-TT-CT-0F

        # DB0.1 = 1: no Prio [0E]
        # DB0.1 = 0: Prio   [0A,08]
        # DB0.2 = 1: limits thermostat range to +/-3°K [0A]

    class HeaterMode(Enum):
        NORMAL = 0x70                       # normal mode
        STAND_BY_2_DEGREES = 0x30           # -2°K degree off-set mode              
        NIGHT_SET_BACK_4_DEGREES = 0x50     # night set back (-4°K)
        OFF = 0x10                          # Off
        UNKNOWN = 0x00

    @classmethod
    def decode_message(cls, msg):
        if msg.org == 0x07:

            priority = cls.ControllerPriority.find_by_code(msg.data[3])
            # reversed range (from 40° to 0°)
            current_temp = ((cls.usr - msg.data[2]) / cls.usr) * cls.max_temp
            target_temp = (msg.data[1] / cls.usr) * cls.max_temp
            
            try:
                mode = cls.HeaterMode(msg.data[0])
                if mode.value == 0 and target_temp == 0:
                    mode = cls.HeaterMode.OFF
            except:
                mode = cls.HeaterMode.UNKNOWN

            return cls(mode, target_temp, current_temp, priority)
        else:
            raise WrongOrgError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])

        data[3] = self.priority.code

        # reversed range (from 40° to 0°)
        data[2] = int((self.max_temp - self.current_temperature) / self.max_temp * self.usr)

        data[1] = int(self.target_temperature / self.max_temp * self.usr)
        
        data[0] = self.mode.value
        
        status = 0x80

        return Regular4BSMessage(address, status, data, True)

    @property
    def mode(self) -> HeaterMode:
        return self._mode
    
    @property
    def target_temperature(self):
        return self._target_temp
    
    @property
    def current_temperature(self):
        return self._current_temp
    
    @property
    def priority(self) -> ControllerPriority:
        return self._priority

    def __init__(self, mode:HeaterMode=HeaterMode.NORMAL, target_temp:float=40, current_temp:float=min_temp, priority: ControllerPriority=ControllerPriority.AUTO):
        self._mode  = mode
        self._target_temp = target_temp
        self._current_temp = current_temp
        self._priority = priority


class A5_10_06(_HeatingCooling):
    """Heating and Cooling"""

class _HeatingCoolingHumidity(EEP):
    temp_min = 0.0
    temp_max = 40.0
    usr = 250.0 # unscaled range 
    usr_tt = 255.0 # unscaled range for target temperature

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        target_temperature = (msg.data[0] / cls.usr) * (cls.temp_max - cls.temp_min) + cls.temp_min
        # 0 .. 100%
        humidity = (msg.data[1] / cls.usr) * 100.0
        # -20°C .. +60°C
        current_temperature = (msg.data[2] / cls.usr) * (cls.temp_max - cls.temp_min) + cls.temp_min
        
        return cls(current_temperature, target_temperature, humidity)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        data[0] = int((self._target_temperature / (self.temp_max - self.temp_min)) * self.usr)
        data[1] = int((self._humidity / 100.0) * self.usr)
        data[2] = int((self._current_temperature / (self.temp_max - self.temp_min)) * self.usr)
        data[3] = 8 # data telegram
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def current_temperature(self):
        return self._current_temperature
    
    @property
    def target_temperature(self):
        return self._target_temperature
    
    @property
    def humidity(self):
        return self._humidity
    
    def __init__(self, current_temperature:int=0, target_temperature:int=0, humidity:int=0):
        self._current_temperature = current_temperature
        self._target_temperature = target_temperature
        self._humidity = humidity


class A5_10_12(_HeatingCoolingHumidity):
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
            data[1] = int(((self.temperature - self.temp_min) / (self.temp_max - self.temp_min)) * 255.0)
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

    def __init__(self, identifier:int=1, learn_button:int=1,
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
    temp_min = -20.0
    temp_max = 60.0
    usr = 250.0 # unscaled range 

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        learn_button = (msg.data[3] & 0x08) >> 3

        # 0 .. 100%
        humidity = (msg.data[1] / cls.usr) * 100.0
        # -20°C .. +60°C
        temperature = ((msg.data[2] / cls.usr) * (cls.temp_max - cls.temp_min)) + cls.temp_min
        

        return cls(temperature,humidity,learn_button)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        data[0] = 0x00
        data[1] = int((self.humidity / 100.0) * self.usr)
        data[2] = int(((self.current_temperature - self.temp_min) / (self.temp_max - self.temp_min)) * self.usr)
        data[3] = (self.learn_button << 3)
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def current_temperature(self):
        return self._temperature
    
    @property
    def humidity(self):
        return self._humidity
    
    @property
    def learn_button(self):
        return self._learn_button
    
    def __init__(self, temperature:int=0, humidity:int=0, learn_button:int=1):
        self._temperature = temperature
        self._humidity = humidity
        self._learn_button = learn_button

class A5_04_02(_TemperatureAndHumiditySensor):
    """Temperature and Humidity Sensor"""


class _TemperatureAndHumiditySensor2(EEP):
    temp_min = 0.0
    temp_max = 40.0
    usr = 250.0 # unscaled range 

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        learn_button = (msg.data[3] & 0x08) >> 3

        temp_availability = (msg.data[3] & 0x02) >> 1

        # 0 .. 100%
        humidity = (msg.data[1] / cls.usr) * 100.0
        # -20°C .. +60°C
        temperature = (msg.data[2] / cls.usr) * cls.temp_max
        
        return cls(temperature, humidity, learn_button, temp_availability)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        data[0] = 0x00
        data[1] = int((self.humidity / 100.0) * self.usr)
        data[2] = int((self.current_temperature / self.temp_max) * self.usr)
        data[3] = (self.learn_button << 3) | (self.temp_availability << 1)
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def current_temperature(self):
        return self._temperature
    
    @property
    def humidity(self):
        return self._humidity
    
    @property
    def temp_availability(self):
        return self._temp_availability
    
    @property
    def learn_button(self):
        return self._learn_button

    def __init__(self, temperature:int=0, humidity:int=0, learn_button:int=1, temp_availability:int=1):
        self._temperature = temperature
        self._humidity = humidity
        self._learn_button = learn_button
        self._temp_availability = temp_availability

class A5_04_01(_TemperatureAndHumiditySensor2):
    """Temperature and Humidity Sensor"""


class _TemperatureAndHumiditySensor3(EEP):
    temp_min = -20.0
    temp_max = 60.0
    usr = 255.0 # unscaled range 

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        learn_button = (msg.data[3] & 0x08) >> 3

        telegram_type = (msg.data[3] & 0x01)

        # 0 .. 100%
        humidity = (msg.data[0] / cls.usr) * 100.0
        # -20°C .. +60°C
        raw_temp = msg.data[1] * 265 + msg.data[2]
        temperature = ((raw_temp / 1024) * (cls.temp_max - cls.temp_min)) + cls.temp_min

        return cls(temperature,humidity,learn_button, telegram_type)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        data[0] = 0x00
        data[1] = int((self.humidity / 100.0) * self.usr)
        data[2] = int((self.current_temperature / (self.temp_max - self.temp_min)) * self.usr)
        data[3] = (self.learn_button << 3) + self.telegram_type
        
        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    @property
    def current_temperature(self):
        return self._temperature
    
    @property
    def humidity(self):
        return self._humidity
    
    @property
    def learn_button(self):
        return self._learn_button
    
    # 0 = heartbeat, 1 = event triggered
    @property
    def telegram_type(self):
        return self._telegram_type
    
    def __init__(self, temperature:int=-20, humidity:int=0, learn_button:int=1, telegram_type:int=1):
        self._temperature = temperature
        self._humidity = humidity
        self._learn_button = learn_button
        self._telegram_type = telegram_type

class A5_04_03(_TemperatureAndHumiditySensor3):
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
        if self.state is not None:
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


# ======================================
# MARK: - Occupancy Sensor
# ======================================
    
class _OccupancySensor(EEP):

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        
        support_voltage = msg.data[0] / 250.0 * 5.0
        
        pir_status = msg.data[2]
        pir_status_on = pir_status >= 128
        
        learn_button = (msg.data[3] & 0x08) >> 3
        support_volrage_availability = msg.data[3] & 0x01

        return cls(support_voltage, pir_status, pir_status_on, learn_button, support_volrage_availability)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[0] = int( self.support_voltage * 255.0 / 5.0 )
        data[1] = 0
        data[2] = self._pir_status
        data[3] = (self.learn_button << 3) | self._support_volrage_availability

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)

    @property
    def support_volrage_availability(self):
        return self._support_volrage_availability

    @property
    def support_voltage(self):
        return self._support_voltage

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def pir_status(self):
        return self._pir_status
    
    @property
    def pir_status_on(self):
        return self._pir_status_on

    def __init__(self, support_voltage, pir_status, pir_status_on, learn_button, support_volrage_availability):
        self._support_voltage = support_voltage
        self._pir_status = pir_status
        self._pir_status_on = pir_status_on
        self._learn_button = learn_button
        self._support_volrage_availability = support_volrage_availability

class A5_07_01(_OccupancySensor):
    """Occupancy Sensor"""

class _BrightnessTwilightSensor(EEP):
    # ORG = 0x07
    # Data_byte3 = Brightness 0..100 lux (0..100)
    # (only if DB2 = 0x00)
    # Data_byte2 = Brightness 300..30.000 lux (0..255)
    # Data_byte1 = -
    # Data_byte0 = 0x0F
    # Lerntelegramm: 0x18080D87

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        twilight = msg.data[0]
        day_light = msg.data[1] / 255.0 * (30000 - 300) + 300
        illumination = twilight if msg.data[1] == 0 else day_light

        return cls(twilight, day_light, illumination)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[0] = self.twilight
        data[1] = max(0, min(255, int( (self.day_light - 300) / (30000 - 300) * 255 )))
        data[2] = 0x00
        data[3] = 0x0F

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)
    
    @property
    def day_light(self):
        return self._day_light
    
    @property
    def twilight(self):
        return self._twilight
    
    @property
    def illumination(self):
        return self._illumination

    def __init__(self, twilight:int=0, day_light:int=300, illumination:int=300):
        self._twilight = twilight
        self._day_light = day_light
        self._illumination = illumination

class A5_06_01(_BrightnessTwilightSensor):
    """Brightness Twilight Sensor"""

class _DigitalInputAndBattery(EEP):
    """Digital Input regarding A5-30-01"""

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        battery_status = msg.data[1]
        contact_status = msg.data[2]
        learn_button = (msg.data[3] & 0x08) >> 3

        return cls(battery_status, contact_status, learn_button)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[0] = 0
        data[1] = self.battery_status
        data[2] = self.contact_status
        data[3] = self.learn_button

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)
    
    @property
    def low_battery(self):
        return self._low_battery

    @property
    def contact_closed(self):
        return self._contact_closed

    @property
    def battery_status(self):
        return self._battery_status
    
    @property
    def contact_status(self):
        return self._contact_status
    
    @property
    def learn_button(self):
        return self._learn_button

    def __init__(self, battery_status, contact_status, learn_button):
        self._battery_status = battery_status
        self._contact_status = contact_status
        self._low_battery = self._battery_status < 121
        self._contact_closed = self._contact_status < 196
        self._learn_button = learn_button

class A5_30_01(_DigitalInputAndBattery):
    """Digital Input with battery status"""

class _DigitalInputsAndTemperature(EEP):
    """4 Digital Inputs and Temperature"""

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        temperature = msg.data[1] / 255 * 40
        
        digital_input_0 = msg.data[2] & 0x01
        digital_input_1 = (msg.data[2] & 0x02) >> 1
        digital_input_2 = (msg.data[2] & 0x04) >> 2
        digital_input_3 = (msg.data[2] & 0x08) >> 3
        status_of_wake = (msg.data[2] & 0x10) >> 4

        learn_button = (msg.data[3] & 0x08) >> 3

        return cls(temperature, digital_input_0, digital_input_1, digital_input_2, digital_input_3, status_of_wake, learn_button)
    

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[1] = int(self._temperature / 40 * 255)

        data[2] += self.digital_input_0
        data[2] += self.digital_input_1 << 1
        data[2] += self.digital_input_2 << 2
        data[2] += self.digital_input_3 << 3
        data[2] += self.status_of_wake << 4

        data[3] = self.learn_button

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)
    
    @property
    def digital_input_0(self):
        return self._digital_input_0
    
    @property
    def digital_input_1(self):
        return self._digital_input_1
    
    @property
    def digital_input_2(self):
        return self._digital_input_2
    
    @property
    def digital_input_3(self):
        return self._digital_input_3
    
    @property
    def status_of_wake(self):
        return self._status_of_wake
    
    @property
    def learn_button(self):
        return self._learn_button

    def __init__(self, temperature, digital_input_0, digital_input_1, digital_input_2, digital_input_3, status_of_wake, learn_button):
        self._temperature = temperature
        self._digital_input_0 = digital_input_0
        self._digital_input_1 = digital_input_1
        self._digital_input_2 = digital_input_2
        self._digital_input_3 = digital_input_3
        self._status_of_wake = status_of_wake
        self._learn_button = learn_button

class A5_30_03(_DigitalInputsAndTemperature):
    """Digital Inputs"""