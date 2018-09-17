import asyncio
import time

import serial_asyncio

from .bus import BusInterface
from .error import ParseError, TimeoutError
from .message import ESP2Message, prettify, EltakoTimeout

class RS485SerialInterface(BusInterface):
    """Implementation of the BusInterface as POSIX Serial device.

    Note that this relies on the UART to be configured to drive the bus only
    when data is being sent, as for example done by the Digitus adapters.
    """
    def __init__(self, filename, suppress_echo=None):
        self._filename = filename

        self.received = asyncio.Queue()
        self._hook = None

        self.suppress_echo = suppress_echo
        self._suppress = []

    async def run(self, loop, *, conn_made=None):
        self._loop = loop
        reader, self._writer = await serial_asyncio.open_serial_connection(url=self._filename, baudrate=57600, loop=loop)

        if self.suppress_echo is None:
            # any character sequence as long as it won't look like the preamble and confuse other bus participants
            for i in range(5):
                # flush the input; FIXME tapping into StreamReader internals means I should implement a protocol
                reader._buffer.clear()
                echotest = b'\xff\x00\xff'
                self._writer.write(echotest)
                try:
                    read = await asyncio.wait_for(reader.readexactly(len(echotest)), timeout=0.1, loop=self._loop)
                except asyncio.TimeoutError:
                    self.suppress_echo = False
                    break
                if read == echotest:
                    self.suppress_echo = True
                    break
                else:
                    await asyncio.sleep(0.5)
                    continue
            else:
                conn_made.set_exception(RuntimeError("Echo detection failed"))
                return

        if conn_made is not None:
            conn_made.set_result(None)

        buffered = b""

        while True:
            try:
                buffered += await reader.readexactly(14 - len(buffered))
            except asyncio.streams.IncompleteReadError:
                # TBD: determine whether this shows up somewhere, and develop a signaling strategy
                raise
            while len(buffered) >= 14:
                if self.suppress_echo:
                    # purge entries older than 3s, they might have had
                    # collisions and thus did not report correctly
                    while self._suppress and self._suppress[0][0] < time.time() - 3:
                        self._suppress.pop(0)
                    if self._suppress and buffered[:14] == self._suppress[0][1]:
                        buffered = buffered[14:]
                        continue

                try:
                    parsed = ESP2Message.parse(buffered[:14])
                except ParseError:
                    buffered = buffered[1:]
                else:
                    buffered = buffered[14:]

                    if self._hook is not None and self._hook(parsed):
                        continue # swallowed by the hook
                    await self.received.put(parsed)

    async def exchange(self, request, responsetype=None):
        """Send a request and return a response depending on responsetype as
        BusInterface.exchange does.

        Unlike that basic imlementation, this accepts messages inbetween that
        are not of the specified type, and passes them on to the receive queue
        if they don't match."""

        if self._hook is not None:
            raise RuntimeError("exchange is not reentrant, please serialize your access to the bus yourself.")

        match = asyncio.Future()

        def hook(message):
            if responsetype is None:
                match.set_result(prettify(message))
                self._hook = None
                return True
            else:
                try:
                    parsed = responsetype.parse(message.serialize())
                except ParseError:
                    try:
                        EltakoTimeout.parse(message.serialize())
                    except ParseError:
                        pass
                    else:
                        match.set_exception(TimeoutError)
                        self._hook = None
                        return True
                    return False
                else:
                    match.set_result(parsed)
                    self._hook = None
                    return True

        try:
            self._hook = hook

            await self.send(request)
            try:
                # FIXME this timeout is rather arbitrary
                return await asyncio.wait_for(match, timeout=1, loop=self._loop)
            except asyncio.TimeoutError:
                if responsetype is EltakoTimeout:
                    return EltakoTimeout()
                else:
                    raise TimeoutError
        finally:
            self._hook = None

    async def send(self, request):
        serialized = request.serialize()
        if self.suppress_echo:
            self._suppress.append((time.time(), serialized))
        self._writer.write(serialized)

    base_exchange = None
