from .error import ParseError
from .util import b2a

def prettify(message):
    """Given a ESP2Message, try parsing this as all the known message classes
    and return the parsing result if it matches.

    Only use this for displaying messages during debugging; when driving your
    application logic, you should have a good idea of which messages you'd
    expect, and try to $CLASS.parse() what's coming in. If you rely on
    prettify() to hand you the class you expect, later changes to the list of
    supported messages might give you a subtype or something else
    unexpected."""
    classes = [EltakoBusLock, EltakoBusUnlock, EltakoDiscoveryRequest,
            EltakoDiscoveryReply, EltakoMemoryRequest, EltakoMemoryResponse,
            EltakoTimeout, EltakoPoll, EltakoPollForced, EltakoWrappedRPS,
            EltakoWrapped4BS, RPSMessage, Regular4BSMessage, TeachIn4BSMessage2,
            EltakoMessage]

    for c in classes:
        try: return c.parse(message.serialize())
        except ParseError: pass

    return message

class ESP2Message:
    """A basic message in EnOcean Serial Protocol 2 serialization. The only
    constraint to this class is that the message has the right length, the
    SYNC_BYTEs are present and that the checksum matches. Everything else is
    left to further telegram formats.

    The .org property exposes the ORG byte present in most telegram formats,
    but does not make any assertions on its meaning.

    Subclasses of this implement the same interface (.parse()), but typically
    store the parsed data internally. Their constructors differ because they
    take a more meaningful version of the message's data.
    """
    def __init__(self, body):
        self.body = body

    def serialize(self):
        return b"\xa5\x5a" + self.body + bytes([sum(self.body) % 256])

    @property
    def org(self):
        return self.body[1]

    @classmethod
    def parse(cls, data):
        if data[:2] != b"\xa5\x5a":
            raise ParseError("No preamble found")
        if len(data) != 14:
            raise ParseError("Invalid message length")

        body = data[2:13]
        if sum(body) % 256 != data[13]:
            raise ParseError("Checksum mismatch")

        return ESP2Message(body)

    def __repr__(self):
        return "<%s %r>"%(type(self).__name__, b2a(self.body))

class RPSMessage(ESP2Message):
    """An incoming or outgoing RPS (1 byte, switch) telegram"""
    org = 0x05

    def __init__(self, address, status, data, outgoing=False):
        self.address = address
        self.status = status
        self.data = data
        self.outgoing = outgoing

    h_seq = property(lambda self: 3 if self.outgoing else 0)

    body = property(lambda self: bytes(((self.h_seq << 5) + 11, self.org, *self.data, 0, 0, 0, *self.address, self.status)))

    @classmethod
    def parse(cls, data):
        esp2message = super().parse(data)
        try:
            outgoing = {(3 << 5) + 11: True, (0 << 5) + 11: False}[esp2message.body[0]]
        except KeyError:
            raise ParseError("Code is neither RRT nor TRT")
        if esp2message.body[1] != cls.org:
            raise ParseError("Not an RPS message")
        data = esp2message.body[2:3]
        if any(esp2message.body[3:6]):
            raise ParseError("RPS message should not carry db1..3")
        address = esp2message.body[6:10]
        status = esp2message.body[10]
        return cls(address, status, data, outgoing)

    t21 = property(lambda self: 2 if (self.status >> 5) & 1 else 1)
    nu = property(lambda self: "N" if (self.status >> 4) & 1 else "U")
    rp_count = property(lambda self: self.status & 0xf)

    def __repr__(self):
        return "<%s from %s, db0 = %s, status = 0x%02x (T%s, %s, %d repetitions)>"%(type(self).__name__, b2a(self.address), b2a(self.data), self.status, self.t21, self.nu, self.rp_count)

class _4BSMessage(ESP2Message):
    org = 0x07

    def __init__(self, address, status, data, outgoing=False):
        self.address = address
        self.status = status
        self.data = data
        self.outgoing = outgoing

    h_seq = property(lambda self: 3 if self.outgoing else 0)

    body = property(lambda self: bytes(((self.h_seq << 5) + 11, self.org, *self.data, *self.address, self.status)))

    @classmethod
    def parse(cls, data):
        esp2message = super().parse(data)
        try:
            outgoing = {(3 << 5) + 11: True, (0 << 5) + 11: False}[esp2message.body[0]]
        except KeyError:
            raise ParseError("Code is neither RRT nor TRT")
        if esp2message.body[1] != cls.org:
            raise ParseError("Not a 4BS message")
        data = esp2message.body[2:6]
        teach_in = not (data[3] & 0x08)
        if teach_in != cls.teach_in:
            raise ParseError("LRN bit does not match")
        address = esp2message.body[6:10]
        status = esp2message.body[10]
        return cls(address, status, data, outgoing)

class Regular4BSMessage(_4BSMessage):
    teach_in = False

    def __repr__(self):
        return "<%s from %s, data %s, status = 0x%02x>"%(type(self).__name__, b2a(self.address), b2a(self.data), self.status)

