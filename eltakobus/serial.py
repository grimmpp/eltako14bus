import asyncio
import time
import logging

import threading
import queue
import serial

import serial_asyncio

from .bus import BusInterface
from .error import ParseError, TimeoutError
from .message import ESP2Message, prettify, EltakoTimeout, EltakoPoll, EltakoMessage

class RS485SerialInterfaceV2(BusInterface, threading.Thread):

    class ReceiverQueue():
        def __init__(self, receive: queue.Queue, mutex: threading.Lock):
            self._receive = receive
            self._mutex = mutex

        async def get(self) -> any:
            return self._receive.get()
        
        def empty(self) -> bool:
            return self._receive.empty()
        
        def get_nowait(self):
            return self._receive.get_nowait()


    def __init__(self, 
                 filename, 
                 log=None, 
                 callback=None, 
                 baud_rate=57600, 
                 reconnection_timeout:float=10, 
                 delay_message:float=0.01, 
                 auto_reconnect=True):
        
        super(RS485SerialInterfaceV2, self).__init__()
        self._filename = filename
        self._baud_rate = baud_rate
        self.delay_message = delay_message
        self._auto_reconnect = auto_reconnect

        self.log = log or logging.getLogger('eltakobus.serial')

        # Create an event to stop the thread
        self._stop_flag = threading.Event()
        # Input buffer
        self._buffer = []
        self.__mutex = threading.Lock()
        # Setup packet queues
        self.transmit = queue.Queue()
        self.receive = queue.Queue()
        self.received = RS485SerialInterfaceV2.ReceiverQueue(self.receive, self.__mutex)
        # Set the callback method
        self.__callback = callback
        # serial
        self.__serial = None

        self.suppress_echo = False
        self._suppress = []

        # reconnection timeout
        self.__recon_time = reconnection_timeout

        self.is_serial_connected = threading.Event()

        self.status_changed_handler = None

    def set_status_changed_handler(self, handler) -> None:
        self.status_changed_handler = handler
        self._fire_status_change_handler(self.is_active())

    def _fire_status_change_handler(self, connected:bool) -> None:
        try:
            if self.status_changed_handler:
                self.status_changed_handler(connected)
        except Exception as e:
            pass

    def stop(self):
        self._stop_flag.set()

    async def base_exchange(self, request:ESP2Message):
        self._send(request)

    def _send(self, request:ESP2Message):
        if self.suppress_echo:
            self._suppress.append((time.time(), request.serialize()))
        self.transmit.put((time.time(), request))

    def set_callback(self, callback):
        with self.__mutex:
            self.__callback = callback
            if callable is not None:
                while not self.transmit.empty(): self.transmit.get()

    async def send_base_id_request(self):
        data = b'\xAB\x58\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        await self.send(ESP2Message(bytes(data)))

    async def send_version_request(self):
        data = b'\xAB\x4B\x00\x00\x00\x00\x00\x00\x00\x00\x00'
        await self.send(ESP2Message(bytes(data)))

    def echotest(self):
        echotest = b'\xff\x00\xff' * 5 # long enough that it can not be contained in any EnOcean message

        for write_attempt in range(5):
            # send echo
            self.__serial.write(echotest)
            # receive echo
            response = self.__serial.read_until( echotest )

            if echotest == response: return True
            
        return False

    def is_active(self) -> bool:
        return not self._stop_flag.is_set() and self.is_serial_connected.is_set()

    def reconnect(self):
        self._stop_flag.set()
        self._stop_flag.wait()
        self.start()

    def run(self):
        self.log.info('Serial communication started')
        self._fire_status_change_handler(connected=False)
        while not self._stop_flag.is_set():
            try:
                with self.__mutex:
                    # reconnect
                    if self.__serial is None:
                        self.__serial = serial.serial_for_url(self._filename, self._baud_rate, timeout=0.1, write_timeout=0.1)
                        self.log.info("Established serial connection to %s - baud rate: %d", self._filename, self._baud_rate)
                        
                        self.log.debug("Performing echo detection")
                        self.suppress_echo = self.echotest()
                        if self.suppress_echo:
                            self.log.debug("Echo detected on the line, enabling suppression")
                        else:
                            self.log.debug("No echo detected on the line")
                        
                        self.is_serial_connected.set()
                        self._fire_status_change_handler(connected=True)

                    # send messages
                    while not self.transmit.empty(): 
                        ser_msg = self.transmit.get()
                        # dropp old messages
                        if ser_msg[0] < time.time() - 30:
                            self.log.info("Dropping echo-suppressed message because it timed out without being echoed")
                        else:
                            self.__serial.write(ser_msg[1].serialize())
                            self.log.debug("Sent message: %s", ser_msg[1])
                            # baud speed on the bus is 9600 and gateway usually have 57600
                            # this means we need to watch out that the internal gateway buffer does not overflow
                            # fam14 (baudrate 57600) delay_message=.001
                            # fam14 (baudrate 9600) delay_message=.001
                            # fam-usb (baudrate 9600) delay_message=.001
                            # fgw14-usb (baudrate 57600) delay_message=.01
                            time.sleep(self.delay_message)
                            self.transmit.task_done()

                    # read from bus
                    self._buffer.extend( self.__serial.read_all() )

                    # process received messages from bus
                    while len(self._buffer) >= 14:
                        try:
                            parsed_msg = prettify( ESP2Message.parse(bytes(self._buffer[:14])) )
                            # self.log.debug("Received Message: %s", parsed_msg)
                        except ParseError:
                            self._buffer = self._buffer[1:]
                        else:
                            self._buffer = self._buffer[14:]
                            if self.__callback is None:
                                self.receive.put(parsed_msg)
                            else: 
                                self.__callback(parsed_msg)

                # required to not utilize the whole CPU power
                time.sleep(.00001)
                

            except (serial.SerialException, IOError) as e:
                self._fire_status_change_handler(connected=False)
                self.is_serial_connected.clear()
                self.log.error(e)
                self.__serial = None
                if self._auto_reconnect:
                    self.log.info("Serial communication crashed. Wait %s seconds for reconnection.", self.__recon_time)
                    time.sleep(self.__recon_time)

        self._fire_status_change_handler(connected=False)
        if self.__serial is not None:
            self.__serial.close()
        self.is_serial_connected.clear()
        self.log.info('Serial communication stopped')


    async def exchange(self, request: ESP2Message, responsetype=None, retries:int=3, timeout:float=1.0) -> ESP2Message:
        """Send a request and return a response depending on responsetype as
        BusInterface.exchange does.
        """

        # callback and exchange cannot be used at the same time.
        if self.__callback is not None:
            raise RuntimeError("exchange is not reentrant, please serialize your access to the bus yourself.")

        send_time = 0
        while retries > 0:

            with self.__mutex:
                # empty queue
                while not self.receive.empty():
                    self.receive.get()

                # send request
                send_time = time.time()
                self._send(request)

            while self.transmit.unfinished_tasks > 0:
                # required to not utilize the whole CPU power
                time.sleep(.00001) 

            # receive response
            while True:
                try:
                    msg = self.receive.get_nowait()
                    if responsetype is None:
                        return msg
                    else:
                        if isinstance(msg, responsetype):
                            return msg
                        if isinstance(msg, EltakoTimeout):
                            raise TimeoutError
                except queue.Empty:
                    pass

                # retry
                if time.time() - send_time > timeout:
                    self.log.debug("Retry sending message. Timeout (%ds) reached.", timeout)
                    retries = retries-1
                    break

                # required to not utilize the whole CPU power
                time.sleep(.00001)



