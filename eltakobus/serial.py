import asyncio
import time
import logging

import serial_asyncio

from .bus import BusInterface
from .error import ParseError, TimeoutError
from .message import ESP2Message, prettify, EltakoTimeout

class RS485SerialInterface(BusInterface, asyncio.Protocol):
    """Implementation of the BusInterface as POSIX Serial device.

    Note that this relies on the UART to be configured to drive the bus only
    when data is being sent, as for example done by the Digitus adapters.
    """
    def __init__(self, filename, suppress_echo=None, log=None):
        self._filename = filename

        self.received = asyncio.Queue()
        self._hook = None

        self.suppress_echo = suppress_echo
        self._suppress = []

        self.log = log or logging.getLogger('eltakobus.serial')

        self.transport = None

        self._buffer = b''
        # a single future waiting for the buffer to reach a certain level. Only
        # one is supported: we don't need two futures racing for who gets to
        # snatch the first bytes off the buffer
        self._buffer_request = None
        self._buffer_request_level = 0

    def connection_made(self, transport):
        self.transport.set_result(transport)

    def data_received(self, d):
        self._buffer += d
        if self._buffer_request is not None and \
                len(self._buffer) >= self._buffer_request_level:
            self._buffer_request.set_result(None)

    def eof_received(self):
        self.transport = None
        if self._buffer_request is not None:
            self._buffer_request.set_exception(EOFError)

    async def await_bufferlevel(self, level):
        """Wait until at least level bytes are in self._buffer"""
        if self._buffer_request is not None:
            raise RuntimeError("Simultaneous waiting for buffer levels")
        self._buffer_request = asyncio.Future()
        self._buffer_request_level = level
        try:
            await self._buffer_request
        finally:
            self._buffer_request = None

    async def run_echotest(self):
        echotest = b'\xff\x00\xff' * 5 # long enough that it can not be contained in any EnOcean message

        for write_attempt in range(5):
            # flush input
            self._buffer = b""

            self.transport.write(echotest)

            try:
                await asyncio.wait_for(self.await_bufferlevel(len(echotest)), timeout=0.2, loop=self._loop)
            except asyncio.TimeoutError:
                continue

            for waiting_for_slow_transmission_on_busy_line in range(5):
                if echotest in self._buffer:
                    return True

                if write_attempt > 0 and self._buffer == b"":
                    # Quick path to another write attempt: we've had plenty of
                    # grace time the first time already, and didn't receive a
                    # byte while waiting for the UART to round-trip. It'd make
                    # sense to listen in a bit longer on a busy UART, but here
                    # it's pointless.
                    break

                # could do some magic like "how much of the tail of buffer
                # looks like the echotest, so for how many more bytes do i
                # have to wait", but that'd buy us only a few hundred
                # milliseconds in already rare and chatty situations and
                # would be completely untested
                await asyncio.sleep(0.1)

        return False

    async def run(self, loop, *, conn_made=None):
        self._loop = loop

        if self.transport is not None:
            raise RuntimeError("Serial interface run twice")
        self.transport = asyncio.Future()
        await serial_asyncio.create_serial_connection(
                loop,
                protocol_factory=lambda: self,
                url=self._filename,
                baudrate=57600
                )
        self.transport = await self.transport

        if self.suppress_echo is None:
            try:
                self.log.debug("Performing echo detection")
                self.suppress_echo = await self.run_echotest()
                if self.suppress_echo:
                    self.log.debug("Echo detected on the line, enabling suppression")
                else:
                    self.log.debug("No echo detected on the line")
            except Exception as e:
                if conn_made:
                    self.conn_made.set_exception(e)
                    return
                else:
                    raise
            self._buffer = b""

        if conn_made is not None:
            conn_made.set_result(None)

        while True:
            await self.await_bufferlevel(14)

            while len(self._buffer) >= 14:
                if self.suppress_echo:
                    # purge entries older than 3s, they might have had
                    # collisions and thus did not report correctly
                    while self._suppress and self._suppress[0][0] < time.time() - 3:
                        self.log.info("Dropping echo-suppressed message because it timed out without being echoed")
                        self._suppress.pop(0)
                    found_i = None
                    for i, (t, suppressed) in enumerate(self._suppress):
                        if self._buffer[:14] == suppressed:
                            found_i = i
                            break
                    if found_i is not None:
                        if found_i > 0:
                            self.log.info("Dropping %d echo-suppressed message(s) because a later sent message was already received" % found_i)
                        # block is not part of the if-condition in the loop
                        # because it would invalidate the iterator (that'd be
                        # OK as we're breaking) but also needs to continue on
                        # the outer loop
                        del self._suppress[:found_i + 1]
                        self._buffer = self._buffer[14:]
                        continue

                try:
                    parsed = ESP2Message.parse(self._buffer[:14])
                except ParseError:
                    self._buffer = self._buffer[1:]
                else:
                    self._buffer = self._buffer[14:]

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
        self.transport.write(serialized)

    base_exchange = None
