from collections import namedtuple
from enum import Enum

from eltakobus.util import DefaultEnum
from .error import NotImplementedError, WrongOrgError
from .message import RPSMessage, Regular1BSMessage, Regular4BSMessage
import re


class EEPFieldMetadata(namedtuple(
        "EEPFieldMetadataBase",
        "name description unit value_range values data_type")):
    """Metadata describing one decoded/encoded EEP value.

    ``value_range`` describes the physical or logical value exposed by the
    Python property, not the raw byte range on the wire. ``values`` is useful
    for enumerations and bit fields. The metadata is descriptive; encoding
    and decoding continue to be implemented by the EEP classes themselves.
    """

    __slots__ = ()

    def __new__(cls, name, description="", unit=None, value_range=None,
                values=None, data_type="number"):
        return super(EEPFieldMetadata, cls).__new__(
            cls, name, description, unit, value_range, values, data_type)

    def as_dict(self) -> dict:
        result = {
            "name": self.name,
            "description": self.description,
            "unit": self.unit,
            "value_range": self.value_range,
            "values": dict(self.values) if self.values is not None else None,
            "data_type": self.data_type,
        }
        return result


class EEPMetadata(namedtuple(
        "EEPMetadataBase", "eep name description org fields")):
    """Human- and machine-readable description of an EEP profile."""

    __slots__ = ()

    def __new__(cls, eep, name, description, org, fields=()):
        return super(EEPMetadata, cls).__new__(
            cls, eep, name, description, org, fields)

    def with_eep(self, eep):
        return self._replace(eep=eep)

    def field(self, name: str) -> EEPFieldMetadata:
        """Return metadata for *name* or raise ``KeyError``."""
        for field in self.fields:
            if field.name == name:
                return field
        raise KeyError(name)

    def as_dict(self) -> dict:
        """Return a JSON-friendly representation of this metadata."""
        return {
            "eep": self.eep,
            "name": self.name,
            "description": self.description,
            "org": self.org,
            "fields": [field.as_dict() for field in self.fields],
        }

