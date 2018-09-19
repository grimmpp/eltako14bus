import asyncio
import logging
import itertools

import re

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
from eltakobus.eep import EEP, ProfileExpression, AddressExpression
from eltakobus.error import TimeoutError, ParseError, UnrecognizedUpdate

DOMAIN = 'eltako'

logger = logging.getLogger('eltako')
# To make other log levels than warn/error visible, set this in configuration.yml
#
# logger:
#   default: warning
#   logs:
#     eltako: debug
del logging # just to make sure nobody accidentally `logging.warning`s something

def into_entity_id_part(s):
    """Filter out anything that wouldn't pass by is_valid_entity_id and replace
    it with underscores. This does not take care of having a dot somewhere in
    it."""
    return re.sub(r'[^\w]', '_', s)

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

    async def wait_for_platforms(self, platforms):
        """Wait for the futures originally dealt out to the various platforms
        to come back, so that at the end there is a .platforms property that
        contains all the add_entities callbacks"""
        logger.debug("Waiting for platforms to register")
        for p in platforms:
            platforms[p] = await platforms[p]
        logger.debug("Platforms registered")
        self.platforms = platforms

    async def sweep(self, bus, programming):
        """With the bus locked, enumerate all devices on the bus, register them
        as entities and do any necessary configuration on them.

        Must only be called once because the duplicate entities created
        otherwise are not taken into consideration."""

        logger.debug("Locking bus")
        bus_status = await locking.lock_bus(bus)

        logger.debug("Bus locked (%s), enumerating devices", bus_status)

        self.entities_for_status = {}

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

            if isinstance(d, device.DimmerStyle):
                await d.ensure_direct_command_address()
                e = DimmerEntity(type(d).__name__, d, self.bus_id_part)
                self.entities_for_status[d.address] = [e]
                logger.info("Created dimmer entity for %s", d)
                self.platforms['light']([e])

                for source, profile in programming.get(d.address, {}).items():
                    logger.debug("Verifying programming %s: %s", source, profile)
                    await d.ensure_programmed(source, profile)
            elif isinstance(d, device.FSR14):
                await d.ensure_direct_command_addresses()
                for subchannel in range(d.size):
                    e = FSR14Entity(d, subchannel, self.bus_id_part)
                    self.platforms['switch']([e])
                    self.entities_for_status[d.address + subchannel] = [e]

                    for source, profile in programming.get(d.address + subchannel, {}).items():
                        logger.debug("Verifying programming on subchannel %s %s: %s", subchannel, source, profile)
                        await d.ensure_programmed(subchannel, source, profile)
                logger.info("Created FSR14 entity(s) for %s", d)
            elif isinstance(d, device.FWZ14_65A):
                serial = await d.read_serial()
                additional_state = {
                        'serial-number': serial,
                        }
                prefix = "sensor.%s_%s_%s" % (self.bus_id_part, d.address, serial.replace(' ', ''))
                e_cum = BusSensorEntity(
                        'FWZ14 65A [%s] cummulative' % d.address,
                        prefix + '_cum',
                        'kWh',
                        (0, 'energy'),
                        additional_state,
                        d,
                        )
                e_cur = BusSensorEntity(
                        'FWZ14 65A [%s] current' % d.address,
                        prefix + '_cur',
                        'W',
                        (0, 'power'),
                        additional_state,
                        d,
                        )
                self.platforms['sensor']([e_cum, e_cur])
                self.entities_for_status[d.address] = [e_cum, e_cur]
                logger.info("Created FWZ14 entities")
            else:
                continue

        logger.debug("Forcing status messages from %d known channels" % len(self.entities_for_status))
        for addr, entities in self.entities_for_status.items():
            for entity in entities:
                forced_answer = await bus.exchange(message.EltakoPollForced(addr))
                logger.debug("Answer to forced poll on %d is %s", addr, forced_answer)
                # FIXME who's responsible for making this into an RPS/4BS message?
                # This is implicit prettify use here.
                await entity.process_message(forced_answer, notify=False)

        logger.debug("Unlocking bus")
        bus_status = await locking.unlock_bus(bus)
        logger.debug("Bus unlocked (%s)", bus_status)

    async def main(self, platforms):
        await self.wait_for_platforms(platforms)

        serial_dev = self.config['eltako'].get(CONF_DEVICE)
        teachin_preconfigured = self.config['eltako'].get('teach-in', {})
        programming_config = self.config['eltako'].get('programming', {})

        programming = {k: Programming(v) for (k, v) in programming_config.items()}
        teachins = TeachInCollection(self.hass, teachin_preconfigured, programming_config, self.platforms['sensor'])

        bus = RS485SerialInterface(serial_dev, log=logger.getChild('serial'))
        self.bus_id_part = into_entity_id_part(serial_dev.replace('/dev/', ''))

        await self.initialize_bus_task(bus.run)

        logger.info("Serial device detected and ready")

        await self.sweep(bus, programming)

        logger.info("Bus ready. Full operational readiness may take a few seconds while the FAM scans the bus.")

        while True:
            await self.step(bus, teachins)

    async def step(self, bus, teachins):
        """Process a single bus message"""
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

        if address in self.entities_for_status:
            for entity in self.entities_for_status[address]:
                try:
                    await entity.process_message(msg)
                except UnrecognizedUpdate as e:
                    logger.error("Update to %s could not be processed: %s", entity, msg)
                    logger.exception(e)

            return

        # so it's not an eltakowrapped message... maybe regular 4bs/rps?
        try:
            msg = message.RPSMessage.parse(msg.serialize())
        except ParseError as e:
            pass
        else:
            teachins.feed_rps(msg)
            return

        try:
            msg = message.Regular4BSMessage.parse(msg.serialize())
        except ParseError:
            pass
        else:
            teachins.dispatch_4bs(msg)
            return

        try:
            msg = message.TeachIn4BSMessage2.parse(msg.serialize())
        except ParseError:
            pass
        else:
            teachins.feed_4bs(msg)
            return

        # It's for debug only, prettify is OK here
        msg = message.prettify(msg)
        if type(msg) not in (message.EltakoPoll, message.EltakoPollForced):
            logger.debug("Discarding message %s", message.prettify(msg))

