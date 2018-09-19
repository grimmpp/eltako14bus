"""Selected supported EEP decoders

This does not access the XML EEP definitions due to their unclear license
status."""

from .util import b2a

class ProfileExpression(tuple):
    """A 3-tuple expressing a profile without actually guaranteeing that it is
    implemenmted. This is mainly for passing around user-entered values and
    reporting errors about them."""

    @classmethod
    def parse(cls, s):
        psplit = s.split('-')
        if 3 != len(psplit):
            raise ValueError
        return cls((int(x, 16) for x in psplit))

    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self)

    def __str__(self):
        return b2a(self).replace(' ', '-')

class AddressExpression(tuple):
    """An object around the 4-long byte strings passed around for addressing
    purposes. This supports parsing and serialization for user-readable
    purposes (esp. in home assistant), but also adds the possibility to add a
    discriminator string (eg. "00-21-63-43 left", stored as (b'\0\x32\x63\x43',
    'left')) to the address which is used in the programming area to express
    sub-features of an address that neither fit there nor in the profile."""

    def __repr__(self):
        return "<%s %s>" % (type(self).__name__, self)

    def __str__(self):
        return b2a(self[0]).replace(' ', '-') + (" %s" % self[1] if self[1] is not None else "")

    @classmethod
    def parse(cls, s):
        plain, delim, discriminator = s.partition(' ')
        if not delim:
            discriminator = None
        plain = bytes(int(x, 16) for x in plain.split('-'))
        if len(plain) != 4:
            raise ValueError
        return cls((plain, discriminator))

    def plain_address(self):
        """Return the address and assert that no discriminator is set"""
        if self[1] is not None:
            raise ValueError("Address has disciminator %s, None expected" % self[1])
        return self[0]

class EEP:
    __by_eep_number = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, "eep") and cls.__name__[:3] in (('A5_', 'F6_')):
            cls.eep = tuple(int(x, 16) for x in cls.__name__.split('_'))

        if hasattr(cls, "eep"):
            cls.__by_eep_number[cls.eep] = cls

    @classmethod
    def find(cls, profile):
        return cls.__by_eep_number[profile]

class TemperatureSensor(EEP):
    """The straight-forward subtypes of A5-02"""
    fields = ['temperature']

    @classmethod
    def decode(cls, data):
        return {'temperature': cls.min + (cls.max - cls.min) * (255 - data[2]) / 255}

class A5_02_01(TemperatureSensor): min = -40; max = 0
class A5_02_02(TemperatureSensor): min = -30; max = 10
class A5_02_03(TemperatureSensor): min = -20; max = 20
class A5_02_04(TemperatureSensor): min = -10; max = 30
class A5_02_05(TemperatureSensor): min = 0; max = 40
class A5_02_06(TemperatureSensor): min = 10; max = 50
class A5_02_07(TemperatureSensor): min = 20; max = 60
class A5_02_08(TemperatureSensor): min = 30; max = 70
class A5_02_09(TemperatureSensor): min = 40; max = 80
class A5_02_0A(TemperatureSensor): min = 50; max = 90
class A5_02_0B(TemperatureSensor): min = 60; max = 100
class A5_02_10(TemperatureSensor): min = -60; max = 20
class A5_02_11(TemperatureSensor): min = -50; max = 30
class A5_02_12(TemperatureSensor): min = -40; max = 40
class A5_02_13(TemperatureSensor): min = -30; max = 50
class A5_02_14(TemperatureSensor): min = -20; max = 60
class A5_02_15(TemperatureSensor): min = -10; max = 70
class A5_02_16(TemperatureSensor): min = 0; max = 80
class A5_02_17(TemperatureSensor): min = 10; max = 90
class A5_02_18(TemperatureSensor): min = 20; max = 100
class A5_02_19(TemperatureSensor): min = 30; max = 110
class A5_02_1A(TemperatureSensor): min = 40; max = 120
class A5_02_1B(TemperatureSensor): min = 50; max = 130

class TempHumSensor(EEP):
    """The straight-forward subtypes of A5-04"""
    fields = ['temperature', 'humidity']

    @classmethod
    def decode(cls, data):
        return {
                'humidity': 100 * data[1] / 250,
                'temperature': cls.min + (cls.max - cls.min) * data[2] / 255,
                }

class A5_04_01(TempHumSensor): min = 0; max = 40
class A5_04_02(TempHumSensor): min = -20; max = 60

class MeterReading(EEP):
    """Base for the A5-12 subtypes"""
    @classmethod
    def decode(cls, data):
        value = (data[0] << 16) + (data[1] << 8) + data[2]
        channel = data[3] >> 4
        cumulative = not (data[3] & 0x04)
        divisor = 10 ** (data[3] & 0x03)

        return {(channel, cls.cum if cumulative else cls.cur): value / divisor}

class A5_12_00(MeterReading): cum = 'counter'; cur = 'frequency'
class A5_12_01(MeterReading): cum = 'energy'; cur = 'power'
class A5_12_02(MeterReading): cum = 'volume'; cur = 'flow' # for gas
class A5_12_03(MeterReading): cum = 'volume'; cur = 'flow' # for water

class A5_38_08(EEP):
    """So far, only a sentinel -- later, eltakobus.device should make use of
    this for en- and decoding"""
    # FIXME: Decoding code resides in DimmerStyle.interpret_status_update, and
    # the no-op here just makes sure that no unexpected exceptions fly around
    # if any such teach-in telegram comes about

class A5_13_01(EEP):
    """Weather data

    This decodes both A5-13-01 and A5-13-02 telegrams -- the latter should not
    have received an EEP at all in the view of the author, for there are no -01
    teach-in telegrams, and variations of -01 can be discerned by looking at an
    identifier bit, just as variations between the meanings of meter reading
    telegrams (cumulative, current) can be discerned.
    """
    fields = ['illuminance (dawn)', 'temperature', 'wind speed', 'rain', 'illuminance (west)', 'illuminance (central)', 'illuminance (east)', 'fault']

    @classmethod
    def decode(cls, data):
        if data[3] >> 4 == 1:
            if data == bytes((0, 0, 0xff, 0x1a)):
                return {'fault': True}
            return {
                'illuminance (dawn)': 999 * data[0] / 255,
                'temperature': -40 + 120 * data[1] / 255,
                'wind speed': 70 * data[2] / 255,
                'rain': bool(data[3] & 0x02),
                'fault': False,
                }
        elif data[3] >> 4 == 2:
            return {
                'illuminance (west)': 150000 * data[0] / 255,
                'illuminance (central)': 150000 * data[1] / 255,
                'illuminance (east)': 150000 * data[2] / 255,
                }
        else:
            return {}

class F6_02_01(EEP):
    """2-part Rocker switch, Application Style 1 (European, bottom switches
    on)"""
class F6_02_02(EEP):
    """2-part Rocker switch, Application Style 2 (US, top switches on)"""
