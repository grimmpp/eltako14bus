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
# To make other log levels than warn/error visible, set this in configuration.yml
#
# logger:
#   default: warning
#   logs:
#     eltako: debug

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

    light_entities = []
    entities_for_status = {}

    bus_devices = {}
    for i in range(1, 256):
        try:
            d = await device.create_busobject(bus, i)
        except TimeoutError:
            continue

        # reading ahead so all the configuration data needed during
        # find_direct_command_address and similar are available at once
        await d.read_mem()
        # reading ahead all polling state so we never end up with
        # registered bus objects having an assumed state
        # await d.force_poll_once()
        bus_devices[i] = d

        # Creating the entities while the bus is locked so they can process
        # their initial messages right away

        if isinstance(d, device.FUD14):
            e = FUD14Entity(d, "%s-%s" % (serial_dev.replace('/', '-').lstrip('-'), i))
            light_entities.append(e)
        else:
            continue

        logging.info("Found entity %s, asking for initial state", e)

        for scan_address in range(d.address, d.address + d.size):
            forced_answer = await bus.exchange(message.EltakoPollForced(scan_address))
            # FIXME who's responsible for making this into an RPS/4BS message?
            await e.process_message(forced_answer, notify=False)

            # Future messages go here as well
            entities_for_status[scan_address] = e

    logger.debug("Found %d devices on the bus, unlocking bus", len(bus_devices))
    try:
        await bus.exchange(message.EltakoBusUnlock(), message.EltakoDiscoveryReply)
    except TimeoutError:
        raise RuntimeError("FAM14 did not acknowledge release of bus, please make sure it's in mode 2 or 3.")

    logger.info("Injecting entities for found devices")

    add_light_entities = await platforms['light']
    add_light_entities(light_entities)
    del light_entities

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

        if address in entities_for_status:
            await entities_for_status[address].process_message(msg)
        else:
            # It's for debug only, prettify is OK here
            msg = message.prettify(msg)
            if type(msg) not in (message.EltakoPoll, message.EltakoPollForced):
                logger.debug("Discarding message %s", message.prettify(msg))

class FUD14Entity(Light):
    poll = False

    def __init__(self, busobject, unique_id):
        self.busobject = busobject
        self._unique_id = unique_id
        self._name = "FUD14 [%s]" % busobject.address
        self._state = None

        # would need to do that outside, and even then 
        # self._writable = await self.busobject.find_direct_command_address() is not None

    unique_id = property(lambda self: self._unique_id)
    name = property(lambda self: self._name)

    @property
    def is_on(self):
        return self._state != 0

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS

    @property
    def brightness(self):
        return self._state

    @property
    def assumed_state(self):
        return self._state is None

    @property
    def state_attributes(self):
        base = super().state_attributes
        return {**base,
                'eltako-bus-address': self.busobject.address,
                'eltako-bus-size': self.busobject.size,
                'eltako-device-version': ".".join(map(str, self.busobject.version)),
                }

    async def process_message(self, msg, notify=True):
        self._state = msg.data[1]
        if notify:
            self.async_schedule_update_ha_state(False)

    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
        else:
            brightness = 255
        await self.busobject.set_state(brightness)

    async def async_turn_off(self, **kwargs):
        await self.busobject.set_state(0)

# next steps: make .read_mem() store the memory dump in self too (or make it a
# memo access), move update parser in there and make brightness setting methods. then all that's left for this part is to split up BusObject devices into their entity aspects.
