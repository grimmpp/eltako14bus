import asyncio
import logging

from homeassistant.const import CONF_DEVICE
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers import discovery

from homeassistant.components.light import Light, SUPPORT_BRIGHTNESS, ATTR_BRIGHTNESS
from homeassistant.components.switch import SwitchDevice
from homeassistant.helpers.entity import Entity

# until eltakobus is published, pull in its dependencies:
REQUIREMENTS = ['pyserial_asyncio', 'pyserial >= 3.4']
import sys
sys.path.append(__file__[:__file__.rfind('/')])
from eltakobus.serial import RS485SerialInterface
from eltakobus.util import b2a
from eltakobus import device
from eltakobus import message
from eltakobus import locking
from eltakobus.eep import EEP
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

    global platforms
    assert platforms == {}
    platforms = {k: asyncio.Future() for k in ('light', 'switch', 'sensor')}
    for platform, f in platforms.items():
        await discovery.async_load_platform(
                hass,
                platform,
                DOMAIN,
                {},
                config
                )

    ctrl = EltakoBusController(hass, loop, config, platforms)

    return True

class EltakoBusController:
    def __init__(self, hass, loop, config, platforms):
        self.loop = loop
        self.hass = hass
        self.config = config
        self._main_task = asyncio.ensure_future(self.wrapped_main(platforms), loop=loop)
        self._bus_task = None

    async def initialize_bus_task(self, run):
        """Call bus.run in a task that takes down main if it crashes, and is
        properly shut down as well"""
        if self._bus_task is not None:
            self._bus_task.cancel()

        conn_made = asyncio.Future()
        self._bus_task = asyncio.ensure_future(run(self.loop, conn_made=conn_made))
        def bus_done(bus_future, _main=self._main_task):
            self._bus_task = None
            try:
                result = bus_future.result()
            except Exception as e:
                logger.error("Bus task terminated with %s, removing main task", bus_future.exception())
                logger.exception(e)
            else:
                logger.error("Bus task terminated with %s (it should have raised an exception instead), removing main task", result)
            _main.cancel()
        self._bus_task.add_done_callback(bus_done)
        await conn_made

    async def wrapped_main(self, *args):
        try:
            await self.main(*args)
        except Exception as e:
            logger.exception(e)
            # FIXME should I just restart with back-off?

        if self._bus_task is not None:
            self._bus_task.cancel()

    async def main(self, platforms):
        logger.debug("Waiting for platforms to register")
        for p in platforms:
            platforms[p] = await platforms[p]
        logger.debug("Platforms registered")


        serial_dev = self.config['eltako'].get(CONF_DEVICE)
        teachin_preconfigured = self.config['eltako'].get('teach-in', {})

        teachins = TeachInCollection(self.hass, teachin_preconfigured, platforms['sensor'])


        bus = RS485SerialInterface(serial_dev, log=logger.getChild('serial'))
        unique_id_prefix = serial_dev.replace('/', '-').lstrip('-')

        await self.initialize_bus_task(bus.run)

        logger.info("Serial device detected and ready")

        logger.debug("Locking bus")
        bus_status = await locking.lock_bus(bus)

        logger.debug("Bus locked (%s), enumerating devices", bus_status)

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

            if isinstance(d, device.FUD14) or isinstance(d, device.FSG14_1_10V):
                e = DimmerEntity(type(d).__name__, d, unique_id_prefix)
                entities_for_status[d.address] = e
                logger.info("Created dimmer entity for %s", d)
                platforms['light']([e])
            elif isinstance(d, device.FSR14):
                for subchannel in range(d.size):
                    e = FSR14Entity(d, subchannel, unique_id_prefix)
                    platforms['switch']([e])
                    entities_for_status[d.address + subchannel] = e
                logger.info("Created FSR14 entity(s) for %s", d)
            else:
                continue

        logger.debug("Forcing status messages from %d known channels" % len(entities_for_status))
        for addr, entity in entities_for_status.items():
            forced_answer = await bus.exchange(message.EltakoPollForced(addr))
            logger.debug("Answer to forced poll on %d is %s", addr, forced_answer)
            # FIXME who's responsible for making this into an RPS/4BS message?
            # This is implicit prettify use here.
            await entity.process_message(forced_answer, notify=False)

        logger.debug("Unlocking bus")
        bus_status = await locking.unlock_bus(bus)
        logger.debug("Bus unlocked (%s)", bus_status)

        logger.debug("Injecting entities for found devices")

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
                continue

            # so it's not an eltakowrapped message... maybe regular 4bs/rps?
            try:
                msg = message.RPSMessage.parse(msg.serialize())
            except ParseError as e:
                pass
            else:
                teachins.feed_rps(msg)
                continue

            try:
                msg = message.Regular4BSMessage.parse(msg.serialize())
            except ParseError:
                pass
            else:
                teachins.dispatch_4bs(msg)
                continue

            try:
                msg = message.TeachIn4BSMessage2.parse(msg.serialize())
            except ParseError:
                pass
            else:
                teachins.feed_4bs(msg)
                continue

            # It's for debug only, prettify is OK here
            msg = message.prettify(msg)
            if type(msg) not in (message.EltakoPoll, message.EltakoPollForced):
                logger.debug("Discarding message %s", message.prettify(msg))