class TeachIn4BSMessage2(_4BSMessage):
    """A Variation 2 (LRN type 1 and nothing bidirectional) 4BS Teach-In telegram"""
    teach_in = True

    @classmethod
    def parse(cls, data):
        # The status is largely ignored, but that's consistent with the
        # documentation where it gets no mention either

        any_teach_in = super().parse(data)
        if any_teach_in.data[3] & 0xf8 != 0x80:
            # The remaining 3 bites are not described in EEP 2.6.7 (gray in
            # diagram), Eltako devices send 0x7 there
            raise ParseError("This is not a plain Variation 2 teach-in telegram")
        return any_teach_in

    profile = property(lambda self: (0xa5, self.data[0] >> 2, ((self.data[0] & 0x03) << 5) | (self.data[1] >> 3)))
    manufacturer = property(lambda self: ((self.data[1] & 0x07) << 8) | self.data[2])

    def __repr__(self):
        return "<%s from %s, profile %02x-%02x-%02x, manufacturer %d>"%(type(self).__name__, b2a(self.address), *self.profile, self.manufacturer)

class EltakoMessage(ESP2Message):
    """A control message of the Eltako bus.

    Note that these messages are proprietary to Eltako, and use the RMT and TCT
    (Receive Message Telegram, Transmit Control Telegram) h_seq values of the
    ESP2 protocol.

    This library will still try to interpret RMT/TCT telegrams as EltakoMessage
    objects because it's the only (known) use of those.

    The ORG field is used to disambiguate more detailed command types."""

    org = None # an instance attribute, no longer a property as in ESP2Message

    def __init__(self, org, address, payload=b"\0\0\0\0\0\0\0\0", is_request=True):
        self.org = org
        self.address = address
        self.payload = payload
        self.is_request = is_request

    body = property(lambda self: bytes((((5 if self.is_request else 4) << 5) + 11, self.org, *self.payload, self.address)))

    @classmethod
    def parse(cls, data):
        esp2message = super().parse(data)
        try:
            is_request = {(5 << 5) + 11: True, (4 << 5) + 11: False}[esp2message.body[0]]
        except KeyError:
            raise ParseError("Code is neither TCT nor RMT")
        org = esp2message.body[1]
        address = esp2message.body[10]
        payload = esp2message.body[2:10]
        return EltakoMessage(org, address, payload, is_request)

    def __repr__(self):
        return "<%s %s ORG %02x ADDR %02x, %s>"%(type(self).__name__, ["Response", "Request"][self.is_request], self.org, self.address, b2a(self.payload))

class EltakoWrappedRPS(ESP2Message):
    """A response to Eltako bus polling that encapsulates a RPS message; it is
    technically not a RPS message because it's sent with h_seq=TRT, but the
    rest of the message is structured like one.

    Those messages can be relayed by a FAM14 with their address shifted to its
    base address if it is configured to do so."""

    org = 0x05

    def __init__(self, address, status, data):
        self.address = address
        self.status = status
        self.data = data

    @classmethod
    def parse(cls, data):
        eltakomessage = EltakoMessage.parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != False:
            raise ParseError("This is not an %s" % (cls.__name__,))
        if any(eltakomessage.payload[1:4]):
            raise ParseError("RPS message should not carry db1..3")
        return cls(address=eltakomessage.payload[4:8], status=eltakomessage.address, data=eltakomessage.payload[0:1])

    body = property(lambda self: EltakoMessage(org=self.org, address=self.status, payload=self.data + bytes((0, 0, 0)) + self.address, is_request=False).body)

    def __repr__(self):
        return "<%s from %s, status %02x, data %s>" % (type(self).__name__, b2a(self.address), self.status, b2a(self.data))

class EltakoWrapped4BS(ESP2Message):
    """Like EltakoWrappedRPS, but the 4BS variety."""

    org = 0x07

    def __init__(self, address, status, data):
        self.address = address
        self.status = status
        self.data = data

    @classmethod
    def parse(cls, data):
        eltakomessage = EltakoMessage.parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != False:
            raise ParseError("This is not an %s" % (cls.__name__,))
        return cls(address=eltakomessage.payload[4:8], status=eltakomessage.address, data=eltakomessage.payload[0:4])

    body = property(lambda self: EltakoMessage(org=self.org, address=self.status, payload=self.data + self.address, is_request=False).body)

    def __repr__(self):
        return "<%s from %s, status %02x, data %s>" % (type(self).__name__, b2a(self.address), self.status, b2a(self.data))

class EltakoStaticMessage(EltakoMessage):
    """Base class for any kind of message that has no variance in it at all"""
    def __init__(self):
        pass

    @classmethod
    def parse(cls, data):
        eltakomessage = super().parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != cls.is_request or \
                eltakomessage.payload != cls.payload or eltakomessage.address != cls.address:
            raise ParseError("This is not an %s"%(cls.__name__,))
        return cls()

    def __repr__(self):
        return "<%s>"%type(self).__name__