class RS485SerialInterface(BusInterface, asyncio.Protocol):
    """Implementation of the BusInterface as POSIX Serial device.

    Note that this relies on the UART to be configured to drive the bus only
    when data is being sent, as for example done by the Digitus adapters.
    """
    def __init__(self, filename, suppress_echo=None, log=None, baud_rate=57600):
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
        self.baud_rate = baud_rate

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
                await asyncio.wait_for(self.await_bufferlevel(len(echotest)), timeout=0.2)
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
                baudrate=self.baud_rate
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
                    # In some Python versions, the wait_for'd await_bufferlevel
                    # is not cancelled in time. Avoiding the race condition
                    # until that's further investigated or obsolete.
                    await asyncio.sleep(0.3)
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
                    self.log.debug("Received message %s", parsed)
                    self._hook = None
                    return True

        try:
            self._hook = hook

            await self.send(request)
            try:
                # FIXME this timeout is rather arbitrary
                return await asyncio.wait_for(match, timeout=1)
            except asyncio.TimeoutError:
                if responsetype is EltakoTimeout:
                    return EltakoTimeout()
                else:
                    raise TimeoutError
        finally:
            self._hook = None

    async def send(self, request):
        self.log.debug("Sent message: %s", request)
        serialized = request.serialize()
        if self.suppress_echo:
            self._suppress.append((time.time(), serialized))
        self.transport.write(serialized)

    base_exchange = None