class TeachInCollection:
    def __init__(self, hass, preconfigured, add_entities_callback):
        self.hass = hass
        self._seen_rps = set()
        self._seen_4bs = {}
        self._messages = [] # list of (address, profile) pairs
        self._add_entities_callback = add_entities_callback
        self._entities = {} # address -> list of entities

        for k, v in preconfigured.items():
            try:
                address = bytes(int(x, 16) for x in k.split('-'))
                profile = tuple(int(x, 16) for x in v.split('-'))
                if len(profile) != 3 or len(address) != 4:
                    raise ValueError
            except ValueError:
                logger.error('Invalid configuration entry %s: %s -- expected format is "01-23-45-67" for addresses and "a5-02-16" for values.', k, v)
                continue

            if profile[0] == 0xf6:
                self._seen_rps.append(address)
                # not creating entities; right now they're only logged
            elif profile[0] == 0xa5:
                self.create_entity(address, profile)
            else:
                logger.error('Invalid profile %s: Only RPS and 4BS (f6-... and a5-...) supported', "-".join("%02x" % x for x in profile))

    def announce(self, address, profile):
        self._messages.append((address, profile))
        self.hass.components.persistent_notification.async_create(
                """To make the resulting sensors persistent and remove this message, append the following lines in your <code>configuration.yaml</code> file:
                <pre>eltako:<br />  teach-in:<br />""" +
                "<br />".join('    "%02x-%02x-%02x-%02x": "%02x-%02x-%02x"' % (*m[0], *m[1]) for m in self._messages) +
                """</pre>""",
                title="New EnOcean devices detected",
                notification_id="eltako-teach-in"
                )

    def feed_4bs(self, msg):
        if msg.address not in self._seen_4bs:
            self.announce(msg.address, msg.profile)
            self.create_entity(msg.address, msg.profile)

    def feed_rps(self, msg):
        if msg.address not in self._seen_rps:
            self._seen_rps.add(msg.address)
            self.announce(msg.address, (0xf6, 0x02, 0x01))
            # not creating entities; right now they're only logged

    def create_entity(self, address, profile):
        """Create and register appropriate entity(ies) based on an address and
        profile obtained from a teach-in telegram or configuration"""

        try:
            eep = EEP.find(profile)
        except KeyError:
            logger.error("No EEP support available for %s, ignoring values from that sensor", "-".join("%02x" % x for x in profile))
            self._seen_4bs[address] = None # don't report again
            return

        self._seen_4bs[address] = eep

        field_to_unit = {
                'temperature': '°C',
                'humitity': '%',
                }
        for field in eep.fields:
            entity_class = type("CustomSensor", (Entity,), {
                "poll": False,
                "name": "%s Sensor %s" % (field.capitalize(), b2a(address)),
                "entity_id": "sensor.enocean.%s-%s" % (b2a(address).replace(' ', ''), field),
                "unique_id": "sensor.enocean.%s-%s" % (b2a(address).replace(' ', ''), field),
                "state": None,
                "assumed_state": True,
                "unit_of_measurement": field_to_unit.get(field, ''),
                "state_attributes": {'enocean-address': b2a(address), 'enocean-profile': b2a(bytes(profile)).replace(' ', '-')},
                })
            instance = entity_class()
            self._entities.setdefault(address, {})[field] = instance
            self._add_entities_callback([instance])

    def dispatch_4bs(self, msg):
        try:
            profile = self._seen_4bs[msg.address]
        except KeyError:
            logger.warning("4BS from unknown source %s, discarding", b2a(msg.address))
            return

        decoded = profile.decode(msg.data)

        # Apply some rounding while home assistant does not know of precisison
        # or sane rounding
        field_to_round = {
                'temperature': lambda v: round(v, 1),
                'humidity': lambda v: round(v, 1),
                }

        for k, v in decoded.items():
            entity = self._entities[msg.address][k]
            entity.assumed_state = False
            entity.state = field_to_round.get(k, lambda x:x)(v)
            entity.async_schedule_update_ha_state(False)

class EltakoEntity:
    poll = False

    unique_id = property(lambda self: self._unique_id)
    name = property(lambda self: self._name)

class DimmerEntity(EltakoEntity, Light):
    def __init__(self, typename, busobject, unique_id_prefix):
        self.busobject = busobject
        self._unique_id = "%s-%s" % (unique_id_prefix, busobject.address)
        self._name = "%s [%s]" % (typename, busobject.address)
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
            logger.debug("Read brightness as %s", self._state)
            if notify:
                self.async_schedule_update_ha_state(False)
    async def async_turn_on(self, **kwargs):
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
        else:
            brightness = 255
        brightness = brightness * 100 / 255
        logger.debug("Setting brightness to %s", brightness)
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