def parse_address_profile_pair(k, v):
    """Given an address and a profile in string form as they occur in the keys
    and values of teach-in or programming lines, return them parsed or log an
    error and ignore them (returng None, None)"""

    try:
        address = AddressExpression.parse(k)
        profile = ProfileExpression.parse(v)
    except ValueError:
        logger.error('Invalid configuration entry %s: %s -- expected format is "01-23-45-67" (of "01-23-45-67 left") for addresses and "a5-02-16" for values.', k, v)
        return None, None

    return address, profile

class Programming(dict):
    def __init__(self, config):
        for k, v in config.items():
            address, profile = parse_address_profile_pair(k, v)
            if address is None:
                continue
            try:
                profile = EEP.find(profile)
            except KeyError:
                logger.warning("Unknown profile %s, not processing any further", profile)
                return
            if address is not None:
                self[address] = profile

class TeachInCollection:
    def __init__(self, hass, preconfigured, programming, add_entities_callback):
        self.hass = hass
        self._statically_known = set()
        self._announced = set()
        self._4bs_profiles = {}
        self._add_entities_callback = add_entities_callback
        self._entities = {} # address -> list of entities

        # Not only use the stored teach-in telegrams, but also the ones
        # explicitly configure to do something in any of the actuators.
        #
        # Not using the parsed Programming data because that went a step too
        # far by already resolving the profile expressions into EEPs
        items = itertools.chain(
                preconfigured.items(),
                *(p.items() for p in programming.values())
                )

        for k, v in items:
            address, profile = parse_address_profile_pair(k, v)
            if address is None:
                continue

            self._statically_known.add(address)
            if profile[0] == 0xf6:
                # not creating entities; right now they're only logged
                pass
            elif profile[0] == 0xa5:
                self.create_entity(address, profile)
            else:
                logger.error('Invalid profile %s: Only RPS and 4BS (f6-... and a5-...) supported', (profile,))

    def reset_messages(self):
        """Reset the to-be-shown messages, and rewind the _seen_rps and _4bs_profiles ... @@@"""
        self._messages_teach_in = [] # list of (address, profile) pairs
        self._messages_assignable = [] # like teach_in, but probably go into a programming section
        self._announced = set()

    def announce(self, address, profile):
        """Announce the address/profile combination to the user interface. This
        checks if it has been announced previously, but before doing so asks
        back whether the UI dismissed the notifications."""

        # Poll whether there might have been a "dismissed" event (or just never present)
        #
        # If we could get a callback here instead to clean up (would be nice),
        # then we could move the checks for already having been announced
        # outside of announce again, and especially the special case below
        # could have its checking where it is created.
        was_dismissed = self.hass.states.get('persistent_notification.eltakoteachin') is None
        if was_dismissed:
            # was not shown, or was dismissed
            logger.debug("Teach-in notification was dismissed")
            self.reset_messages()

        if address in self._announced or address in self._statically_known:
            logger.warning("Not sending: already shown")
            return
        # Special case for RPS: Don't announce fallback profiles if any more specific profile is present
        if profile == ProfileExpression((0xf6, 0x01, 0x01)):
            if any(a[0] == address[0] for a in self._announced.union(self._statically_known)):
                logger.warning("Not sending: better is known")
                return


        self._announced.add(address)

        if profile == ProfileExpression((0xf6, 0x02, 0x01)) and address[1] in ('left', 'right'):
            self._messages_assignable.append((address, profile))
        else:
            self._messages_teach_in.append((address, profile))

        if self._messages_teach_in:
            teach_in_part = "<br />  teach-in:<br />""" + \
                "<br />".join(
                    '    "%s": "%s"' % (a, p) for (a, p) in self._messages_teach_in
                )
        else:
            teach_in_part = ""

        if self._messages_assignable:
            programming_part = "<br />  programming:<br />    <i>some channel number</i>:<br />""" + \
                "<br />".join(
                    '      "%s": "%s"' % (a, p) for (a, p) in self._messages_assignable
                )
        else:
            programming_part = ""

        full_text = """To make the resulting sensors persistent and remove this
            message, append the following lines in your
            <code>configuration.yaml</code> file:
            <pre>eltako:""" + teach_in_part + programming_part + """</pre>"""

        if programming_part:
            full_text += """where the channel number can be picked from the
                <code>eltako-bus-address</code> property of supported
                actuators."""

        self.hass.components.persistent_notification.async_create(
                full_text,
                title="New EnOcean devices detected",
                notification_id="eltako-teach-in"
                )

    def feed_4bs(self, msg):
        address = AddressExpression((msg.address, None))
        profile = ProfileExpression(msg.profile)

        if msg.address not in self._4bs_profiles:
            self.create_entity(address, profile)

        self.announce(address, profile)

    def feed_rps(self, msg):
        if msg.data[0] in (0x30, 0x20): # a left key
            address = AddressExpression((msg.address, "left"))
            profile = ProfileExpression((0xf6, 0x02, 0x01))
        elif msg.data[0] in (0x50, 0x70): # a right key
            address = AddressExpression((msg.address, "right"))
            profile = ProfileExpression((0xf6, 0x02, 0x01))
        else:
            address = AddressExpression((msg.address, None))
            # or any other F6 profile, I'm out of heuristics here
            profile = ProfileExpression((0xf6, 0x01, 0x01))

        self.announce(address, profile)

    def create_entity(self, address: AddressExpression, profile: ProfileExpression):
        """Create and register appropriate entity(ies) based on an address and
        profile obtained from a teach-in telegram or configuration"""

        a_plain = address.plain_address()
        try:
            eep = EEP.find(profile)
        except KeyError:
            logger.error("No EEP support available for %s, ignoring values from that sensor", profile)
            self._4bs_profiles[a_plain] = None # don't report again
            return

        self._4bs_profiles[a_plain] = eep

        field_to_unit = {
                'temperature': '°C',
                'humitity': '%',
                'wind speed': 'm/s',
                'illuminance (dawn)': 'lux',
                'illuminance (west)': 'lux',
                'illuminance (central)': 'lux',
                'illuminance (east)': 'lux',
                }
        for field in eep.fields:
            entity_class = type("CustomSensor", (Entity,), {
                "poll": False,
                "name": "%s Sensor %s" % (field.capitalize(), address),
                "entity_id": "sensor.enocean_%s_%s" % (str(address).replace('-', ''), into_entity_id_part(field)),
                "state": None,
                "assumed_state": True,
                "unit_of_measurement": field_to_unit.get(field, ''),
                "state_attributes": {'enocean-address': str(address), 'enocean-profile': str(profile)},
                })
            instance = entity_class()
            self._entities.setdefault(a_plain, {})[field] = instance
            self._add_entities_callback([instance])

    def dispatch_4bs(self, msg):
        try:
            profile = self._4bs_profiles[msg.address]
        except KeyError:
            logger.warning("4BS from unknown source %s, discarding", b2a(msg.address))
            return

        if profile is None:
            # "No EEP support available for..." was already returned
            return

        try:
            decoded = profile.decode(msg.data)
            if not isinstance(decoded, dict):
                # Could duck-typingly check, but meh
                raise ValueError("decode function did not return a dictionary")
        except Exception as e:
            logger.error("Failed to decode 4BS message %s according to %s; continuing normally", msg, profile)
            logger.exception(e)

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

    entity_id = None # set in constructor
    name = property(lambda self: self._name)

