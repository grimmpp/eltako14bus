from typing import *
import abc
import pickle

from .error import ParseError, TimeoutError
from .message import EltakoMemoryRequest, EltakoMemoryResponse, EltakoMessage, prettify

class BusInterface(metaclass=abc.ABCMeta):
    async def exchange(self, request, responsetype=None):
        """Send a request and get back a response. The response will be of
        responsetype or (if None) any suitable ESP2Message subclass. If the
        response type fails to parse the response because it is a timeout, a
        TimeoutError will be raised instead of the expected ParseError.

        The default implementation defers to base_exchange, but drivers are
        invited to implement exchange in full if they can."""

        response = await self.base_exchange(request)

        if responsetype is None:
            return prettify(ESP2Message.parse(response))

        try:
            return responsetype.parse(response)
        except ParseError:
            try:
                EltakoTimeout.parse(response)
            except ParseError:
                pass
            else:
                raise TimeoutError
            raise

    async def send(self, request):
        """Send a request without expecting a response.

        The default implementation defers to base_exchange, but drivers are
        invited to implement exchange in full if they can."""
        await self.base_exchange(request)

    @abc.abstractmethod
    async def base_exchange(self, request):
        """Exchange function without responsetype bells and whistles, returns
        only the first resulting payload.

        Right now, everyone implements this -- if it becomes practical that a
        BusInterface does not, this function here should start raising
        NotImplementedError, and users should fall back to
        exchange().serialize(), or maybe this should provide that here."""

    async def read_mem(self, address, known_memory_size=None) -> Tuple[bytes]:
        """Return the complete memory content of the bus participant with the
        given address, as queried with F1 messages."""

        memory_size = known_memory_size or 255

        # FIXME more stringent error handling / message type filtering
        data = []
        for j in range(memory_size + 1):
            response = await self.exchange(EltakoMemoryRequest(address, j), EltakoMemoryResponse)
            data.append(response.value)
        return tuple(data)


class ReadaheadMixin:
    """While this technically inherits from BusInterface alone, it is only
    practical in connection with a BusCache because otherwise the obtained data
    is immediately lost again"""

    async def base_exchange(self, request):
        pretty = prettify(request)
        if isinstance(pretty, EltakoMemoryRequest):
            full = await self.read_mem(pretty.address)
            return EltakoMemoryResponse(pretty.row, full[pretty.row]).serialize()

        return await super(ReadaheadMixin, self).base_exchange(request)

# this approach won't work exactly like that, because memory can both be
# written in full or line-wise from PCT; furthermore, there are too many
# timeouts around yet, so there is probably something else fishy.
#
# a better approach would spool all writes and flush them timeout-based, or
# before the next incompatible write comes along.
#
#class WriteDelayer(BusInterface):
#    def __init__(self, *args, **kwargs):
#        super(WriteDelayer, self).__init__(*args, **kwargs)
#        self.spool = []
#
#    async def base_exchange(self, request):
#        pretty = prettify(request)
#        if pretty.org == 0xf2 or pretty.org == 0xf4:
#            print("postponing write operation %s"%request)
#            if pretty.org == 0xf4 and pretty.address == 0x7f:
#                print("Flushing out the write operations now")
#                retries = 3
#                while self.spool:
#                    await asyncio.sleep(0.5)
#                    next_request = self.spool[0]
#                    response = prettify(ESP2Message.parse(await super(WriteDelayer, self).base_exchange(next_request)))
#                    print("%s - %s"%(prettify(next_request), response))
#                    if isinstance(response, EltakoTimeout):
#                        if retries:
#                            retries -= 1
#                            continue
#                        else:
#                            raise Exception("Too many timeouts in write sequence")
#                    else:
#                        self.spool.pop(0)
#                        retries = 3
#                response = await super(WriteDelayer, self).base_exchange(request)
#                print("Flushing complete; you can probably ignore the error the flashing software gave you")
#                return response
#            else:
#                self.spool.append(request)
#
#            return EltakoMessage(pretty.org, pretty.address, pretty.payload, not pretty.is_request).serialize()
#        else:
#            return await super(WriteDelayer, self).base_exchange(request)

class BusCache(BusInterface):
    """Basic store of attributes on the bus that are not expected to change.

    This class takes care of the actual caching logic, but relies on subclasss
    to provide storage.

    The whole locking area is handled as follows: As long as the bus is not
    locked (and it is assumed that the bus is not locked initially), no cached
    data is served, and no responses are cached, due to the assumption that bus
    communication is too erratic then. Only when a successful bus lock is
    obtained, caching is started, and cache responses are handed out.
    Subsequent lock (and even unlock) commands are not sent to the bus, but
    served from memory (as the response to an unlock was always observed to be
    the same as to a lock)."""

    def __init__(self, parent):
        self.parent = parent

        self.is_locked = False

    async def base_exchange(self, request):
        pretty = prettify(request)

        if not self.is_locked:
            response = await self.parent.base_exchange(request)

            try:
                pretty_response = EltakoDiscoveryReply.parse(response)
            except ParseError:
                pass
            else:
                if isinstance(pretty, EltakoBusLock) and isinstance(pretty_response, EltakoDiscoveryReply) and pretty_response.address == 0:
                    self.is_locked = True
                    self['fam_reply'] = response

            return response

        if pretty.org == 0xf2:
            # writing prepared -- we better wipe the cache for that
            self.pop(('memory', pretty.address), None)
            for i in range(256):
                self.pop(('read', pretty.address, i), None)

        key = None
        if isinstance(pretty, EltakoBusLock) or isinstance(pretty, EltakoBusUnlock):
            return self['fam_reply']
        if isinstance(pretty, EltakoDiscoveryRequest):
            key = ('discover', pretty.address)
        elif isinstance(pretty, EltakoMemoryRequest):
            key = ('read', pretty.address, pretty.row)

        if key is None: # uncachable
            return await self.parent.base_exchange(request)

        if key not in self:
            try:
                self[key] = await self.parent.base_exchange(request)
            except TimeoutError:
                self[key] = EltakoTimeout().serialize()

        return self[key]

    async def read_mem(self, address):
        key = ('memory', address)
        if key not in self:
            self[key] = await self.parent.read_mem(address)
        return self[key]

class RAMBusCache(dict, BusCache):
    pass

class PickledBusCache(RAMBusCache):
    def __init__(self, parent, filename):
        BusCache.__init__(self, parent)

        self._filename = filename
        if filename.exists():
            self.update(pickle.load(self._filename.open('rb')))

    def __setitem__(self, k, v):
        super(PickledBusCache, self).__setitem__(k, v)

        self.__save()

    def pop(self, *args, **kwargs):
        result = super(PickledBusCache, self).pop(*args, **kwargs)
        self.__save()
        return result

    # FIXME implement all dict methods with a __save

    def __save(self):
        tmpname = self._filename.with_suffix(".tmp")
        with tmpname.open('wb') as f:
            pickle.dump(dict(self), f)
        tmpname.rename(self._filename)

class ReadaheadPickledBusCache(ReadaheadMixin, PickledBusCache):
    pass
