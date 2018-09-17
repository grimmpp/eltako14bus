import asyncio
import logging

from homeassistant.const import CONF_DEVICE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import discovery

from homeassistant.components.light import Light, SUPPORT_BRIGHTNESS, ATTR_BRIGHTNESS
from homeassistant.components.switch import SwitchDevice

# until eltakobus is published, pull in its dependencies:
REQUIREMENTS = ['pyserial_asyncio', 'pyserial >= 3.4']
import sys
sys.path.append(__file__[:__file__.rfind('/')])
from eltakobus.serial import RS485SerialInterface
from eltakobus import device
from eltakobus import message
from eltakobus import locking
from eltakobus.error import TimeoutError, ParseError, UnrecognizedUpdate

DOMAIN = 'eltako'

logger = logging.getLogger('eltako')
# To make other log levels than warn/error visible, set this in configuration.yml
#
# logger:
#   default: warning
#   logs:
#     eltako: debug

# Passing the futures around in a global rather than in discovery_info because
# recorder would try to serialize discovery_info and die from it. (Showing a
# "Object of type 'Future' is not JSON serializable" error, nothing else bad
# happens at first, but I suspect that history is unavailable when that
# happened.)
platforms = {}

async def async_setup(hass, config):
    loop = asyncio.get_event_loop()

    serial_dev = config['eltako'].get(CONF_DEVICE)

    global platforms
    assert platforms == {}
    platforms = {k: asyncio.Future() for k in ('light', 'switch')}

    asyncio.ensure_future(wrapped_main(loop, serial_dev, platforms), loop=loop)

    for platform, f in platforms.items():
        await discovery.async_load_platform(
                hass,
                platform,
                DOMAIN,
                {},
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
    unique_id_prefix = serial_dev.replace('/', '-').lstrip('-')

    bus_ready = asyncio.Future()
    asyncio.ensure_future(bus.run(loop, conn_made=bus_ready), loop=loop)
    await bus_ready

    logger.info("Serial device detected and ready")

    logger.debug("Locking bus")
    bus_status = await locking.lock_bus(bus)

    logger.debug("Bus locked (%s), enumerating devices", bus_status)

    light_entities = []
    switch_entities = []
    entities_for_status = {}

    for i in range(1, 256):
        try:
            d = await device.create_busobject(bus, i)
        except TimeoutError:
            continue

        logger.debug("Found device %s", d)

        # reading ahead so all the configuration data needed during
        # find_direct_command_address and similar are available at once
        try:
            await d.read_mem()
        except TimeoutError:
            logger.info("Device %s announces readable memory but does not permit readouts", d)

        # Creating the entities while the bus is locked so they can process
        # their initial messages right away

        if isinstance(d, device.FUD14):
            e = FUD14Entity(d, unique_id_prefix)
            light_entities.append(e)
            entities_for_status[d.address] = e
            logger.info("Created FUD14 entity for %s", d)
        elif isinstance(d, device.FSR14):
            for subchannel in range(d.size):
                e = FSR14Entity(d, subchannel, unique_id_prefix)
                switch_entities.append(e)
                entities_for_status[d.address + subchannel] = e
            logger.info("Created FSR14 entity(s) for %s", d)
        else:
            continue

    logger.debug("Forcing status messages from %d known channels" % len(entities_for_status))
    for addr, entity in entities_for_status.items():
        forced_answer = await bus.exchange(message.EltakoPollForced(addr))
        # FIXME who's responsible for making this into an RPS/4BS message?
        # This is implicit prettify use here.
        await entity.process_message(forced_answer, notify=False)

    logger.debug("Unlocking bus")
    bus_status = await locking.unlock_bus(bus)
    logger.debug("Bus unlocked (%s)", bus_status)

    logger.debug("Injecting entities for found devices")

    add_light_entities = await platforms['light']
    add_light_entities(light_entities)
    add_switch_entities = await platforms['switch']
    add_switch_entities(switch_entities)
    del light_entities, switch_entities

    logger.info("Bus ready. Full operational readiness may take a few seconds while the FAM scans the bus.")

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
            try:
                await entities_for_status[address].process_message(msg)
            except UnrecognizedUpdate as e:
                logger.warn("Update to %s could not be processed: %s", address, msg)
                logger.exception(e)
        else:
            # It's for debug only, prettify is OK here
            msg = message.prettify(msg)
            if type(msg) not in (message.EltakoPoll, message.EltakoPollForced):
                logger.debug("Discarding message %s", message.prettify(msg))

class EltakoEntity:
    poll = False

    unique_id = property(lambda self: self._unique_id)
    name = property(lambda self: self._name)

class FUD14Entity(EltakoEntity, Light):
    def __init__(self, busobject, unique_id_prefix):
        self.busobject = busobject
        self._unique_id = "%s-%s" % (unique_id_prefix, busobject.address)
        self._name = "FUD14 [%s]" % busobject.address
        self._state = None

        # would need to do that outside, and even then 
        # self._writable = await self.busobject.find_direct_command_address() is not None

    @property
    def is_on(self):
        return self._state != 0

    @property
    def supported_features(self):
        return SUPPORT_BRIGHTNESS

    @property
    def brightness(self):
        if self._state is None:
            # see assumed_state
            return 0
        return self._state * 255 / 100

    @property
    def assumed_state(self):
        return self._state is None

    @property
    def state_attributes(self):
        base = super().state_attributes
        return {**base,
                'eltako-bus-address': self.busobject.address,
                'eltako-device-version': ".".join(map(str, self.busobject.version)),
                }

    async def process_message(self, msg, notify=True):
        processed = self.busobject.interpret_status_update(msg)
        if 'dim' in processed:
            self._state = processed['dim']
            logger.debug("Read FUD14 brightness as %s", self._state)
            if notify:
                self.async_schedule_update_ha_state(False)

    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
        else:
            brightness = 255
        brightness = brightness * 100 / 255
        logger.debug("Setting FUD14 to %s", brightness)
        await self.busobject.set_state(brightness)

    async def async_turn_off(self, **kwargs):
        await self.busobject.set_state(0)

class FSR14Entity(EltakoEntity, SwitchDevice):
    def __init__(self, busobject, subchannel, unique_id_prefix):
        self.busobject = busobject
        self.subchannel = subchannel
        self._unique_id = "%s-%s-%s" % (unique_id_prefix, busobject.address, subchannel)
        self._name = "FSR14 [%s/%s]" % (busobject.address, subchannel)
        self._state = None

    @property
    def is_on(self):
        return self._state

    @property
    def assumed_state(self):
        return self._state is None

    @property
    def state_attributes(self):
        base = super().state_attributes
        return {**base,
                'eltako-bus-address': self.busobject.address,
                'eltako-bus-address-subchannel': self.subchannel,
                'eltako-device-version': ".".join(map(str, self.busobject.version)),
                }

    async def process_message(self, msg, notify=True):
        processed = self.busobject.interpret_status_update(msg)
        if self.subchannel in processed:
            self._state = processed[self.subchannel]
            if notify:
                self.async_schedule_update_ha_state(False)

    async def async_turn_on(self, **kwargs):
        await self.busobject.set_state(self.subchannel, True)

    async def async_turn_off(self, **kwargs):
        await self.busobject.set_state(self.subchannel, False)