class DimmerEntity(EltakoEntity, Light):
    def __init__(self, typename, busobject, bus_id_part):
        self.busobject = busobject
        self.entity_id = "light.%s_%s" % (bus_id_part, busobject.address)
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
        base = super().state_attributes or {}
        return {**base,
                'eltako-bus-address': self.busobject.address,
                'eltako-bus-address-base': self.busobject.address,
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
    def __init__(self, busobject, subchannel, bus_id_part):
        self.busobject = busobject
        self.subchannel = subchannel
        self.entity_id = "switch.%s_%s" % (bus_id_part, busobject.address + subchannel)
        self._name = "%s [%s/%s]" % (type(busobject).__name__, busobject.address, subchannel)
        self._state = None

    @property
    def is_on(self):
        return self._state

    @property
    def assumed_state(self):
        return self._state is None

    @property
    def state_attributes(self):
        base = super().state_attributes or {}
        return {**base,
                'eltako-bus-address': self.busobject.address + self.subchannel,
                'eltako-bus-address-base': self.busobject.address,
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

class BusSensorEntity(EltakoEntity, Entity):
    # no I don't want to implement a property right now; the first two also
    # serve as default values
    state = None
    assumed_state = True
    unit_of_measurement = None

    def __init__(self, name, entity_id, unit, update_to_state_key, additional_state, busobject):
        self.entity_id = entity_id
        self._name = name
        self.unit_of_measurement = unit
        self.update_to_state_key = update_to_state_key
        self.additional_state = additional_state
        self.busobject = busobject

    @property
    def state_attributes(self):
        base = super().state_attributes or {}
        return {**base,
                **self.additional_state,
                'eltako-bus-address': self.busobject.address,
                'eltako-bus-address-base': self.busobject.address,
                'eltako-device-version': ".".join(map(str, self.busobject.version)),
                }

    async def process_message(self, msg, notify=True):
        processed = self.busobject.interpret_status_update(msg)
        if not processed:
            return
        energy = processed.pop(self.update_to_state_key, None)
        if energy is not None:
            self.assumed_state = False
            self.state = energy
            self.async_schedule_update_ha_state(False)
