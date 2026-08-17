# ESP2 tutorial: connect to a LAN gateway

This tutorial uses the native ESP2-over-TCP adapter for a gateway that exposes
the Eltako 14-byte ESP2 stream.

```sh
python -m pip install 'eltako14bus[serial]'
```

```python
import asyncio
from eltakobus.esp2_gateway import ESP2TCPSerialInterface
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest


async def main():
    bus = ESP2TCPSerialInterface("192.168.1.50", 5000, auto_reconnect=True)
    bus.start()
    try:
        await asyncio.to_thread(bus.is_serial_connected.wait)
        reply = await bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply)
        print(reply.reported_address, reply.model.hex(), reply.memory_size)
    finally:
        bus.stop()
        await asyncio.to_thread(bus.join, 2)


asyncio.run(main())
```

The adapter handles fragmented/coalesced TCP reads, unsolicited telegrams,
timeouts and reconnects. For a runnable version see
[`examples/esp2_tcp_gateway.py`](../examples/esp2_tcp_gateway.py).

A discovered `LAN_ESP2` endpoint can be used after an explicit application
decision:

```python
from eltakobus.lan_discovery import LanGatewayDiscovery

discovery = LanGatewayDiscovery()
discovery.start()
try:
    service = discovery.find_endpoint(gateway_device_type="lan-gw-esp2")
    if service:
        host, port = service.endpoint
        # construct ESP2TCPSerialInterface(host, port) here
finally:
    discovery.stop()
```

Discovery supplies metadata only; it does not open the TCP gateway.
