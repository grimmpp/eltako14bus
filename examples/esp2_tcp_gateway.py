#!/usr/bin/env python3
"""Read one discovery response from an ESP2-over-TCP gateway."""

import argparse
import asyncio

from eltakobus.esp2_gateway import ESP2TCPSerialInterface
from eltakobus.message import EltakoDiscoveryReply, EltakoDiscoveryRequest
from eltakobus.transport_metrics import TransportMetrics


async def main(host: str, port: int) -> None:
    metrics = TransportMetrics()
    bus = ESP2TCPSerialInterface(host, port, metrics=metrics, auto_reconnect=True)
    bus.start()
    try:
        await asyncio.to_thread(bus.is_serial_connected.wait)
        response = await bus.exchange(EltakoDiscoveryRequest(1), EltakoDiscoveryReply, retries=2)
        print(response)
        print(metrics.snapshot().as_dict())
    finally:
        bus.stop()
        await asyncio.to_thread(bus.join, 2)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()
    asyncio.run(main(args.host, args.port))
