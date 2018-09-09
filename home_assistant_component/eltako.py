import asyncio
import logging

from homeassistant.const import CONF_DEVICE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import discovery

from homeassistant.components.light import Light, SUPPORT_BRIGHTNESS, ATTR_BRIGHTNESS

# until eltakobus is published, pull in its dependencies:
REQUIREMENTS = ['pyserial_asyncio', 'pyserial >= 3.4']
import sys
sys.path.append(__file__[:__file__.rfind('/')])
from eltakobus.serial import RS485SerialInterface
from eltakobus import device
from eltakobus import message
from eltakobus.error import TimeoutError, ParseError

DOMAIN = 'eltako'

logger = logging.getLogger('eltako')
# setLevel still does not make things show in log viewer
logger.debug = logger.warn
logger.info = logger.error

async def async_setup(hass, config):
    loop = asyncio.get_event_loop()

    serial_dev = config['eltako'].get(CONF_DEVICE)

    platforms = ['light']
    platforms = {k: asyncio.Future() for k in platforms}

    asyncio.ensure_future(wrapped_main(loop, serial_dev, platforms), loop=loop)

    for platform, f in platforms.items():
        # recorder creates an error message around this because "Object of type
        # 'Future' is not JSON serializable", which is no big surprise, but
        # that does not seem to harm much.
        await discovery.async_load_platform(
                hass,
                platform,
                DOMAIN,
                {'add_entities': f},
                config
                )

    return True

async def wrapped_main(*args):
    try:
        await main(*args)
    except Exception as e:
        logger.exception(e)
        # FIXME should I just restart with back-off?

async def main(loop, serial_dev, platforms):
    bus = RS485SerialInterface(serial_dev)

    bus_ready = asyncio.Future()
    asyncio.ensure_future(bus.run(loop, conn_made=bus_ready), loop=loop)
    await bus_ready

    logger.info("Bus ready")

    logger.debug("Locking bus")
    for i in range(20):
        try:
            response = await bus.exchange(message.EltakoBusLock(), message.EltakoDiscoveryReply)
            if not response.is_fam:
                # typically happens when FAM is just scanning and we get one of
                # its replies back rather than its "OK I'm locked"
                continue
        except TimeoutError:
            continue

    logger.debug("Bus locked, enumerating devices")

    bus_devices = {}
    bus_memory = {}
    for i in range(1, 256):
        try:
            d = await device.create_busobject(bus, i)
        except TimeoutError:
            continue
        else:
            bus_devices[i] = d
            bus_memory[i] = await d.read_mem()

    logger.debug("Found %d devices, unlocking bus", len(bus_devices))

    try:
        await bus.exchange(message.EltakoBusUnlock(), message.EltakoDiscoveryReply)
    except TimeoutError:
        raise RuntimeError("FAM14 did not acknowledge release of bus, please make sure it's in mode 2 or 3.")

    logger.info("Creating entities for found devices")

    entities = {}

    for i, bd in bus_devices.items():
        if isinstance(bd, device.FUD14):
            e = FUD14Entity(bd, bus_memory[i], "%s-%s" % (serial_dev.replace('/', '-').lstrip('-'), i))
            entities[i] = e

            add_light_entities = await platforms['light']
            add_light_entities([e])

    while True:
        msg = await bus.received.get()

        address = None
        try:
            msg = message.EltakoWrappedRPS.parse(msg.serialize())
        except ParseError:
            pass
        else:
            address = msg.address[-1]
        try:
            msg = message.EltakoWrapped4BS.parse(msg.serialize())
        except ParseError:
            pass
        else:
            address = msg.address[-1]

        if address in entities:
            await entities[address].process_message(msg)
        else:
            try:
                msg = message.EltakoPoll.parse(msg.serialize())
            except ParseError:
                pass
            else:
                continue
            try:
                msg = message.EltakoPollForced.parse(msg.serialize())
            except ParseError:
                pass
            else:
                continue
            logger.debug("Discarding message %s", msg)

class FUD14Entity(Light):
    poll = False

    def __init__(self, busobject, busmem, dev_id):
        self.busobject = busobject
        self.dev_id = dev_id
        self._name = "FUD14 [%s]" % busobject.address
        self._state = None

        logger.error("Device ID is %s", dev_id)

        self.dim_message = None

        for line in busmem[12:128]:
            sender = line[:4]
            function = line[5]
            if function == 32:
                self.dim_message = lambda val: message.ESP2Message(b"\x0b\x07\x02" + bytes([val]) + b"\0\x09" + sender + b"\0")

    @property
    def name(self):
        return self._name

    @property
    def is_on(self):
        return self._state != 0

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS

    @property
    def brightness(self):
        return self._state * 255 / 100

    async def process_message(self, msg):
        self._state = msg.data[1]
        self.async_schedule_update_ha_state(False)

    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
        else:
            brightness = 255
        await self.busobject.bus.exchange(self.dim_message(brightness), message.EltakoTimeout)

    async def async_turn_off(self, **kwargs):
        await self.busobject.bus.exchange(self.dim_message(0), message.EltakoTimeout)

# next steps: make .read_mem() store the memory dump in self too (or make it a
# memo access), move update parser in there and make brightness setting methods. then all that's left for this part is to split up BusObject devices into their entity aspects.
