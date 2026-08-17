# User guide

`eltako14bus` provides asynchronous access to Eltako Series-14 RS485 buses.
For normal applications, use `RS485SerialInterfaceV2`; it reconnects after a
lost serial device and delivers decoded bus messages through `exchange()` or
the receive queue.

## Install and connect

```sh
python -m pip install 'eltako14bus[serial]'
```

```python
import asyncio
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest
from eltakobus.serial import RS485SerialInterfaceV2


async def main():
    bus = RS485SerialInterfaceV2(
        "/dev/ttyUSB0", baud_rate=57600, auto_reconnect=True,
    )
    bus.start()
    try:
        await asyncio.to_thread(bus.is_serial_connected.wait)
        reply = await bus.exchange(
            EltakoDiscoveryRequest(1), EltakoDiscoveryReply,
        )
        print(reply.reported_address, reply.model.hex())
    finally:
        bus.stop()
        bus.join(timeout=2)


asyncio.run(main())
```

The correct baud rate depends on the adapter and gateway. Keep
`delay_message` at its tested/default value until a bus-specific benchmark
shows that a shorter delay is reliable. Do not run switching or memory-write
tests on a productive installation without an explicit safety plan.

## ESP2 compatibility

All transports use the same validated ESP2 frame boundary. Fragmented serial
reads, multiple telegrams in one read, noise and invalid checksums are handled
before messages are decoded. Existing applications can continue using
`ESP2Message`, `RPSMessage`, `Regular4BSMessage`, discovery and memory classes
without adopting the new parser API.

For offline recordings, `VirtualBus` and `ESP2FrameParser` can be used without
hardware. Hardware tests are opt-in and skip cleanly when the configured serial
device is absent.

See the [developer guide](DEVELOPER_GUIDE.md), [ESP2 framing guide](ESP2_FRAMING.md),
[EEP reference](EEP_REFERENCE.md), and [release guide](RELEASING.md) for the
complete API and operational details.
