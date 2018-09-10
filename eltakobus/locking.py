import asyncio

from .message import *
from .error import *

LOCKED = "Bus was successfully locked as acknowledged by a FAM"
PROBABLY_LOCKED = "No response after 10 repetitions, assuming that no FAM is present on the bus"

async def lock_bus(bus):
    """Lock the bus. While this is being done, no other program component
    should drain the receive queue."""
    largest_seen_discovery_request = 0
    def seen(msg):
        try:
            msg = EltakoDiscoveryRequest.parse(msg.serialize())
        except ParseError:
            return

        nonlocal largest_seen_discovery_request
        if msg.address < largest_seen_discovery_request:
            raise BadFAMMode1
        largest_seen_discovery_request = msg.address

    for i in range(20):
        largest_before = largest_seen_discovery_request - 1
        # Inner loop: Don't count up the attempts as long as the FAM makes progress
        while largest_before != largest_seen_discovery_request:
            largest_before = largest_seen_discovery_request

            while not bus.received.empty():
                seen(bus.received.get_nowait())

            try:
                response = await bus.exchange(EltakoBusLock(), EltakoDiscoveryReply)
            except TimeoutError:
                # Give the FAM time to make progress
                await asyncio.sleep(0.2)
                continue

            if response.is_fam:
                return LOCKED
    return PROBABLY_LOCKED

UNLOCKED = "Bus was successfully unlocked as acknowledged by a FAM"
PROBABLY_UNLOCKED = "No response to unlock, assuming that no FAM is present on the bus or the bus was not locked before"

async def unlock_bus(bus):
    response = await bus.exchange(EltakoBusUnlock(), EltakoMessage)

    try:
        response = EltakoDiscoveryReply.parse(response.serialize())
    except ParseError:
        pass
    else:
        if response.is_fam:
            return UNLOCKED

    return PROBABLY_UNLOCKED
