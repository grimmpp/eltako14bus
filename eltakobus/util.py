from enum import Enum

def b2a(rawdata, separator=' '):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return separator.join("%02x"%b for b in rawdata)

def b2s(rawdata, separator='-'):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return b2a(rawdata, separator).upper()

def combine_hex(data):
    ''' Combine list of integer values to one big integer '''
    output = 0x00
    for i, value in enumerate(reversed(data)):
        output |= (value << i * 8)
    return output

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
        return b2s(self[0]) + (" %s" % self[1] if self[1] is not None else "")

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

class DefaultEnum(Enum):

    # DEFAULT = (0, , 0'Unknown')

    def __new__(cls, value, code:int=0, description:str=None):
        obj = object.__new__(cls)
        obj._value_ = value
        obj._code = code
        obj._description = description
        return obj
    
    @classmethod
    def find_by_code(cls, code):
        for e in cls:
            if e.code == code:
                return e
        return None
    
    @classmethod
    def find_by_description(cls, description):
        for e in cls:
            if e.description == description:
                return e
        return None

    @property
    def value(self) -> int:
        return self._value_

    @property
    def code(self) -> str:
        return self._code

    @property
    def description(self) -> str:
        return self._description
        
    def __repr__(self) -> str:
        v_repr = self.__class__._value_repr_ or repr
        repr = "<%s.%s: %s " % (self.__class__.__name__, self._name_, v_repr(self._value_))
        if self.code:
            repr += '"%S"' % (self.code)
        if self.description:
            repr += '"%S"' % (self.description)
        repr += '>'
        return repr
