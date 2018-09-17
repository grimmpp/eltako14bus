"""Selected supported EEP decoders

This does not access the XML EEP definitions due to their unclear license
status."""

class EEP:
    __by_eep_number = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if not hasattr(cls, "eep") and cls.__name__.startswith('A5_'):
            cls.eep = (0xa5, int(cls.__name__[3:5], 16), int(cls.__name__[6:8], 16))

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

class A5_38_08(EEP):
    """So far, only a sentinel -- later, eltakobus.device should make use of
    this for en- and decoding"""