class EEP:
    """Base class for decoded EEP telegrams.

    Every concrete EEP below has a short, machine-readable description in
    ``metadata``.  Consumers should use ``get_metadata()`` for a compact
    summary of the telegram's purpose, fields, units and value ranges.
    """
    __sublasses_by_string = {}
    metadata = EEPMetadata(
        eep="",
        name="Unknown EEP",
        description="No metadata has been declared for this profile.",
        org=None,
    )

    @classmethod
    def decode_message(cls, msg):
        raise NotImplementedError

    def encode_message(self, address):
        raise NotImplementedError
    

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        
        if re.match("^([0-9a-zA-Z]{2})_([0-9a-zA-Z]{2})_([0-9a-zA-Z]{2})$", cls.__name__):
            cls.eep_string = cls.__name__.replace("_", "-")
            # Copy inherited metadata onto the concrete profile so callers
            # can use either ``Profile.metadata`` or ``Profile.get_metadata``.
            cls.metadata = cls.metadata.with_eep(cls.eep_string)
            cls.__sublasses_by_string[cls.eep_string] = cls

    @classmethod
    def get_metadata(cls) -> EEPMetadata:
        """Return structured metadata for this EEP class.

        Metadata is available both on concrete classes and on the result of
        :meth:`find`. The returned object always contains the concrete EEP
        identifier, including when the metadata is inherited from a shared
        implementation class.
        """
        return cls.metadata

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
    metadata = EEPMetadata("", "One-button switch", "A single-button RPS switch telegram.", 0x05, (
        EEPFieldMetadata("button_pushed", "Whether the button is pressed.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Two-rocker switch", "A two-part rocker switch using the RPS profile.", 0x05, (
        EEPFieldMetadata("rocker_first_action", "Action of the first rocker.", value_range=(0, 7)),
        EEPFieldMetadata("energy_bow", "Energy bow flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("rocker_second_action", "Action of the second rocker.", value_range=(0, 7)),
        EEPFieldMetadata("second_action", "Second action flag.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Window handle", "Window handle movement and position telegram.", 0x05, (
        EEPFieldMetadata("movement", "Raw four-bit movement code.", value_range=(0, 15), data_type="integer"),
        EEPFieldMetadata("handle_position", "Interpreted handle position.", data_type="enum",
                         values={0: "closed", 1: "open", 2: "tilt"}),
    ))

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
    metadata = EEPMetadata("", "Single input contact", "A one-bit contact input with learn-button state.", 0x06, (
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("contact", "Contact state.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Light, temperature and occupancy sensor",
        "Sensor telegram containing supply voltage, illumination, temperature and PIR state.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Sensor supply voltage.", "V", (0.0, 5.1)),
        EEPFieldMetadata("illumination", "Measured illumination.", "lx", (0.0, 510.0)),
        EEPFieldMetadata("temperature", "Measured temperature.", "°C", (0.0, 51.0)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("pir_status", "Raw PIR status.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("occupancy_button", "Occupancy button flag.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Air quality sensor", "VOC concentration with substance type and unit.", 0x07, (
        EEPFieldMetadata("concentration", "VOC concentration.", value_range=(0.0, 167769.6)),
        EEPFieldMetadata("voc_type", "Measured VOC substance.", data_type="enum"),
        EEPFieldMetadata("voc_unit", "Concentration unit.", data_type="enum", values={0: "ppb", 1: "µg/m3"}),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))

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

class _CO2TemperatureHumiditySensor(EEP):
    metadata = EEPMetadata("", "CO2, temperature and humidity sensor",
        "Indoor-air sensor telegram with carbon dioxide, temperature and relative humidity.", 0x07, (
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("co2", "Carbon dioxide concentration.", "ppm", (0, 2550)),
        EEPFieldMetadata("temperature", "Measured temperature.", "°C", (0.0, 51.0)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError

        # Data_byte3 = Humidity 0..100% (0..200)
        humidity = (msg.data[0] / 200.0) * 100.0

        # Data_byte2 = CO2 value 0..2550ppm (0..255)
        co2 = msg.data[1] * 10

        # Data_byte1 = Temperature 0..51°C (0..255)
        temperature = (msg.data[2] / 255.0) * 51.0

        learn_button = (msg.data[3] & 0x08) >> 3

        return cls(humidity=humidity, co2=co2, temperature=temperature, learn_button=learn_button)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])

        hum_val = int((self.humidity / 100.0) * 200.0)
        data[0] = min(max(hum_val, 0), 200)

        co2_val = int(self.co2 / 10.0)
        data[1] = min(max(co2_val, 0), 255)

        temp_val = int((self.temperature / 51.0) * 255.0)
        data[2] = min(max(temp_val, 0), 255)

        data[3] = (self.learn_button << 3)

        status = 0x00

        return Regular4BSMessage(address, status, data, True)

    def __init__(self, humidity:float=0, co2:int=0, temperature:float=0, learn_button:int=1):
        self._humidity = humidity
        self._co2 = co2
        self._temperature = temperature
        self._learn_button = learn_button

    @property
    def humidity(self):
        return self._humidity

    @property
    def co2(self):
        return self._co2

    @property
    def temperature(self):
        return self._temperature
    
    @property
    def current_temperature(self):
        return self._temperature

    @property
    def learn_button(self):
        return self._learn_button
    
class A5_09_04(_CO2TemperatureHumiditySensor):
    """CO2, Temperature and Humidity Sensor"""


class _EltakoVOCSensor(EEP):
    """Eltako FLT58 VOC telegram (the Eltako A5-09-05 variant)."""
    metadata = EEPMetadata("", "VOC sensor",
        "Eltako VOC concentration from 0 to 500 (A5-09-05 telegram).", 0x07, (
        EEPFieldMetadata("concentration", "VOC concentration.", None, (0.0, 500.0)),
        EEPFieldMetadata("profile_marker", "Eltako profile marker (DB1/DB0).", data_type="integer", value_range=(0, 255)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        raw = (msg.data[0] << 8) | msg.data[1]
        concentration = raw / 65535.0 * 500.0
        return cls(concentration, msg.data[2], msg.data[3])

    def encode_message(self, address):
        if not 0.0 <= self.concentration <= 500.0:
            raise ValueError("VOC concentration must be between 0 and 500")
        raw = int(self.concentration / 500.0 * 65535.0)
        data = bytearray((raw >> 8, raw & 0xFF, self.profile_marker, self.profile_type))
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def concentration(self):
        return self._concentration

    @property
    def profile_marker(self):
        return self._profile_marker

    @property
    def profile_type(self):
        return self._profile_type

    def __init__(self, concentration=0.0, profile_marker=0x1B, profile_type=0x0A):
        self._concentration = concentration
        self._profile_marker = profile_marker
        self._profile_type = profile_type


class A5_09_05(_EltakoVOCSensor):
    """Eltako VOC sensor telegram used by FLT58."""

# ======================================
# MARK: - Central Command
# ======================================

class _CentralCommand(EEP):
    metadata = EEPMetadata("", "Central command", "Central switching or dimming command.", 0x07, (
        EEPFieldMetadata("command", "Command variant: switching or dimming.", data_type="enum", values={1: "switching", 2: "dimming"}),
        EEPFieldMetadata("switching", "Switching parameters: time, switch, delay/duration and optional actuator lock.", data_type="object"),
        EEPFieldMetadata("dimming", "Dimming command parameters.", data_type="object"),
    ))
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
    """Parameters for A5-38-08 command 0x01 (switching).

    ``lock`` requests an actuator lock.  With ``lock=1`` the actuator accepts
    no other commands until the timer expires; ``time=0`` means an unlimited
    lock.  An explicit unlock command is the exception and remains accepted.
    The same timer is used as a delay or switching duration according to
    ``delay_or_duration`` when the command is not a lock operation.
    """
    @property
    def time(self):
        return self._time

    @property
    def learn_button(self):
        return self._learn_button

    @property
    def lock(self):
        """Whether the target actuator shall ignore commands temporarily."""
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
    """Parameters for A5-38-08 command 0x02 (absolute dimming)."""
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
    """Central switching/dimming command for gateway-to-actuator control.

    Command ``0x01`` switches an actuator and can lock it; command ``0x02``
    sets a dimming value and ramp time.  This EEP represents commands, not a
    guaranteed feedback/status telegram.
    """

# ======================================
# MARK: - Eltako Gateway Switching
# ======================================

class _EltakoSwitchingCommand(EEP):
    metadata = EEPMetadata("", "Eltako switching command", "RPS switching command used by an Eltako gateway.", 0x05, (
        EEPFieldMetadata("state", "Requested switch state.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Thermostat", "Current and desired temperature control telegram.", 0x07, (
        EEPFieldMetadata("target_temperature", "Desired temperature.", "°C", (8.0, 30.0)),
        EEPFieldMetadata("current_temperature", "Current temperature.", "°C", (0.0, 40.0)),
    ))
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
            target_temp = cls.min_des_temp + (msg.data[1] / cls.usr) * (cls.max_des_temp - cls.min_des_temp)

            return cls(target_temp, current_temp)
        else:
            raise WrongOrgError

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])

        # reversed range (from 40° to 0°)
        data[2] = int((self.max_cur_temp - self.current_temperature) / self.max_cur_temp * self.usr)
        # range from 8° to 30°
        data[1] = int((self.target_temperature - self.min_des_temp) / (self.max_des_temp - self.min_des_temp) * self.usr)
        
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
    metadata = EEPMetadata("", "Heating and cooling controller",
        "Temperature controller telegram with mode and controller priority.", 0x07, (
        EEPFieldMetadata("mode", "Heating/cooling operating mode.", data_type="enum"),
        EEPFieldMetadata("target_temperature", "Desired temperature.", "°C", (0.0, 40.0)),
        EEPFieldMetadata("current_temperature", "Current temperature.", "°C", (0.0, 40.0)),
        EEPFieldMetadata("priority", "Controller priority.", data_type="enum"),
    ))
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
        if self._mode is None or self._mode == 0:
            return self.HeaterMode.NORMAL
        return self._mode
    
    @property
    def target_temperature(self):
        return self._target_temp
    
    @property
    def current_temperature(self):
        return self._current_temp
    
    @property
    def priority(self) -> ControllerPriority:
        if self._priority is None or self._priority == 0:
            return self.ControllerPriority.AUTO
        return self._priority

    def __init__(self, mode:HeaterMode=HeaterMode.NORMAL, target_temp:float=40, current_temp:float=min_temp, priority: ControllerPriority=ControllerPriority.AUTO):
        self._mode  = mode
        self._target_temp = target_temp
        self._current_temp = current_temp
        self._priority = priority


class A5_10_06(_HeatingCooling):
    """Heating and Cooling"""

class _HeatingCoolingHumidity(EEP):
    metadata = EEPMetadata("", "Heating, cooling and humidity controller",
        "Temperature and humidity values for heating/cooling control.", 0x07, (
        EEPFieldMetadata("current_temperature", "Current temperature.", "°C"),
        EEPFieldMetadata("target_temperature", "Desired temperature.", "°C"),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
    ))
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


class _ValveAndTemperatureSensor(EEP):
    """Eltako FKS-H A5-20-04 status telegram."""
    metadata = EEPMetadata("", "Valve and temperature sensor",
        "Valve position with supply/target or error-dependent temperature data.", 0x07, (
        EEPFieldMetadata("valve_position", "Valve position.", "%", (0.0, 100.0)),
        EEPFieldMetadata("temperature", "Temperature selected by the status marker.", "°C"),
        EEPFieldMetadata("status", "Eltako status marker (DB0).", data_type="integer", value_range=(0, 255)),
        EEPFieldMetadata("battery_empty", "Battery-empty error status.", data_type="boolean", value_range=(0, 1)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        status = msg.data[3]
        valve_position = msg.data[0] / 255.0 * 100.0
        if status == 0x08:
            temperature = 20.0 + msg.data[1] / 255.0 * 60.0
        elif status == 0x0A:
            temperature = 10.0 + msg.data[1] / 255.0 * 20.0
        else:
            temperature = msg.data[1]
        return cls(valve_position, temperature, status)

    def encode_message(self, address):
        if not 0.0 <= self.valve_position <= 100.0:
            raise ValueError("Valve position must be between 0 and 100 percent")
        if self.status == 0x08:
            raw_temperature = (self.temperature - 20.0) / 60.0 * 255.0
        elif self.status == 0x0A:
            raw_temperature = (self.temperature - 10.0) / 20.0 * 255.0
        else:
            raw_temperature = self.temperature
        if not 0.0 <= raw_temperature <= 255.0:
            raise ValueError("Temperature is outside the range for the selected status")
        data = bytearray((int(self.valve_position / 100.0 * 255.0), int(raw_temperature), 0, self.status))
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def valve_position(self):
        return self._valve_position

    @property
    def temperature(self):
        return self._temperature

    @property
    def status(self):
        return self._status

    @property
    def battery_empty(self):
        return self.status == 0x09 and self.temperature == 0x12

    def __init__(self, valve_position=0.0, temperature=0.0, status=0x08):
        self._valve_position = valve_position
        self._temperature = temperature
        self._status = status


class A5_20_04(_ValveAndTemperatureSensor):
    """Eltako FKS-H valve and temperature telegram."""

# ======================================
# MARK: - Weather station
# ======================================

class _WeatherStation(EEP):
    metadata = EEPMetadata("", "Weather station",
        "Weather station telegram with wind, temperature, light and rain data.", 0x07, (
        EEPFieldMetadata("identifier", "Weather telegram variant.", data_type="enum", values={1: "weather", 2: "sun position"}),
        EEPFieldMetadata("dawn_sensor", "Dawn/light sensor value.", value_range=(0.0, 999.0)),
        EEPFieldMetadata("temperature", "Measured temperature.", "°C"),
        EEPFieldMetadata("wind_speed", "Wind speed.", "m/s", (0.0, 70.0)),
        EEPFieldMetadata("day_night", "Day/night flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("rain_indication", "Rain indication.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("sun_west", "West-facing sunlight.", "%", (0.0, 150.0)),
        EEPFieldMetadata("sun_south", "South-facing sunlight.", "%", (0.0, 150.0)),
        EEPFieldMetadata("sun_east", "East-facing sunlight.", "%", (0.0, 150.0)),
        EEPFieldMetadata("hemisphere", "Hemisphere flag.", data_type="boolean", value_range=(0, 1)),
    ))
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
        data[3] = (self.identifier & 0x0F) << 4
        
        if self.identifier == 0x01:
            data[3] = data[3] | (self.rain_indication << 1)
            data[3] = data[3] | (self.day_night << 2)
            data[3] = data[3] | (self.learn_button << 3)
            data[2] = int((self.wind_speed / 70.0) * 255.0)
            data[1] = int(((self.temperature - self.temp_min) / (self.temp_max - self.temp_min)) * 255.0)
            data[0] = int((self.dawn_sensor / 999.0) * 255.0)
        elif self.identifier == 0x02:
            data[3] = data[3] | (self.hemisphere << 2)
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


class A5_13_02(_WeatherStation):
    """Sun-position telegram with west, south and east light sensors."""
    metadata = EEPMetadata("", "Sun-position sensor",
        "Three directional sunlight measurements and hemisphere indication.", 0x07, (
        EEPFieldMetadata("sun_west", "West-facing sunlight.", "klx", (0.0, 150.0)),
        EEPFieldMetadata("sun_south", "South-facing sunlight.", "klx", (0.0, 150.0)),
        EEPFieldMetadata("sun_east", "East-facing sunlight.", "klx", (0.0, 150.0)),
        EEPFieldMetadata("hemisphere", "Hemisphere flag (0 north, 1 south).", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn bit.", data_type="boolean", value_range=(0, 1)),
    ))


class A5_13_04(EEP):
    """Clock and weekday telegram used by Eltako time transmitters."""
    metadata = EEPMetadata("", "Time and weekday",
        "Weekday, 24-hour/12-hour clock and teach-in indicator.", 0x07, (
        EEPFieldMetadata("weekday", "Weekday, Monday=1 through Sunday=7.", data_type="integer", value_range=(1, 7)),
        EEPFieldMetadata("hour", "Hour as transmitted on the wire.", "h", (0, 23), data_type="integer"),
        EEPFieldMetadata("minute", "Minute.", "min", (0, 59), data_type="integer"),
        EEPFieldMetadata("second", "Second.", "s", (0, 59), data_type="integer"),
        EEPFieldMetadata("time_format", "Clock format.", data_type="enum", values={0: "24h", 1: "12h"}),
        EEPFieldMetadata("am_pm", "AM/PM bit for 12-hour display.", data_type="enum", values={0: "AM", 1: "PM"}),
        EEPFieldMetadata("learn_button", "Learn bit.", data_type="boolean", value_range=(0, 1)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        identifier = (msg.data[3] >> 4) & 0x0F
        if identifier != 0x04:
            raise NotImplementedError
        return cls(
            weekday=(msg.data[0] >> 5) & 0x07,
            hour=msg.data[0] & 0x1F,
            minute=msg.data[1] & 0x3F,
            second=msg.data[2] & 0x3F,
            learn_button=(msg.data[3] >> 3) & 1,
            time_format=(msg.data[3] >> 2) & 1,
            am_pm=(msg.data[3] >> 1) & 1,
        )

    def encode_message(self, address):
        if not 1 <= self.weekday <= 7 or not 0 <= self.hour <= 23:
            raise ValueError("weekday/hour is outside the A5-13-04 range")
        if not 0 <= self.minute <= 59 or not 0 <= self.second <= 59:
            raise ValueError("minute/second is outside the A5-13-04 range")
        data = bytes(((self.weekday << 5) | self.hour, self.minute,
                      self.second, 0x40 | (self.learn_button << 3) |
                      (self.time_format << 2) | (self.am_pm << 1)))
        return Regular4BSMessage(address, 0, data, True)

    def __init__(self, weekday=1, hour=0, minute=0, second=0,
                 learn_button=1, time_format=0, am_pm=0):
        self.weekday = weekday
        self.hour = hour
        self.minute = minute
        self.second = second
        self.learn_button = learn_button
        self.time_format = time_format
        self.am_pm = am_pm

# ======================================
# MARK: -  temperature + humidity sensor
# ======================================
class _TemperatureAndHumiditySensor(EEP):
    metadata = EEPMetadata("", "Temperature and humidity sensor",
        "Temperature and relative humidity sensor with a -20 to 60 degree range.", 0x07, (
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (-20.0, 60.0)),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Temperature and humidity sensor (0 to 40 °C)",
        "Temperature and relative humidity sensor with temperature availability.", 0x07, (
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (0.0, 40.0)),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("temp_availability", "Temperature value available.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))
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
    metadata = EEPMetadata("", "Temperature and humidity sensor (extended)",
        "Temperature and relative humidity sensor with heartbeat/event telegram type.", 0x07, (
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (-20.0, 60.0)),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("telegram_type", "Heartbeat or event telegram.", data_type="enum", values={0: "heartbeat", 1: "event"}),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))
    temp_min = -20.0
    temp_max = 60.0
    usr = 255.0 # unscaled range 

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        learn_button = (msg.data[3] & 0x08) >> 3

        telegram_type = (msg.data[3] & 0x01)

        # A5-04-03 uses DB3 for humidity and DB2.1..DB1.0 for the
        # 10-bit temperature value (DB2 contains the two MSBs).
        humidity = (msg.data[0] / cls.usr) * 100.0
        raw_temp = ((msg.data[1] & 0x03) << 8) | msg.data[2]
        temperature = ((raw_temp / 1023.0) * (cls.temp_max - cls.temp_min)) + cls.temp_min

        return cls(temperature,humidity,learn_button, telegram_type)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        if not 0.0 <= self.humidity <= 100.0:
            raise ValueError("Humidity must be between 0 and 100 %")
        if not self.temp_min <= self.current_temperature <= self.temp_max:
            raise ValueError(
                f"Temperature must be between {self.temp_min} and {self.temp_max} °C")
        raw_temp = round((self.current_temperature - self.temp_min)
                         / (self.temp_max - self.temp_min) * 1023)
        data[0] = int((self.humidity / 100.0) * self.usr)
        data[1] = (raw_temp >> 8) & 0x03
        data[2] = raw_temp & 0xFF
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


class _TemperatureSensor(EEP):
    """Pure temperature sensor using the A5-02 linear temperature encoding."""
    metadata = EEPMetadata("", "Temperature sensor",
        "Pure temperature sensor with a 0 to 40 degree Celsius range.", 0x07, (
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (0.0, 40.0)),
        EEPFieldMetadata("profile_marker", "Eltako profile marker (DB0).", value_range=(0, 255), data_type="integer"),
    ))
    temp_min = 0.0
    temp_max = 40.0
    usr = 255.0

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError

        temperature = cls.temp_min + ((cls.usr - msg.data[2]) / cls.usr) * (cls.temp_max - cls.temp_min)
        return cls(temperature, msg.data[3])

    def encode_message(self, address):
        if not self.temp_min <= self.current_temperature <= self.temp_max:
            raise ValueError(
                f"Temperature must be between {self.temp_min} and {self.temp_max} °C")

        data = bytearray(4)
        data[2] = int((self.temp_max - self.current_temperature)
                      / (self.temp_max - self.temp_min) * self.usr)
        data[3] = self.profile_marker
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def current_temperature(self):
        return self._temperature

    @property
    def profile_marker(self):
        return self._profile_marker

    def __init__(self, temperature: float = 0.0, profile_marker: int = 0x0F):
        self._temperature = temperature
        self._profile_marker = profile_marker


class A5_02_05(_TemperatureSensor):
    """Temperature Sensor, 0 to 40 °C (e.g. EnOcean STM 330)."""


# The A5-02 family uses the same 8-bit linear field (DB1), but each profile
# declares a different physical range.  Keep the concrete profile names
# available through ``EEP.find()`` instead of making callers duplicate this
# mapping themselves.
_A5_02_RANGES = {
    "A5_02_01": (-40.0, 0.0),
    "A5_02_02": (-30.0, 10.0),
    "A5_02_03": (-20.0, 20.0),
    "A5_02_04": (-10.0, 30.0),
    "A5_02_06": (10.0, 50.0),
    "A5_02_07": (20.0, 60.0),
    "A5_02_08": (30.0, 70.0),
    "A5_02_09": (40.0, 80.0),
    "A5_02_0A": (50.0, 90.0),
    "A5_02_0B": (60.0, 100.0),
    "A5_02_10": (-60.0, 20.0),
    "A5_02_11": (-50.0, 30.0),
    "A5_02_12": (-40.0, 40.0),
    "A5_02_13": (-30.0, 50.0),
    "A5_02_14": (-20.0, 60.0),
    "A5_02_15": (-10.0, 70.0),
    "A5_02_16": (0.0, 80.0),
    "A5_02_17": (10.0, 90.0),
    "A5_02_18": (20.0, 100.0),
    "A5_02_19": (30.0, 110.0),
    "A5_02_1A": (40.0, 120.0),
    "A5_02_1B": (50.0, 130.0),
}

for _profile_name, (_minimum, _maximum) in _A5_02_RANGES.items():
    globals()[_profile_name] = type(
        _profile_name,
        (_TemperatureSensor,),
        {
            "temp_min": _minimum,
            "temp_max": _maximum,
            "metadata": _TemperatureSensor.metadata._replace(
                fields=(EEPFieldMetadata(
                    "current_temperature", "Measured temperature.", "°C",
                    (_minimum, _maximum)),
                    _TemperatureSensor.metadata.field("profile_marker"))),
            "__doc__": f"Temperature sensor, {_minimum:g} to {_maximum:g} °C.",
        },
    )


class _TemperatureSensor10Bit(EEP):
    """A5-02 10-bit temperature encoding (DB2.1..DB1.0)."""
    metadata = EEPMetadata("", "10-bit temperature sensor",
        "Temperature sensor using the A5-02 10-bit linear encoding.", 0x07, (
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C"),
    ))
    temp_min = 0.0
    temp_max = 40.0

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        raw = ((msg.data[1] & 0x03) << 8) | msg.data[2]
        temperature = cls.temp_min + (1023 - raw) / 1023 * (cls.temp_max - cls.temp_min)
        return cls(temperature)

    def encode_message(self, address):
        if not self.temp_min <= self.current_temperature <= self.temp_max:
            raise ValueError(
                f"Temperature must be between {self.temp_min} and {self.temp_max} °C")
        raw = round((self.temp_max - self.current_temperature) /
                    (self.temp_max - self.temp_min) * 1023)
        data = bytearray(4)
        data[1] = (raw >> 8) & 0x03
        data[2] = raw & 0xFF
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def current_temperature(self):
        return self._temperature

    def __init__(self, temperature=0.0):
        self._temperature = temperature


class A5_02_20(_TemperatureSensor10Bit):
    """10-bit temperature sensor, -10 to +41.2 °C."""
    temp_min = -10.0
    temp_max = 41.2
    metadata = _TemperatureSensor10Bit.metadata._replace(fields=(
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (-10.0, 41.2)),
    ))


class A5_02_30(_TemperatureSensor10Bit):
    """10-bit temperature sensor, -40 to +62.3 °C."""
    temp_min = -40.0
    temp_max = 62.3
    metadata = _TemperatureSensor10Bit.metadata._replace(fields=(
        EEPFieldMetadata("current_temperature", "Measured temperature.", "°C", (-40.0, 62.3)),
    ))


class _OccupancySensorWithIllumination(EEP):
    """A5-07 occupancy sensor with supply voltage and 10-bit illumination."""
    metadata = EEPMetadata("", "Occupancy and illumination sensor",
        "Occupancy sensor with super-capacitor voltage and 0 to 1000 lx illumination.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply or super-capacitor voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("illumination", "Measured illumination.", "lx", (0.0, 1000.0)),
        EEPFieldMetadata("motion_detected", "Whether motion is detected.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("error_code", "Supply voltage error code, if present.", value_range=(0, 255), data_type="integer"),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError

        # ESP2 data is exposed as DB3..DB0 by Regular4BSMessage.  A5-07-03
        # places supply voltage in DB3, illumination in DB2.7..DB1.6 and
        # occupancy in DB0.7.
        supply_raw = msg.data[0]
        error_code = supply_raw if supply_raw >= 251 else 0
        supply_voltage = min(supply_raw, 250) / 250.0 * 5.0
        illumination_raw = (msg.data[1] << 2) | (msg.data[2] >> 6)
        illumination = min(illumination_raw, 1000)
        motion_detected = (msg.data[3] & 0x80) >> 7
        return cls(supply_voltage, illumination, motion_detected, error_code)

    def encode_message(self, address):
        if not 0.0 <= self.supply_voltage <= 5.0:
            raise ValueError("Supply voltage must be between 0 and 5 V")
        if not 0.0 <= self.illumination <= 1000.0:
            raise ValueError("Illumination must be between 0 and 1000 lx")

        supply_raw = min(250, int(self.supply_voltage / 5.0 * 250))
        illumination_raw = int(self.illumination)
        data = bytearray(4)
        data[0] = supply_raw
        data[1] = (illumination_raw >> 2) & 0xFF
        data[2] = (illumination_raw & 0x03) << 6
        data[3] = (int(bool(self.motion_detected)) << 7)
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def supply_voltage(self):
        return self._supply_voltage

    @property
    def illumination(self):
        return self._illumination

    @property
    def motion_detected(self):
        return self._motion_detected

    @property
    def error_code(self):
        return self._error_code

    def __init__(self, supply_voltage=0.0, illumination=0.0, motion_detected=0, error_code=0):
        self._supply_voltage = supply_voltage
        self._illumination = illumination
        self._motion_detected = motion_detected
        self._error_code = error_code


class A5_07_03(_OccupancySensorWithIllumination):
    """Occupancy with supply voltage monitor and 10-bit illumination."""


class _OccupancySensorWithRequiredSupply(EEP):
    """Standard A5-07-02 occupancy telegram."""
    metadata = EEPMetadata("", "Occupancy sensor with supply voltage",
        "Occupancy sensor with required supply-voltage monitoring.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply or super-capacitor voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("motion_detected", "Whether motion is detected.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("error_code", "Supply-voltage error code, if present.", value_range=(0, 255), data_type="integer"),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        supply_raw = msg.data[0]
        error_code = supply_raw if supply_raw >= 251 else 0
        supply_voltage = min(supply_raw, 250) / 250.0 * 5.0
        motion_detected = bool(msg.data[3] & 0x80)
        return cls(supply_voltage, motion_detected, error_code)

    def encode_message(self, address):
        if not 0.0 <= self.supply_voltage <= 5.0:
            raise ValueError("Supply voltage must be between 0 and 5 V")
        data = bytearray(4)
        data[0] = min(250, int(self.supply_voltage / 5.0 * 250))
        data[3] = int(bool(self.motion_detected)) << 7
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def supply_voltage(self):
        return self._supply_voltage

    @property
    def motion_detected(self):
        return self._motion_detected

    @property
    def error_code(self):
        return self._error_code

    def __init__(self, supply_voltage=0.0, motion_detected=False, error_code=0):
        self._supply_voltage = supply_voltage
        self._motion_detected = motion_detected
        self._error_code = error_code


class A5_07_02(_OccupancySensorWithRequiredSupply):
    """Occupancy with supply voltage monitor (standard EEP A5-07-02)."""


class _EltakoWindowContact(EEP):
    """Eltako 4BS window contact status used by FFGB and mTronic."""
    metadata = EEPMetadata("", "Window contact",
        "Window state with supply voltage and optional alarm flag.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("window_state", "Window position.", data_type="enum",
                         values={0x08: "closed", 0x0A: "tilted", 0x0E: "open"}),
        EEPFieldMetadata("alarm", "Tamper or alarm flag.", data_type="boolean", value_range=(0, 1)),
    ))
    CLOSED = 0x08
    TILTED = 0x0A
    OPEN = 0x0E

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        status = msg.data[3]
        return cls(msg.data[0] / 250.0 * 5.0, status & 0xFE, status & 0x01)

    def encode_message(self, address):
        if not 0.0 <= self.supply_voltage <= 5.0:
            raise ValueError("Supply voltage must be between 0 and 5 V")
        if self.window_state not in (self.CLOSED, self.TILTED, self.OPEN):
            raise ValueError("Window state must be 0x08, 0x0A, or 0x0E")
        data = bytearray((int(self.supply_voltage / 5.0 * 250.0), 0, 0,
                          self.window_state | int(bool(self.alarm))))
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def supply_voltage(self): return self._supply_voltage
    @property
    def window_state(self): return self._window_state
    @property
    def alarm(self): return self._alarm

    def __init__(self, supply_voltage=0.0, window_state=CLOSED, alarm=0):
        self._supply_voltage = supply_voltage
        self._window_state = window_state
        self._alarm = alarm


class A5_14_09(_EltakoWindowContact):
    """Eltako FFGB window contact status."""


class A5_14_0A(_EltakoWindowContact):
    """Eltako mTronic window contact status with alarm flag."""


class _A514ContactSensor(EEP):
    """Shared decoder for Eltako's supply-voltage/contact 4BS profiles."""
    voltage_error_values = range(251, 256)

    @classmethod
    def _common(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        raw = msg.data[0]
        return min(raw, 250) / 250.0 * 5.0, (raw if raw in cls.voltage_error_values else 0), (msg.data[3] >> 3) & 1

    def _encode_common(self, address, db0):
        if not 0.0 <= self.supply_voltage <= 5.0:
            raise ValueError("Supply voltage must be between 0 and 5 V")
        raw = min(250, int(round(self.supply_voltage / 5.0 * 250.0)))
        return Regular4BSMessage(address, 0, bytes((raw, 0, 0, db0 | (self.learn_button << 3))), True)

    @property
    def supply_voltage(self): return self._supply_voltage
    @property
    def error_code(self): return self._error_code
    @property
    def learn_button(self): return self._learn_button

    def __init__(self, supply_voltage=0.0, error_code=0, learn_button=1):
        self._supply_voltage = supply_voltage
        self._error_code = error_code
        self._learn_button = learn_button


class A5_14_01(_A514ContactSensor):
    """Contact and supply voltage sensor."""
    metadata = EEPMetadata("", "Contact sensor",
        "Contact state with supply-voltage monitoring.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("contact", "Contact state (0 closed, 1 open).", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn bit.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("error_code", "Supply-voltage error code, 251..255.", data_type="integer", value_range=(0, 255)),
    ))
    @classmethod
    def decode_message(cls, msg):
        voltage, error, learn = cls._common(msg)
        return cls(voltage, (msg.data[3] & 1), learn, error)
    def encode_message(self, address):
        return self._encode_common(address, self.contact & 1)
    @property
    def contact(self): return self._contact
    def __init__(self, supply_voltage=0.0, contact=0, learn_button=1, error_code=0):
        super().__init__(supply_voltage, error_code, learn_button); self._contact = int(bool(contact))


class A5_14_03(_A514ContactSensor):
    """Contact and vibration sensor."""
    metadata = A5_14_01.metadata._replace(eep="", name="Contact and vibration sensor",
        description="Contact, vibration and supply-voltage status.", fields=(
        EEPFieldMetadata("supply_voltage", "Supply voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("contact", "Contact state (0 closed, 1 open).", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("vibration", "Vibration detected.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn bit.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("error_code", "Supply-voltage error code, 251..255.", data_type="integer", value_range=(0, 255)),))
    @classmethod
    def decode_message(cls, msg):
        voltage, error, learn = cls._common(msg)
        return cls(voltage, msg.data[3] & 1, (msg.data[3] >> 1) & 1, learn, error)
    def encode_message(self, address): return self._encode_common(address, self.contact | (self.vibration << 1))
    @property
    def contact(self): return self._contact
    @property
    def vibration(self): return self._vibration
    def __init__(self, supply_voltage=0.0, contact=0, vibration=0, learn_button=1, error_code=0):
        super().__init__(supply_voltage, error_code, learn_button); self._contact=int(bool(contact)); self._vibration=int(bool(vibration))


class A5_14_05(A5_14_03):
    """Vibration sensor with supply-voltage monitoring."""
    metadata = A5_14_03.metadata._replace(eep="", name="Vibration sensor",
        description="Vibration and supply-voltage status.", fields=tuple(f for f in A5_14_03.metadata.fields if f.name != "contact"))
    @classmethod
    def decode_message(cls, msg):
        voltage, error, learn = cls._common(msg)
        return cls(voltage, 0, (msg.data[3] >> 1) & 1, learn, error)
    def encode_message(self, address): return self._encode_common(address, self.vibration << 1)


class A5_14_07(A5_14_03):
    """Door and lock contact sensor."""
    metadata = A5_14_03.metadata._replace(eep="", name="Door and lock contact",
        description="Door contact, lock contact and supply-voltage status.", fields=(
        EEPFieldMetadata("supply_voltage", "Supply voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("door_contact", "Door state (0 closed, 1 open).", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("lock_contact", "Lock state (0 locked, 1 unlocked).", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn bit.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("error_code", "Supply-voltage error code, 251..255.", data_type="integer", value_range=(0, 255)),))
    @classmethod
    def decode_message(cls, msg):
        voltage, error, learn = cls._common(msg)
        return cls(voltage, msg.data[3] >> 2 & 1, msg.data[3] >> 1 & 1, learn, error)
    def encode_message(self, address): return self._encode_common(address, (self.door_contact << 2) | (self.lock_contact << 1))
    @property
    def door_contact(self): return self._contact
    @property
    def lock_contact(self): return self._vibration
    def __init__(self, supply_voltage=0.0, door_contact=0, lock_contact=0, learn_button=1, error_code=0):
        super().__init__(supply_voltage, door_contact, lock_contact, learn_button, error_code)


class A5_14_08(A5_14_07):
    """Door, lock and vibration contact sensor."""
    metadata = A5_14_07.metadata._replace(eep="", name="Door, lock and vibration sensor",
        description="Door contact, lock contact, vibration and supply-voltage status.", fields=A5_14_07.metadata.fields + (
        EEPFieldMetadata("vibration", "Vibration detected.", data_type="boolean", value_range=(0, 1)),))
    @classmethod
    def decode_message(cls, msg):
        voltage, error, learn = cls._common(msg)
        return cls(voltage, msg.data[3] >> 2 & 1, msg.data[3] >> 1 & 1, msg.data[3] & 1, learn, error)
    def encode_message(self, address): return self._encode_common(address, (self.door_contact << 2) | (self.lock_contact << 1) | self.vibration)
    @property
    def vibration(self): return self._vibration_extra
    def __init__(self, supply_voltage=0.0, door_contact=0, lock_contact=0, vibration=0, learn_button=1, error_code=0):
        super().__init__(supply_voltage, door_contact, lock_contact, learn_button, error_code); self._vibration_extra=int(bool(vibration))


class _SmokeDetector(EEP):
    """RPS smoke detector status used by Eltako FRW and compatible devices."""
    metadata = EEPMetadata("", "Smoke detector",
        "Smoke detector alarm and low-battery status telegram.", 0x05, (
        EEPFieldMetadata("status", "Raw smoke detector status.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("smoke_alarm", "Whether the smoke alarm is active.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("low_battery", "Whether the low-battery status is reported.", data_type="boolean", value_range=(0, 1)),
    ))
    NORMAL = 0x00
    ALARM = 0x10
    LOW_BATTERY = 0x30

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        return cls(msg.data[0])

    def encode_message(self, address):
        return RPSMessage(address, 0x30, bytes((self.status,)), True)

    @property
    def status(self):
        return self._status

    @property
    def smoke_alarm(self):
        return self.status == self.ALARM

    @property
    def low_battery(self):
        return self.status == self.LOW_BATTERY

    def __init__(self, status=0):
        if not 0 <= status <= 255:
            raise ValueError("Smoke detector status must be a byte")
        self._status = status


class F6_05_02(_SmokeDetector):
    """Smoke detector status (e.g. Eltako FRW)."""


class _WaterLeakageDetector(EEP):
    """Eltako FWS81 water-leakage RPS status telegram."""
    metadata = EEPMetadata("", "Water leakage detector",
        "Water/no-water status telegram from an Eltako water detector.", 0x05, (
        EEPFieldMetadata("status", "Raw water detector status.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("water_detected", "Whether water is detected.", data_type="boolean", value_range=(0, 1)),
    ))
    WATER = 0x30
    NO_WATER = 0x20

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x05:
            raise WrongOrgError
        return cls(msg.data[0])

    def encode_message(self, address):
        return RPSMessage(address, 0x30, bytes((self.status,)), True)

    @property
    def status(self):
        return self._status

    @property
    def water_detected(self):
        return self.status == self.WATER

    def __init__(self, status=NO_WATER):
        if not 0 <= status <= 255:
            raise ValueError("Water detector status must be a byte")
        self._status = status


class F6_05_01(_WaterLeakageDetector):
    """Water leakage sensor (e.g. Eltako FWS81)."""


# ======================================
# MARK: - Automated Meter Reading
# ======================================

class _AutomatedMeterReading(EEP):
    metadata = EEPMetadata("", "Automated meter reading",
        "Meter reading with measurement channel, data type and decimal divisor.", 0x07, (
        EEPFieldMetadata("meter_reading", "Raw cumulative meter reading.", value_range=(0, 16777215), data_type="integer"),
        EEPFieldMetadata("measurement_channel", "Meter measurement channel.", value_range=(0, 15), data_type="integer"),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("data_type", "Meter data type.", value_range=(0, 1), data_type="integer"),
        EEPFieldMetadata("divisor", "Decimal divisor code.", value_range=(0, 3), data_type="integer"),
    ))
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
    metadata = EEPMetadata("", "Shutter status", "Shutter state or movement status telegram.", None, (
        EEPFieldMetadata("state", "Raw shutter state.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("time", "Movement time.", "s", (0, 65535), data_type="integer"),
        EEPFieldMetadata("direction", "Movement direction.", value_range=(0, 255), data_type="integer"),
    ))
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
    metadata = EEPMetadata("", "Shutter command", "Shutter movement command with time and command code.", 0x07, (
        EEPFieldMetadata("time", "Requested movement time; resolution is selected by send_time_in_seconds.", "s", (0, 6553.5), data_type="number"),
        EEPFieldMetadata("command", "Shutter command code.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("send_time_in_seconds", "Encode movement time in whole seconds when true, otherwise in 100-ms units.", data_type="boolean", value_range=(0, 1)),
    ))
    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        send_time_in_seconds = not (msg.data[3] & 0x02)
        if send_time_in_seconds:
            time = msg.data[1]
        else:
            time = ((msg.data[0] << 8) | msg.data[1]) / 10.0
        command = msg.data[2]
        learn_button = (msg.data[3] & 0x08) >> 3

        return cls(time, command, learn_button, send_time_in_seconds)

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        if self.send_time_in_seconds:
            if not isinstance(self.time, int) or isinstance(self.time, bool):
                raise ValueError("Cover drive time must be an integer in seconds")
            if not 0 <= self.time <= 255:
                raise ValueError("Cover drive time must be between 0 and 255 seconds")
            data[1] = self.time
        else:
            time_100ms = round(self.time * 10)
            if not 0 <= time_100ms <= 0xffff:
                raise ValueError("Cover drive time must be between 0 and 6553.5 seconds")
            data[0] = (time_100ms >> 8) & 0xff
            data[1] = time_100ms & 0xff
            data[3] = 0x02
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

    @property
    def send_time_in_seconds(self):
        return self._send_time_in_seconds

    def __init__(self, time, command, learn_button, send_time_in_seconds=True):
        self._time = time
        self._command = command
        self._learn_button = learn_button
        self._send_time_in_seconds = send_time_in_seconds

class H5_3F_7F(_EltakoShutterCommand):
    """Eltako Shutter Command"""


# ======================================
# MARK: - Occupancy Sensor
# ======================================
    
class _OccupancySensor(EEP):
    metadata = EEPMetadata("", "Occupancy sensor", "PIR occupancy sensor with supply-voltage status.", 0x07, (
        EEPFieldMetadata("support_voltage", "Sensor supply voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("pir_status", "Raw PIR status.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("pir_status_on", "Whether occupancy is detected.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("support_volrage_availability", "Supply-voltage value available.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))

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
    metadata = EEPMetadata("", "Brightness and twilight sensor",
        "Brightness sensor with a twilight value and a daylight illumination range.", 0x07, (
        EEPFieldMetadata("twilight", "Twilight threshold/value.", "lx", (0, 255), data_type="integer"),
        EEPFieldMetadata("day_light", "Daylight illumination.", "lx", (300, 30000)),
        EEPFieldMetadata("illumination", "Selected illumination value.", "lx", (0, 30000)),
    ))
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


class _EltakoLightVoltageSensor(EEP):
    """Eltako FHD65SB variant documented as A5-06-02."""
    metadata = EEPMetadata("", "Light and supply-voltage sensor",
        "Eltako illumination and supply-voltage telegram, 0 to 1020 lx and 0 to 5.1 V.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply voltage.", "V", (0.0, 5.1)),
        EEPFieldMetadata("illumination", "Illumination.", "lx", (0.0, 1020.0)),
        EEPFieldMetadata("profile_marker", "Eltako profile marker (DB0).", data_type="integer", value_range=(0, 255)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        return cls(msg.data[0] / 255.0 * 5.1, msg.data[1] / 255.0 * 1020.0, msg.data[3])

    def encode_message(self, address):
        if not 0.0 <= self.supply_voltage <= 5.1:
            raise ValueError("Supply voltage must be between 0 and 5.1 V")
        if not 0.0 <= self.illumination <= 1020.0:
            raise ValueError("Illumination must be between 0 and 1020 lx")
        data = bytearray((int(self.supply_voltage / 5.1 * 255.0),
                          int(self.illumination / 1020.0 * 255.0), 0, self.profile_marker))
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def supply_voltage(self):
        return self._supply_voltage

    @property
    def illumination(self):
        return self._illumination

    @property
    def profile_marker(self):
        return self._profile_marker

    def __init__(self, supply_voltage=0.0, illumination=0.0, profile_marker=0x0F):
        self._supply_voltage = supply_voltage
        self._illumination = illumination
        self._profile_marker = profile_marker


class A5_06_02(_EltakoLightVoltageSensor):
    """Eltako FHD65SB light and supply-voltage telegram."""


class _LightSensor10Bit(EEP):
    """Standard A5-06-03 10-bit illumination sensor."""
    metadata = EEPMetadata("", "10-bit light sensor",
        "Light sensor with 1 lx resolution and a 0 to 1000 lx range.", 0x07, (
        EEPFieldMetadata("supply_voltage", "Supply or super-capacitor voltage.", "V", (0.0, 5.0)),
        EEPFieldMetadata("illumination", "Measured illumination.", "lx", (0.0, 1000.0)),
        EEPFieldMetadata("error_code", "Supply-voltage error code, if present.", value_range=(0, 255), data_type="integer"),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        supply_raw = msg.data[0]
        error_code = supply_raw if supply_raw >= 251 else 0
        supply_voltage = min(supply_raw, 250) / 250.0 * 5.0
        illumination_raw = (msg.data[1] << 2) | (msg.data[2] >> 6)
        illumination = min(illumination_raw, 1000)
        return cls(supply_voltage, illumination, error_code)

    def encode_message(self, address):
        if not 0.0 <= self.supply_voltage <= 5.0:
            raise ValueError("Supply voltage must be between 0 and 5 V")
        if not 0.0 <= self.illumination <= 1000.0:
            raise ValueError("Illumination must be between 0 and 1000 lx")
        illumination_raw = int(self.illumination)
        data = bytearray(4)
        data[0] = min(250, int(self.supply_voltage / 5.0 * 250))
        data[1] = (illumination_raw >> 2) & 0xFF
        data[2] = (illumination_raw & 0x03) << 6
        return Regular4BSMessage(address, 0x00, data, True)

    @property
    def supply_voltage(self):
        return self._supply_voltage

    @property
    def illumination(self):
        return self._illumination

    @property
    def error_code(self):
        return self._error_code

    def __init__(self, supply_voltage=0.0, illumination=0.0, error_code=0):
        self._supply_voltage = supply_voltage
        self._illumination = illumination
        self._error_code = error_code


class A5_06_03(_LightSensor10Bit):
    """10-bit light sensor with 0 to 1000 lx range."""

class _DigitalInputAndBattery(EEP):
    """Digital Input regarding A5-30-01"""
    metadata = EEPMetadata("", "Digital input with battery status",
        "Digital contact input with battery and contact status bytes.", 0x07, (
        EEPFieldMetadata("battery_status", "Raw battery status.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("low_battery", "Whether the battery is low.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("contact_status", "Raw contact status.", value_range=(0, 255), data_type="integer"),
        EEPFieldMetadata("contact_closed", "Whether the contact is closed.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("learn_button", "Learn button flag.", data_type="boolean", value_range=(0, 1)),
    ))

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
    metadata = EEPMetadata("", "Four digital inputs and temperature",
        "Eltako FHMB/FRWB temperature and smoke alarm telegram.", 0x07, (
        EEPFieldMetadata("temperature", "Measured temperature.", "°C", (0.0, 40.0)),
        EEPFieldMetadata("alarm_status", "Eltako alarm marker (0x0F alarm, 0x1F no alarm).", data_type="integer", value_range=(0, 255)),
        EEPFieldMetadata("alarm", "Whether the alarm is active.", data_type="boolean", value_range=(0, 1)),
        EEPFieldMetadata("profile_marker", "Eltako profile marker (DB0).", data_type="integer", value_range=(0, 255)),
    ))

    @classmethod
    def decode_message(cls, msg):
        if msg.org != 0x07:
            raise WrongOrgError
        
        temperature = (255 - msg.data[1]) / 255 * 40
        alarm_status = msg.data[2]
        return cls(temperature, alarm_status, msg.data[3])
    

    def encode_message(self, address):
        data = bytearray([0, 0, 0, 0])
        
        data[1] = int((255 - self._temperature / 40 * 255))
        data[2] = self.alarm_status
        data[3] = self.profile_marker

        status = 0x00
        
        return Regular4BSMessage(address, status, data, True)
    
    @property
    def alarm_status(self):
        return self._alarm_status

    @property
    def temperature(self):
        return self._temperature

    @property
    def alarm(self):
        return self.alarm_status == 0x0F

    @property
    def profile_marker(self):
        return self._profile_marker

    # Legacy names remain available as aliases for applications that used the
    # former generic interpretation of this profile.
    @property
    def digital_input_0(self): return self.alarm_status & 0x01
    @property
    def digital_input_1(self): return (self.alarm_status >> 1) & 0x01
    @property
    def digital_input_2(self): return (self.alarm_status >> 2) & 0x01
    @property
    def digital_input_3(self): return (self.alarm_status >> 3) & 0x01
    @property
    def status_of_wake(self): return (self.alarm_status >> 4) & 0x01
    @property
    def learn_button(self): return (self.profile_marker >> 3) & 0x01

    def __init__(self, temperature=0.0, alarm_status=0x1F, profile_marker=0x08):
        self._temperature = temperature
        self._alarm_status = alarm_status
        self._profile_marker = profile_marker

class A5_30_03(_DigitalInputsAndTemperature):
    """Digital Inputs"""


# ======================================
# MARK: - VLD profiles (ESP3 RORG D2)
# ======================================

def _vld_bits(data, offset, size):
    """Read an MSB-first bit field from a VLD payload."""
    if len(data) * 8 < offset + size:
        raise ValueError("VLD payload is shorter than the EEP profile")
    value = 0
    for bit in range(size):
        absolute = offset + bit
        value = (value << 1) | ((data[absolute // 8] >> (7 - absolute % 8)) & 1)
    return value


def _vld_message_data(msg, minimum):
    if getattr(msg, "org", None) != 0xD2:
        raise WrongOrgError
    data = bytes(msg.data)
    if len(data) < minimum:
        raise ValueError("VLD payload is too short")
    return data


def _linear_or_none(raw, maximum, minimum, physical_max):
    return None if raw > maximum else minimum + (raw / float(maximum)) * (physical_max - minimum)


class D2_00_01(EEP):
    """RCP/window handle controller with temperature and environment data."""
    metadata = EEPMetadata("", "RCP with temperature measurement and display",
        "Bidirectional controller status including handle, window, buttons, temperature, humidity, illumination and battery state.", 0xD2, (
        EEPFieldMetadata("message_type", "VLD message type.", data_type="integer", value_range=(0, 255)),
        EEPFieldMetadata("burglary_alarm", "Burglary alarm state.", data_type="enum", values={0: "not triggered", 1: "triggered", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("protection_alarm", "Protection-plus alarm state.", data_type="enum", values={0: "not triggered", 1: "triggered", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("handle_position", "Window-handle position.", data_type="enum", values={0: "undefined", 1: "up", 2: "down", 3: "left", 4: "right", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("window_state", "Window state.", data_type="enum", values={0: "undefined", 1: "not tilted", 2: "tilted", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("button_right", "Right button state.", data_type="enum", values={0: "no change", 1: "pressed", 2: "released", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("button_left", "Left button state.", data_type="enum", values={0: "no change", 1: "pressed", 2: "released", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("motion", "Motion state.", data_type="enum", values={0: "not triggered", 1: "triggered", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("vacation_mode", "Vacation mode state.", data_type="enum", values={0: "no change", 1: "locally switched on", 2: "locally switched off", 14: "invalid", 15: "unsupported"}),
        EEPFieldMetadata("temperature", "Measured temperature.", "°C", (-20.0, 60.0)),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("illumination", "Illumination.", "lx", (0.0, 60000.0)),
        EEPFieldMetadata("battery_state", "Battery state.", "%", (0.0, 100.0)),
    ))
    @classmethod
    def decode_message(cls, msg):
        data = _vld_message_data(msg, 10)
        if data[0] != 0:
            raise NotImplementedError
        raw_temperature = _vld_bits(data, 40, 8)
        raw_humidity = _vld_bits(data, 48, 8)
        raw_illumination = _vld_bits(data, 56, 16)
        return cls(
            message_type=data[0], burglary_alarm=_vld_bits(data, 8, 4),
            protection_alarm=_vld_bits(data, 12, 4), handle_position=_vld_bits(data, 16, 4),
            window_state=_vld_bits(data, 20, 4), button_right=_vld_bits(data, 24, 4),
            button_left=_vld_bits(data, 28, 4), motion=_vld_bits(data, 32, 4),
            vacation_mode=_vld_bits(data, 36, 4), temperature=_linear_or_none(raw_temperature, 250, -20, 60),
            humidity=None if raw_humidity >= 201 else raw_humidity / 2.0,
            illumination=None if raw_illumination > 60000 else float(raw_illumination),
            battery_state=None if _vld_bits(data, 72, 5) > 20 else _vld_bits(data, 72, 5) * 5,
            temperature_raw=raw_temperature, humidity_raw=raw_humidity,
            illumination_raw=raw_illumination, battery_state_raw=_vld_bits(data, 72, 5))

    def __init__(self, **values):
        for name, value in values.items(): setattr(self, name, value)


class _D2_14(EEP):
    metadata = EEPMetadata("", "Indoor multisensor",
        "Temperature, humidity, illumination and three-axis acceleration VLD telegram.", 0xD2, (
        EEPFieldMetadata("temperature", "Measured temperature.", "°C", (-40.0, 60.0)),
        EEPFieldMetadata("humidity", "Relative humidity.", "%", (0.0, 100.0)),
        EEPFieldMetadata("illumination", "Illumination.", "lx", (0.0, 100000.0)),
        EEPFieldMetadata("acceleration_status", "Acceleration event status.", data_type="enum", values={0: "periodic", 1: "threshold 1", 2: "threshold 2", 3: "reserved"}),
        EEPFieldMetadata("acceleration_x", "Acceleration X.", "g", (-2.5, 2.5)),
        EEPFieldMetadata("acceleration_y", "Acceleration Y.", "g", (-2.5, 2.5)),
        EEPFieldMetadata("acceleration_z", "Acceleration Z.", "g", (-2.5, 2.5)),
    ))
    @classmethod
    def _decode_common(cls, msg):
        data = _vld_message_data(msg, 9)
        raws = [_vld_bits(data, 0, 10), _vld_bits(data, 10, 8), _vld_bits(data, 18, 17),
                _vld_bits(data, 35, 2), _vld_bits(data, 37, 10), _vld_bits(data, 47, 10), _vld_bits(data, 57, 10)]
        return data, raws
    @staticmethod
    def _physical(raw, maximum, minimum, maximum_value):
        return _linear_or_none(raw, maximum, minimum, maximum_value)
    def __init__(self, temperature, humidity, illumination, acceleration_status,
                 acceleration_x, acceleration_y, acceleration_z, contact=None, **raws):
        self.temperature = temperature; self.humidity = humidity; self.illumination = illumination
        self.acceleration_status = acceleration_status; self.acceleration_x = acceleration_x
        self.acceleration_y = acceleration_y; self.acceleration_z = acceleration_z
        if contact is not None: self.contact = contact
        for name, value in raws.items(): setattr(self, name, value)


class D2_14_40(_D2_14):
    """Indoor multisensor proposal profile without a contact bit."""
    @classmethod
    def decode_message(cls, msg):
        data, r = cls._decode_common(msg)
        return cls(cls._physical(r[0], 1000, -40, 60), None if r[1] >= 201 else r[1] / 2.0,
                   None if r[2] > 100000 else float(r[2]), r[3],
                   cls._physical(r[4], 1000, -2.5, 2.5), cls._physical(r[5], 1000, -2.5, 2.5),
                   cls._physical(r[6], 1000, -2.5, 2.5), temperature_raw=r[0], humidity_raw=r[1],
                   illumination_raw=r[2], acceleration_x_raw=r[4], acceleration_y_raw=r[5], acceleration_z_raw=r[6])


class D2_14_41(_D2_14):
    """Indoor multisensor proposal profile with a window/contact bit."""
    metadata = _D2_14.metadata._replace(eep="", name="Indoor multisensor with contact",
        description="Temperature, humidity, illumination, acceleration and contact VLD telegram.", fields=_D2_14.metadata.fields + (
        EEPFieldMetadata("contact", "Contact state (0 open, 1 closed).", data_type="boolean", value_range=(0, 1)),))
    @classmethod
    def decode_message(cls, msg):
        data, r = cls._decode_common(msg)
        return cls(cls._physical(r[0], 1000, -40, 60), None if r[1] >= 201 else r[1] / 2.0,
                   None if r[2] > 100000 else float(r[2]), r[3],
                   cls._physical(r[4], 1000, -2.5, 2.5), cls._physical(r[5], 1000, -2.5, 2.5),
                   cls._physical(r[6], 1000, -2.5, 2.5), contact=bool(_vld_bits(data, 67, 1)),
                   temperature_raw=r[0], humidity_raw=r[1], illumination_raw=r[2],
                   acceleration_x_raw=r[4], acceleration_y_raw=r[5], acceleration_z_raw=r[6])
