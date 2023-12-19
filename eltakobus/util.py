def b2a(rawdata, separator=' '):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return separator.join("%02x"%b for b in rawdata)

def b2s(rawdata, separator='-'):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return separator.join("%02x"%b for b in rawdata).upper()

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
