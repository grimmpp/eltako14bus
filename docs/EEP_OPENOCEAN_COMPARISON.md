# EEP comparison with OpenOcean

This note records a read-only comparison with the EEP classes in the
[fruggy83/openocean repository](https://github.com/fruggy83/openocean/tree/master/src/main/java/org/openhab/binding/enocean/internal/eep).
The OpenOcean code is useful as an independent implementation reference, but
it is an openHAB binding and is therefore not treated as the protocol
authority. The [EnOcean Alliance EEP 2.6.7 specification](https://www.enocean-alliance.org/wp-content/uploads/2017/05/EnOcean_Equipment_Profiles_EEP_v2.6.7_public.pdf)
and Eltako's device catalogue remain authoritative for this library.

## Findings

- The library currently registers 71 concrete EEP profiles. OpenOcean contains
  131 profile-like classes, including manufacturer suffixes, generic helpers,
  actuator commands, and VLD profiles. The numbers are therefore not a direct
  feature comparison.
- OpenOcean confirmed the 10-bit illumination layout for A5-06-03 and
  A5-07-03: DB2 is the eight most significant bits and DB1.BIT7…BIT6 are the
  two least significant bits. The Python implementation and regression tests
  now use this layout.
- OpenOcean exposed an actual defect in the former A5-04-03 implementation.
  The profile uses humidity in DB3 and temperature in DB2.BIT1…BIT0 plus DB1.
  Decode, encode, and boundary tests now follow that definition.
- The existing A5-02 8-bit and 10-bit temperature profiles, A5-04-01/02,
  A5-07-01/02/03, A5-20-04, and A5-14-09/0A were checked against the matching
  OpenOcean classes and the official tables. Eltako-specific status markers
  remain intentionally supported where they differ from the generic profile.

## Remaining coverage gaps

The most notable standard profiles present in OpenOcean but not yet exposed as
independent Python classes are:

- A5-08-02 and A5-08-03;
- most of A5-10 (the room operating panel variants);
- A5-11-03 and A5-11-04;
- A5-12-00 and additional A5-12 profiles;
- A5-13 environmental profiles beyond A5-13-01;
- A5-14-01 through A5-14-08;
- F6-10-01 and the manufacturer-specific F6-10-00 variants;
- the D2 VLD profiles, including D2-01, D2-05, D2-11, D2-14 and related
  bidirectional profiles.

These should be added with raw telegram fixtures and per-field tests. Copying
the openHAB conversion layer directly would introduce openHAB semantics and
would risk confusing application channels with wire-level EEP fields.
