def b2a(rawdata):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return " ".join("%02x"%b for b in rawdata)

def combine_hex(data):
    ''' Combine list of integer values to one big integer '''
    output = 0x00
    for i, value in enumerate(reversed(data)):
        output |= (value << i * 8)
    return output
