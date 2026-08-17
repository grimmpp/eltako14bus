"""Unit tests for the dependency-free ESP2 stream parser."""

import unittest

from eltakobus.esp2_frame import ESP2_FRAME_LENGTH, ESP2FrameParser
from eltakobus.message import EltakoDiscoveryReply


class ESP2FrameParserTest(unittest.TestCase):
    """Verify fragmented reads, resynchronisation and checksum protection."""

    def setUp(self):
        self.frame = EltakoDiscoveryReply(
            reported_address=1, reported_size=1, memory_size=127,
            model=bytes.fromhex("04044200"), is_fam=False,
        ).serialize()

    def test_accepts_bytewise_and_concatenated_input(self):
        parser = ESP2FrameParser()
        received = []
        for byte in self.frame + self.frame:
            received.extend(parser.feed(bytes((byte,))))
        self.assertEqual([self.frame, self.frame], received)
        self.assertEqual(b"", parser.buffered_bytes)
        self.assertEqual(ESP2_FRAME_LENGTH, len(self.frame))
        self.assertEqual((), parser.errors)

    def test_discards_noise_and_recovers_after_bad_checksum(self):
        parser = ESP2FrameParser()
        broken = bytearray(self.frame)
        broken[-1] ^= 0xFF
        received = parser.feed(b"noise" + broken + self.frame)
        self.assertEqual([self.frame], received)
        self.assertGreaterEqual(parser.discarded_bytes, 5)
        self.assertEqual(1, len(parser.errors))
        self.assertEqual(1, len(parser.pop_errors()))
        self.assertEqual((), parser.pop_errors())

    def test_keeps_split_preamble_and_partial_frame(self):
        parser = ESP2FrameParser()
        self.assertEqual([], parser.feed(b"\x00\xA5"))
        self.assertEqual(b"\xA5", parser.buffered_bytes)
        self.assertEqual([], parser.feed(self.frame[1:-1]))
        self.assertEqual([self.frame], parser.feed(self.frame[-1:]))

    def test_rejects_integer_chunks_and_bounds_diagnostics(self):
        with self.assertRaises(TypeError):
            ESP2FrameParser().feed(3)
        parser = ESP2FrameParser(max_errors=2)
        broken = bytearray(self.frame)
        broken[-1] ^= 0xFF
        parser.feed(bytes(broken) * 5)
        self.assertEqual(2, len(parser.errors))

    def test_replays_sixty_frames_with_random_chunk_boundaries(self):
        """A longer replay catches state leaks that short unit vectors miss."""
        parser = ESP2FrameParser()
        stream = self.frame * 60
        received = []
        cursor = 0
        chunk_sizes = (1, 3, 7, 2, 19, 5, 11)
        for size in (chunk_sizes * 20):
            if cursor >= len(stream):
                break
            received.extend(parser.feed(stream[cursor:cursor + size]))
            cursor += size
        self.assertEqual(60, len(received))
        self.assertEqual([self.frame] * 60, received)
        self.assertEqual((), parser.errors)


if __name__ == "__main__":
    unittest.main()