class EltakoBusLock(EltakoStaticMessage):
    """A request to lock the bus (turn on the green LEDs, make senders of
    unsolicited messages like the FTS14 stop sending).

    If there is a FAM on the bus and the bus is already locked, it will respond
    with a DiscoveryReply (?; TBD: Verify the type of the response)."""
    org = 0xff
    is_request = True
    address = 0xff
    payload = b"\0\0\0\0\0\0\0\0"

class EltakoBusUnlock(EltakoStaticMessage):
    """A request to unlock the bus (reverse the effects of EltakoBusLock).

    If there is a FAM on the bus and the bus was locked, it will respond with a
    DiscoveryReply (?; TBD: Verify the type of the response)."""
    org = 0xff
    is_request = True
    address = 0x00
    payload = b"\0\0\0\0\0\0\0\0"

class _EltakoAddressOnlyMessage(EltakoMessage):
    """Base class for any kind of message with static data and varying
    address"""

    def __init__(self, address):
        self.address = address

    @classmethod
    def parse(cls, data):
        eltakomessage = super().parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != cls.is_request or \
                eltakomessage.payload != cls.payload:
            raise ParseError("This is not an EltakoDiscoveryRequest")
        return cls(eltakomessage.address)

    def __repr__(self):
        return "<%s to %s>" % (type(self).__name__, self.address)

class EltakoPoll(_EltakoAddressOnlyMessage):
    """Ask a bus participant to send its queued messages"""
    org = 0xfc
    is_request = True
    payload = b"\0\0\0\0\0\0\0\0"

class EltakoPollForced(_EltakoAddressOnlyMessage):
    """Ask a bus participant to send its status even if it is not queued for sending"""
    org = 0xfe
    is_request = True
    payload = b"\0\0\0\0\0\0\0\0"

class EltakoDiscoveryRequest(_EltakoAddressOnlyMessage):
    """Solicit a DiscoveryReply from a bus participant that has a given bus
    address. Any device in bus address learning mode will take up any
    EltakoDiscoveryRequest, answer it and assign this as its new bus
    address."""
    org = 0xf0
    is_request = True
    payload = b"\0\0\0\0\0\0\0\0"

class EltakoDiscoveryReply(EltakoMessage):
    """A data summary reporting the key parameters of a device, including its
    address, the number of slots it uses on the address bus, its memory size
    and its model number."""
    org = 0xf0
    is_request = False
    address = 0

    def __init__(self, reported_address, reported_size, memory_size, model, is_fam):
        self.reported_address = reported_address
        self.reported_size = reported_size
        self.memory_size = memory_size
        self.model = model
        self.is_fam = is_fam

    payload = property(lambda self: bytes((self.reported_address, self.reported_size, self.memory_size, 0x00 if self.is_fam else 0x08)) + self.model)

    @classmethod
    def parse(cls, data):
        eltakomessage = super().parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != cls.is_request or eltakomessage.address != cls.address:
            raise ParseError("This is not an EltakoDiscoveryReply")
        try:
            is_fam = {0x00: True, 0x08: False}[eltakomessage.payload[3]]
        except KeyError:
            raise ParseError("Assumed fixed part 00 or 08 not present (found %02x)"%eltakomessage.payload[3])
        reported_address = eltakomessage.payload[0]
        reported_size = eltakomessage.payload[1]
        memory_size = eltakomessage.payload[2]
        model = eltakomessage.payload[4:8]
        return EltakoDiscoveryReply(reported_address, reported_size, memory_size, model, is_fam)

    def __repr__(self):
        return "<%s address %d size %d, model %s%s>"%(type(self).__name__, self.reported_address, self.reported_size, b2a(self.model), " (FAM)" if self.is_fam else "")

class EltakoMemoryRequest(EltakoMessage):
    org = 0xf1
    is_request = True

    @property
    def payload(self):
        return bytes([0] * 7 + [self.row])

    def __init__(self, address, row):
        self.address = address
        self.row = row

    @classmethod
    def parse(cls, data):
        eltakomessage = super().parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != cls.is_request or \
                any(eltakomessage.payload[:7]):
            raise ParseError("This is not an EltakoMemoryRequest")
        return cls(eltakomessage.address, eltakomessage.payload[7])

    def __repr__(self):
        return "<%s address %d row %d>"%(type(self).__name__, self.address, self.row)

class EltakoMemoryResponse(EltakoMessage):
    org = 0xf1
    is_request = False

    @property
    def payload(self):
        return self.value

    @property
    def address(self):
        return self.row

    def __init__(self, row, value):
        self.row = row
        self.value = value

    @classmethod
    def parse(cls, data):
        eltakomessage = super().parse(data)
        if eltakomessage.org != cls.org or eltakomessage.is_request != cls.is_request:
            raise ParseError("This is not an EltakoMemoryResponse")
        return cls(eltakomessage.address, eltakomessage.payload)

    def __repr__(self):
        return "<%s row %d value %s>"%(type(self).__name__, self.row, b2a(self.value))

class EltakoTimeout(EltakoStaticMessage):
    org = 0xf8
    is_request = False
    payload = b"\0\0\0\0\0\0\0\0"
    address = 0
