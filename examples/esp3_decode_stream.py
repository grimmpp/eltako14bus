#!/usr/bin/env python3
"""Decode hexadecimal ESP3 stream chunks from stdin without hardware."""

import sys

from eltakobus.esp3_frame import ESP3FrameParser
from eltakobus.esp3_packet import decode_esp3_packet


def main() -> None:
    parser = ESP3FrameParser()
    for line in sys.stdin:
        if not line.strip():
            continue
        for frame in parser.feed(bytes.fromhex(line.strip())):
            print(decode_esp3_packet(frame))
    for error in parser.pop_errors():
        print("ignored ESP3 frame:", error, file=sys.stderr)


if __name__ == "__main__":
    main()
