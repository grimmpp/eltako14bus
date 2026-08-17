#!/usr/bin/env python3
"""Read and decode an ESP3 stream from a USB serial adapter.

Example::

    python -m examples.esp3_usb_stream /dev/ttyUSB0 --baudrate 57600

The program only reads the port. It does not send commands or radio
telegrams. Install the optional serial dependencies with::

    python -m pip install 'eltako14bus[serial]'
"""

from __future__ import annotations

import argparse
import logging

from eltakobus.esp3_frame import ESP3FrameParser
from eltakobus.esp3_packet import decode_esp3_packet


def read_esp3_stream(port: str, baudrate: int = 57600, *, timeout: float = 0.5) -> None:
    """Read raw ESP3 bytes from *port* and print decoded packets."""

    try:
        import serial
    except ImportError as exc:  # pragma: no cover - depends on local extras
        raise RuntimeError(
            "USB ESP3 reading requires pyserial; install `eltako14bus[serial]`"
        ) from exc
    serial_for_url = getattr(serial, "serial_for_url", None)
    if serial_for_url is None:  # pragma: no cover - depends on local environment
        raise RuntimeError(
            "The imported `serial` module is not pyserial (serial_for_url is "
            "missing). Remove the package named `serial` if installed, then "
            "reinstall pyserial with `python -m pip install --force-reinstall "
            "pyserial`."
        )

    parser = ESP3FrameParser()
    logger = logging.getLogger("esp3_usb_stream")

    # ``serial_for_url`` also supports platform-specific URLs such as
    # ``/dev/cu.usbserial-*`` and ``socket://host:port`` for diagnostics.
    with serial_for_url(port, baudrate=baudrate, timeout=timeout) as device:
        print("Reading ESP3 from %s at %d baud; press Ctrl-C to stop." % (port, baudrate))
        try:
            while True:
                chunk = device.read(4096)
                if not chunk:
                    continue
                for frame in parser.feed(chunk):
                    try:
                        packet = decode_esp3_packet(frame)
                    except ValueError as exc:
                        logger.warning("Ignoring malformed semantic ESP3 packet: %s", exc)
                        continue
                    print(packet)
                for error in parser.pop_errors():
                    logger.warning("Ignoring malformed ESP3 frame: %s", error)
        except KeyboardInterrupt:
            print("Stopping ESP3 reader.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port", help="USB serial device, e.g. /dev/ttyUSB0")
    parser.add_argument("--baudrate", type=int, default=57600)
    parser.add_argument("--timeout", type=float, default=0.5)
    args = parser.parse_args()
    read_esp3_stream(args.port, args.baudrate, timeout=args.timeout)


if __name__ == "__main__":
    main()
