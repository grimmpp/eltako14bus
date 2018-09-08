def b2a(rawdata):
    # like binascii.b2a_hex, but directly to unicode for printing, and with nice spacing
    return " ".join("%02x"%b for b in rawdata)
