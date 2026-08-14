"""ESP2 gateway transports.

This module contains the TCP transport used by the ESP2 gateway adapter.  It
speaks the same 14-byte ESP2 telegrams as :class:`RS485SerialInterfaceV2`,
which makes it usable with the existing ``BusInterface`` API.

The implementation is deliberately independent of optional ESP3/EnOcean
packages.  Applications that need an ESP3 radio stick can put an ESP2 gateway
in front of it and use this transport, without making those dependencies
mandatory for the core library.
"""

import logging
import queue
import socket
import threading
import time
import asyncio

from .bus import BusInterface
from .error import ParseError, TimeoutError
from .message import ESP2Message, EltakoTimeout, prettify


class ESP2TCPSerialInterface(BusInterface, threading.Thread):
    """Connect to an ESP2-over-TCP gateway.

    The adapter emits and consumes normal :class:`ESP2Message` frames.  A
    response can be awaited with ``exchange`` just like on
    ``RS485SerialInterfaceV2``.  Unsolicited frames are placed on ``received``
    unless a callback was configured.

    ``socket_factory`` is primarily useful for deterministic unit tests.  It
    must return an object implementing ``connect``, ``sendall``, ``recv``,
    ``settimeout`` and ``close``.
    """

    class ReceiverQueue:
        def __init__(self, receive):
            self._receive = receive

        async def get(self):
            import asyncio
            while True:
                try:
                    return self._receive.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.01)

        def empty(self):
            return self._receive.empty()

        def get_nowait(self):
            return self._receive.get_nowait()

    def __init__(self, host, port=5000, *, log=None, callback=None,
                 reconnection_timeout=10.0, delay_message=0.01,
                 auto_reconnect=True, socket_factory=None,
                 recv_size=1024):
        BusInterface.__init__(self)
        threading.Thread.__init__(self, daemon=True)
        self.host = host
        self.port = port
        self.log = log or logging.getLogger("eltakobus.esp2_gateway")
        self.delay_message = delay_message
        self._reconnection_timeout = reconnection_timeout
        self._auto_reconnect = auto_reconnect
        self._socket_factory = socket_factory or socket.socket
        self._recv_size = recv_size
        self._stop_flag = threading.Event()
        self._connected = threading.Event()
        self.is_serial_connected = self._connected
        self._socket = None
        self._buffer = bytearray()
        self._mutex = threading.Lock()
        self.transmit = queue.Queue()
        self.receive = queue.Queue()
        self.received = self.ReceiverQueue(self.receive)
        self._callback = callback
        self.status_changed_handler = None
        self._exchange_lock = asyncio.Lock()

    @property
    def callback_func(self):
        return self._callback

    def set_callback(self, callback):
        self._callback = callback

    def _send(self, request):
        self.transmit.put((time.time(), request))

    async def base_exchange(self, request):
        """Queue a telegram for transmission without waiting for a reply."""
        self._send(request)

    async def exchange(self, request, responsetype=None, retries=3,
                       timeout=1.0):
        """Send a request and return its first matching response."""
        async with self._exchange_lock:
            if self._callback is not None:
                raise RuntimeError(
                    "exchange is not reentrant while a callback is configured"
                )
            while retries > 0:
                while not self.receive.empty():
                    self.receive.get_nowait()
                send_time = time.time()
                self._send(request)
                while self.transmit.unfinished_tasks > 0:
                    await asyncio.sleep(0.001)
                while time.time() - send_time <= timeout:
                    try:
                        message = self.receive.get_nowait()
                    except queue.Empty:
                        await asyncio.sleep(0.001)
                        continue
                    if responsetype is None:
                        return message
                    if isinstance(message, responsetype):
                        return message
                    if isinstance(message, EltakoTimeout):
                        raise TimeoutError
                retries -= 1
            raise TimeoutError

    def set_status_changed_handler(self, handler):
        self.status_changed_handler = handler
        self._fire_status_change_handler(self.is_active())

    def _fire_status_change_handler(self, connected):
        if self.status_changed_handler is not None:
            try:
                self.status_changed_handler(connected)
            except Exception:
                self.log.exception("Gateway status callback failed")

    def is_active(self):
        return not self._stop_flag.is_set() and self._connected.is_set()

    def stop(self):
        self._stop_flag.set()
        sock = self._socket
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def reconnect(self):
        if self.is_alive():
            self.stop()
            self.join()
        if self._started.is_set():
            threading.Thread.__init__(self, daemon=True)
        self._stop_flag.clear()
        self.start()

    def _connect(self):
        sock = self._socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(0.1)
        sock.connect((self.host, self.port))
        self._socket = sock
        self._connected.set()
        self._fire_status_change_handler(True)
        self.log.info("Connected to ESP2 gateway %s:%s", self.host, self.port)

    def _disconnect(self):
        self._connected.clear()
        self._fire_status_change_handler(False)
        sock, self._socket = self._socket, None
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _send_pending(self):
        while True:
            try:
                timestamp, message = self.transmit.get_nowait()
            except queue.Empty:
                return
            try:
                if timestamp < time.time() - 30:
                    continue
                self._socket.sendall(message.serialize())
                if self.delay_message:
                    time.sleep(self.delay_message)
            finally:
                self.transmit.task_done()

    def _process_bytes(self, data):
        self._buffer.extend(data)
        while len(self._buffer) >= 14:
            raw = bytes(self._buffer[:14])
            try:
                parsed = prettify(ESP2Message.parse(raw))
            except ParseError:
                del self._buffer[0]
                continue
            del self._buffer[:14]
            if self._callback is not None:
                try:
                    self._callback(parsed)
                except Exception:
                    self.log.exception("Gateway receive callback failed")
            else:
                self.receive.put(parsed)

    def run(self):
        self._fire_status_change_handler(False)
        while not self._stop_flag.is_set():
            try:
                if self._socket is None:
                    self._connect()
                self._send_pending()
                try:
                    data = self._socket.recv(self._recv_size)
                except socket.timeout:
                    continue
                if not data:
                    raise ConnectionError("ESP2 gateway closed the connection")
                self._process_bytes(data)
            except (OSError, IOError, ConnectionError) as exc:
                self.log.warning("ESP2 gateway connection lost: %s", exc)
                self._disconnect()
                if not self._auto_reconnect:
                    break
                self._stop_flag.wait(self._reconnection_timeout)
        self._disconnect()


# Name used by the upstream esp2_gateway_adapter project.
ESP2TCP2SerialCommunicator = ESP2TCPSerialInterface
