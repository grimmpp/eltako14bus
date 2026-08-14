# Eltako-specific EEP telegram tests

The tests in [tests/eltako_eep_test.py](../tests/eltako_eep_test.py) protect
device-specific telegram conventions from the Eltako catalogue. They are kept
separate from generic EEP tests because the same EEP identifier can have fixed
markers or status meanings for a particular Eltako product.

Covered examples include:

- FTF65S (`A5-02-05`): inverted 0…40 °C value and DB0 marker `0x0F`;
- FHD65SB (`A5-06-02`): supply voltage, illumination, and DB0 marker `0x0F`;
- FLT58 (`A5-09-05`): 16-bit VOC value with DB1/DB0 markers `0x1B/0x0A`;
- FKS-H (`A5-20-04`): DB0-dependent supply/target temperature and battery
  status `0x09/0x12`;
- FHMB/FRWB (`A5-30-03`): alarm/no-alarm markers `0x0F/0x1F`;
- FFGB/mTronic (`A5-14-09`/`A5-14-0A`): closed, tilt, open and alarm status;
- FWS81/FRW: Eltako RPS water, smoke, and low-battery status bytes;
- Eltako gateway switching and shutter status/command telegrams.

The tests use fixed raw DB3…DB0/RPS payloads and verify both decoding and
encoding, including marker bytes and status values.
