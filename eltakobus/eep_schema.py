"""Declarative wire schemas for selected EEPs.

This module is an opt-in migration bridge.  It deliberately does *not*
replace the established classes in :mod:`eltakobus.eep`: callers of those
classes keep receiving the same mutable profile instances and attributes.

The schemas make the wire layout available to new code and allow tests to
prove that a declarative decode has the same public values as the legacy D2
decoders.  Once a profile has comprehensive parity coverage, an EEP class can
delegate to its schema internally without changing its public API.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any

from .error import NotImplementedError as EEPNotImplementedError
from .error import WrongOrgError
from .vld import VLDDecodedMessage, VLDField, VLDLayout
from .vld import VLDDecodedField, VLDValueStatus


def _payload_bytes(payload: Any) -> bytes:
    """Convert bytes-like input without treating an integer as a byte count."""

    if isinstance(payload, (str, int)):
        raise TypeError("payload must be bytes-like")
    try:
        return bytes(payload)
    except (TypeError, ValueError) as exc:
        raise TypeError("payload must be bytes-like") from exc


@dataclass(frozen=True, slots=True)
class EEPWireSchema:
    """A named VLD layout that is safe to use beside a legacy EEP decoder.

    ``decode_message`` accepts a normal ``VLDMessage`` and intentionally uses
    only the leading bytes covered by the layout.  Existing D2 decoders accept
    additional VLD payload bytes, so retaining that behaviour is important for
    compatibility with vendor extensions.
    """

    eep: str
    name: str
    layout: VLDLayout
    allowed_raw_values: Mapping[str, frozenset[int]] = field(default_factory=dict)

    @property
    def field_names(self) -> frozenset[str]:
        """Names exposed by this schema's decoded message."""

        return frozenset(definition.name for definition in self.layout.fields)

    def __post_init__(self) -> None:
        """Freeze and validate optional message-variant restrictions."""

        if not isinstance(self.eep, str) or not self.eep:
            raise ValueError("eep must be a non-empty string")
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(self.layout, VLDLayout):
            raise TypeError("layout must be a VLDLayout")

        field_names = {definition.name for definition in self.layout.fields}
        allowed = {}
        for field_name, raw_values in dict(self.allowed_raw_values).items():
            if field_name not in field_names:
                raise ValueError("restriction references an unknown schema field")
            values = frozenset(raw_values)
            if not values or any(isinstance(raw, bool) or not isinstance(raw, int)
                                 for raw in values):
                raise ValueError("field restrictions require non-empty integer values")
            allowed[field_name] = values
        object.__setattr__(self, "allowed_raw_values", MappingProxyType(allowed))

    def decode_payload(self, payload: bytes) -> VLDDecodedMessage:
        """Decode the schema-sized prefix of a VLD payload.

        A short payload is rejected, while a longer payload is allowed and
        left untouched.  This matches the established D2 decoder contract.
        """

        data = _payload_bytes(payload)
        if len(data) < self.layout.payload_size:
            raise ValueError(
                "%s requires at least %d payload bytes" %
                (self.eep, self.layout.payload_size)
            )
        decoded = self.layout.decode(data[:self.layout.payload_size])
        for field_name, allowed in self.allowed_raw_values.items():
            raw = decoded[field_name].raw
            if raw not in allowed:
                raise EEPNotImplementedError(
                    "%s does not support %s raw value %d" %
                    (self.eep, field_name, raw)
                )
        return decoded

    def decode_message(self, message: Any) -> VLDDecodedMessage:
        """Decode a D2 ``VLDMessage`` without changing the message object."""

        if getattr(message, "org", None) != 0xD2:
            raise WrongOrgError
        return self.decode_payload(message.data)


@dataclass(frozen=True, slots=True)
class EEPCompatibilityAdapter:
    """Compare an opt-in wire schema with an unchanged legacy decoder.

    ``field_attributes`` maps a declarative wire field to the existing public
    attribute on the object returned by the legacy decoder.  The adapter is a
    verification seam, not a replacement object: :meth:`decode_legacy` always
    returns the original decoder result unchanged.
    """

    schema: Any
    legacy_decoder: Callable[[Any], Any]
    field_attributes: Mapping[str, str]

    def __post_init__(self) -> None:
        definitions = set(self.schema.field_names)
        mapping = dict(self.field_attributes)
        unknown = set(mapping).difference(definitions)
        if unknown:
            raise ValueError(
                "adapter references fields missing from %s: %s" %
                (self.schema.eep, ", ".join(sorted(unknown)))
            )
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("each legacy attribute may be mapped only once")
        object.__setattr__(self, "field_attributes", MappingProxyType(mapping))

    def decode_legacy(self, message: Any) -> Any:
        """Return exactly the object supplied by the original EEP decoder."""

        return self.legacy_decoder(message)

    def decode(self, message: Any) -> tuple[Any, VLDDecodedMessage]:
        """Decode through both paths and return ``(legacy, declarative)``."""

        return self.decode_legacy(message), self.schema.decode_message(message)

    def compatibility_errors(self, message: Any) -> tuple[str, ...]:
        """Return human-readable parity differences, without mutating state."""

        legacy, declarative = self.decode(message)
        errors = []
        for field_name, attribute in self.field_attributes.items():
            # A selected profile may expose a different field set per message
            # variant.  Only compare fields present in the selected variant.
            if field_name not in declarative:
                continue
            field = declarative[field_name]
            expected = field.value if field.is_valid else None
            actual = getattr(legacy, attribute)
            if isinstance(expected, float) and isinstance(actual, (int, float)):
                if abs(expected - actual) <= 1e-9:
                    continue
            elif expected == actual:
                continue
            errors.append(
                "%s.%s differs: legacy=%r schema=%r (raw=%d, status=%s)" %
                (self.schema.eep, attribute, actual, expected, field.raw,
                 field.status.value)
            )
        return tuple(errors)

    def assert_compatible(self, message: Any) -> None:
        """Raise ``AssertionError`` if the old public values differ."""

        errors = self.compatibility_errors(message)
        if errors:
            raise AssertionError("; ".join(errors))


@dataclass(frozen=True, slots=True)
class D20001BitSegment:
    """One byte-local part of a possibly compound D2-00-01 value.

    ``lsb`` counts from the least-significant bit of ``byte_index`` and
    ``raw_offset`` identifies where the segment is placed in the assembled
    integer.  Multiple segments explicitly model the little-endian and split
    fields used by variants B through E.
    """

    byte_index: int
    lsb: int
    width: int
    raw_offset: int = 0

    def __post_init__(self) -> None:
        for name, value in (("byte_index", self.byte_index), ("lsb", self.lsb),
                            ("raw_offset", self.raw_offset)):
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("%s must be an integer" % name)
            if value < 0:
                raise ValueError("%s must not be negative" % name)
        if isinstance(self.width, bool) or not isinstance(self.width, int):
            raise TypeError("width must be an integer")
        if self.width < 1 or self.lsb + self.width > 8:
            raise ValueError("segment must fit inside one byte")


@dataclass(frozen=True, slots=True)
class D20001WireField:
    """Declarative wire field for one D2-00-01 message variant."""

    name: str
    segments: tuple[D20001BitSegment, ...]
    boolean: bool = False
    signed_bits: int | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise ValueError("field name must be a non-empty string")
        segments = tuple(self.segments)
        if not segments or any(not isinstance(item, D20001BitSegment)
                               for item in segments):
            raise TypeError("segments must contain D20001BitSegment values")
        occupied_raw = set()
        for item in segments:
            bits = set(range(item.raw_offset, item.raw_offset + item.width))
            if occupied_raw.intersection(bits):
                raise ValueError("field raw segments must not overlap")
            occupied_raw.update(bits)
        raw_width = max(occupied_raw) + 1
        if self.boolean and (raw_width != 1 or self.signed_bits is not None):
            raise ValueError("boolean fields must be one unsigned bit")
        if self.signed_bits is not None:
            if (isinstance(self.signed_bits, bool) or
                    not isinstance(self.signed_bits, int)):
                raise TypeError("signed_bits must be an integer or None")
            if self.signed_bits != raw_width:
                raise ValueError("signed_bits must cover the assembled field")
        object.__setattr__(self, "segments", segments)

    @property
    def raw_width(self) -> int:
        return max(item.raw_offset + item.width for item in self.segments)

    def decode(self, payload: bytes) -> VLDDecodedField:
        raw_unsigned = 0
        for item in self.segments:
            part = (payload[item.byte_index] >> item.lsb) & ((1 << item.width) - 1)
            raw_unsigned |= part << item.raw_offset
        if self.signed_bits is not None and raw_unsigned & (1 << (self.signed_bits - 1)):
            raw_value = raw_unsigned - (1 << self.signed_bits)
        else:
            raw_value = raw_unsigned
        value = bool(raw_value) if self.boolean else raw_value
        return VLDDecodedField(self.name, raw_value, value, unit=self.unit)

    def encode_into(self, payload: bytearray, value: Any) -> None:
        if self.boolean:
            if type(value) is not bool:
                raise TypeError("%s must be a boolean" % self.name)
            raw = int(value)
        else:
            if isinstance(value, bool) or not isinstance(value, int):
                raise TypeError("%s must be an integer" % self.name)
            raw = value
        if self.signed_bits is not None:
            minimum = -(1 << (self.signed_bits - 1))
            maximum = (1 << (self.signed_bits - 1)) - 1
            if not minimum <= raw <= maximum:
                raise ValueError("%s does not fit into %d signed bits" %
                                 (self.name, self.signed_bits))
            raw &= (1 << self.signed_bits) - 1
        elif not 0 <= raw < (1 << self.raw_width):
            raise ValueError("%s does not fit into %d bits" %
                             (self.name, self.raw_width))
        for item in self.segments:
            mask = ((1 << item.width) - 1) << item.lsb
            part = ((raw >> item.raw_offset) & ((1 << item.width) - 1)) << item.lsb
            payload[item.byte_index] = (payload[item.byte_index] & ~mask) | part


@dataclass(frozen=True, slots=True)
class D20001DerivedField:
    """A documented physical value derived from one or more wire fields."""

    name: str
    raw_source: str
    decoder: Callable[[Mapping[str, Any]], Any]
    unit: str | None = None


@dataclass(frozen=True, slots=True)
class D20001VariantSchema:
    """Schema and strict codec for one documented D2-00-01 variant."""

    message_id: int
    message_type: str
    direction: str
    payload_size: int
    fields: tuple[D20001WireField, ...]
    reserved_masks: tuple[tuple[int, int, str], ...] = ()
    derived_fields: tuple[D20001DerivedField, ...] = ()

    def __post_init__(self) -> None:
        if self.message_id not in range(1, 6):
            raise ValueError("D2-00-01 message ID must be 1 through 5")
        if self.message_type not in "ABCDE" or len(self.message_type) != 1:
            raise ValueError("message_type must be A through E")
        if self.payload_size < 1:
            raise ValueError("payload_size must be positive")
        fields = tuple(self.fields)
        derived = tuple(self.derived_fields)
        names = [item.name for item in fields] + [item.name for item in derived]
        if len(names) != len(set(names)):
            raise ValueError("variant field names must be unique")
        occupied = {(0, bit) for bit in range(3)}  # Message ID selector.
        for definition in fields:
            for segment in definition.segments:
                if segment.byte_index >= self.payload_size:
                    raise ValueError("field segment exceeds variant payload")
                bits = {(segment.byte_index, bit)
                        for bit in range(segment.lsb, segment.lsb + segment.width)}
                if occupied.intersection(bits):
                    raise ValueError("variant wire fields must not overlap")
                occupied.update(bits)
        for byte_index, mask, description in self.reserved_masks:
            if not 0 <= byte_index < self.payload_size or not 0 <= mask <= 0xFF:
                raise ValueError("reserved mask exceeds variant payload")
            if not isinstance(description, str) or not description:
                raise ValueError("reserved masks require a description")
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "derived_fields", derived)
        object.__setattr__(self, "reserved_masks", tuple(self.reserved_masks))

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset(("message_id", "message_type", "direction") +
                         tuple(item.name for item in self.fields) +
                         tuple(item.name for item in self.derived_fields))

    def decode_payload(self, payload: bytes) -> VLDDecodedMessage:
        data = _payload_bytes(payload)
        if len(data) < self.payload_size:
            raise ValueError("D2-00-01 message %s requires at least %d payload bytes" %
                             (self.message_type, self.payload_size))
        if data[0] & 0x07 != self.message_id:
            raise ValueError("payload does not contain D2-00-01 message %s" %
                             self.message_type)
        prefix = data[:self.payload_size]
        for byte_index, mask, description in self.reserved_masks:
            if prefix[byte_index] & mask:
                raise ValueError("D2-00-01 %s must be zero" % description)
        decoded = {
            "message_id": VLDDecodedField("message_id", self.message_id,
                                           self.message_id),
            "message_type": VLDDecodedField("message_type", self.message_id,
                                             self.message_type),
            "direction": VLDDecodedField("direction", self.message_id,
                                          self.direction),
        }
        semantic = {}
        for definition in self.fields:
            result = definition.decode(prefix)
            decoded[definition.name] = result
            semantic[definition.name] = result.value
        for definition in self.derived_fields:
            value = definition.decoder(MappingProxyType(semantic))
            source = decoded[definition.raw_source]
            status = (VLDValueStatus.VALID if value is not None
                      else VLDValueStatus.UNMAPPED)
            decoded[definition.name] = VLDDecodedField(
                definition.name, source.raw, value, status, definition.unit,
                None if value is not None else "value is not defined for this variant state",
            )
        return VLDDecodedMessage(prefix, decoded)

    def encode(
        self,
        values: Mapping[str, Any],
        *,
        base_payload: bytes | None = None,
        require_all: bool = True,
    ) -> bytes:
        """Encode documented wire fields and preserve any extension bytes."""

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        definitions = {item.name: item for item in self.fields}
        unknown = set(values).difference(definitions)
        if unknown:
            raise ValueError("unknown or derived D2-00-01 fields: %s" %
                             ", ".join(sorted(unknown)))
        missing = set(definitions).difference(values)
        if require_all and missing:
            raise ValueError("missing D2-00-01 fields: %s" %
                             ", ".join(sorted(missing)))
        if base_payload is None:
            data = bytearray(self.payload_size)
        else:
            data = bytearray(_payload_bytes(base_payload))
            if len(data) < self.payload_size:
                raise ValueError("base payload is too short for message %s" %
                                 self.message_type)
        data[0] = (data[0] & 0xF8) | self.message_id
        for name, definition in definitions.items():
            if name in values:
                definition.encode_into(data, values[name])
        for byte_index, mask, description in self.reserved_masks:
            if data[byte_index] & mask:
                raise ValueError("D2-00-01 %s must be zero" % description)
        return bytes(data)


@dataclass(frozen=True, slots=True)
class D20001Schema:
    """Selector for the five documented D2-00-01 message variants."""

    variants: Mapping[int, D20001VariantSchema]
    eep: str = "D2-00-01"
    name: str = "RCP with temperature measurement and display"

    def __post_init__(self) -> None:
        variants = dict(self.variants)
        if set(variants) != set(range(1, 6)):
            raise ValueError("D2-00-01 requires variants 1 through 5")
        if any(key != variant.message_id for key, variant in variants.items()):
            raise ValueError("variant registry key does not match message ID")
        object.__setattr__(self, "variants", MappingProxyType(variants))

    @property
    def field_names(self) -> frozenset[str]:
        return frozenset().union(*(variant.field_names
                                   for variant in self.variants.values()))

    def decode_payload(self, payload: bytes) -> VLDDecodedMessage:
        data = _payload_bytes(payload)
        if not data:
            raise ValueError("D2-00-01 requires at least 1 payload byte")
        message_id = data[0] & 0x07
        try:
            variant = self.variants[message_id]
        except KeyError as exc:
            raise EEPNotImplementedError(
                "D2-00-01 message ID %d is not defined; supported IDs are 1 through 5" %
                message_id
            ) from exc
        return variant.decode_payload(data)

    def decode_message(self, message: Any) -> VLDDecodedMessage:
        if getattr(message, "org", None) != 0xD2:
            raise WrongOrgError
        return self.decode_payload(message.data)

    def encode_variant(self, variant: int | str, values: Mapping[str, Any], **kwargs: Any) -> bytes:
        """Encode a variant selected by message ID or letter A through E."""

        if isinstance(variant, str):
            matches = [item for item in self.variants.values()
                       if item.message_type == variant.upper()]
            if len(matches) != 1:
                raise KeyError("unknown D2-00-01 message variant %s" % variant)
            schema = matches[0]
        else:
            try:
                schema = self.variants[variant]
            except (KeyError, TypeError) as exc:
                raise KeyError("unknown D2-00-01 message variant %r" % variant) from exc
        return schema.encode(values, **kwargs)


def _d2_segment(byte_index: int, lsb: int, width: int,
                raw_offset: int = 0) -> D20001BitSegment:
    return D20001BitSegment(byte_index, lsb, width, raw_offset)


def _d2_field(name: str, *segments: D20001BitSegment, **kwargs: Any) -> D20001WireField:
    return D20001WireField(name, tuple(segments), **kwargs)


D2_00_01_VARIANT_A = D20001VariantSchema(
    1, "A", "sensor_to_gateway", 2,
    (
        _d2_field("config_valid", _d2_segment(1, 7, 1), boolean=True),
        _d2_field("user_action", _d2_segment(1, 0, 5)),
    ),
    reserved_masks=((0, 0xF8, "message A header reserved bits"),
                    (1, 0x60, "message A reserved bits")),
)

D2_00_01_VARIANT_B = D20001VariantSchema(
    2, "B", "gateway_to_sensor", 5,
    (
        _d2_field("fan_manual", _d2_segment(0, 7, 1), boolean=True),
        _d2_field("fan_speed", _d2_segment(0, 4, 3)),
        _d2_field("more_data", _d2_segment(0, 3, 1), boolean=True),
        _d2_field("presence", _d2_segment(1, 5, 3)),
        _d2_field("figure_type", _d2_segment(1, 0, 5)),
        _d2_field("figure_value_raw", _d2_segment(2, 0, 8),
                  _d2_segment(3, 0, 8, 8)),
        _d2_field("user_notification", _d2_segment(4, 4, 1), boolean=True),
        _d2_field("window_open", _d2_segment(4, 3, 1), boolean=True),
        _d2_field("no_dew_point_warning", _d2_segment(4, 2, 1), boolean=True),
        _d2_field("cooling", _d2_segment(4, 1, 1), boolean=True),
        _d2_field("heating", _d2_segment(4, 0, 1), boolean=True),
    ),
    derived_fields=(D20001DerivedField(
        "figure_value", "figure_value_raw",
        lambda values: (values["figure_value_raw"] / 100.0
                        if 1 <= values["figure_type"] <= 7 or
                        values["figure_type"] in (14, 16)
                        else values["figure_value_raw"]),
    ),),
)

D2_00_01_VARIANT_C = D20001VariantSchema(
    3, "C", "sensor_to_gateway", 4,
    (
        _d2_field("fan_speed", _d2_segment(0, 4, 3)),
        _d2_field("presence", _d2_segment(1, 5, 3)),
        _d2_field("setpoint_type", _d2_segment(1, 0, 5)),
        _d2_field("setpoint_raw", _d2_segment(2, 0, 8),
                  _d2_segment(3, 0, 8, 8), signed_bits=16),
    ),
    reserved_masks=((0, 0x88, "message C reserved bits"),),
    derived_fields=(D20001DerivedField(
        "setpoint", "setpoint_raw",
        lambda values: (values["setpoint_raw"] / 100.0
                        if values["setpoint_type"] == 5 and
                        -1270 <= values["setpoint_raw"] <= 1270 else None),
        unit="°",
    ),),
)

D2_00_01_VARIANT_D = D20001VariantSchema(
    4, "D", "sensor_to_gateway", 3,
    (
        _d2_field("channel_type", _d2_segment(2, 4, 4)),
        _d2_field("measurement_raw", _d2_segment(1, 0, 8),
                  _d2_segment(2, 0, 4, 8)),
    ),
    reserved_masks=((0, 0xF8, "message D header reserved bits"),),
    derived_fields=(D20001DerivedField(
        "measurement", "measurement_raw",
        lambda values: (values["measurement_raw"] / 100.0
                        if values["channel_type"] == 0 and
                        values["measurement_raw"] <= 4000 else None),
        unit="°C",
    ),),
)

D2_00_01_VARIANT_E = D20001VariantSchema(
    5, "E", "gateway_to_sensor", 6,
    (
        _d2_field("more_data", _d2_segment(0, 3, 1), boolean=True),
        _d2_field("setpoint_range_raw", _d2_segment(1, 0, 7)),
        _d2_field("setpoint_steps", _d2_segment(2, 0, 7)),
        _d2_field("measurement_interval_raw", _d2_segment(3, 4, 4),
                  _d2_segment(4, 0, 2, 4)),
        _d2_field("presence_levels", _d2_segment(4, 5, 3)),
        _d2_field("fan_levels", _d2_segment(4, 2, 3)),
        _d2_field("significant_temperature_difference_raw", _d2_segment(5, 4, 4)),
        _d2_field("keep_alive_measurements_raw", _d2_segment(5, 0, 3)),
    ),
    reserved_masks=((0, 0xF0, "message E header reserved bits"),
                    (1, 0x80, "message E set-point reserved bit"),
                    (2, 0x80, "message E step-count reserved bit"),
                    (3, 0x0F, "message E timing reserved bits"),
                    (5, 0x08, "message E final reserved bit")),
    derived_fields=(
        D20001DerivedField(
            "setpoint_range", "setpoint_range_raw",
            lambda values: (values["setpoint_range_raw"] / 10.0
                            if values["setpoint_range_raw"] else None), unit="°"),
        D20001DerivedField(
            "measurement_interval", "measurement_interval_raw",
            lambda values: (values["measurement_interval_raw"] * 10
                            if 1 <= values["measurement_interval_raw"] <= 60
                            else None), unit="s"),
        D20001DerivedField(
            "significant_temperature_difference",
            "significant_temperature_difference_raw",
            lambda values: values["significant_temperature_difference_raw"] * 0.2,
            unit="°C"),
        D20001DerivedField(
            "keep_alive_measurements", "keep_alive_measurements_raw",
            lambda values: values["keep_alive_measurements_raw"] * 10),
    ),
)

D2_00_01_SCHEMA = D20001Schema({
    1: D2_00_01_VARIANT_A,
    2: D2_00_01_VARIANT_B,
    3: D2_00_01_VARIANT_C,
    4: D2_00_01_VARIANT_D,
    5: D2_00_01_VARIANT_E,
})


D2_06_01_SCHEMA = EEPWireSchema(
    "D2-06-01",
    "Multisensor window handle sensor values",
    VLDLayout((
        VLDField.raw("message_type", 0, 8),
        VLDField.raw("burglary_alarm", 8, 4),
        VLDField.raw("protection_alarm", 12, 4),
        VLDField.raw("handle_position", 16, 4),
        VLDField.raw("window_state", 20, 4),
        VLDField.raw("button_right", 24, 4),
        VLDField.raw("button_left", 28, 4),
        VLDField.raw("motion", 32, 4),
        VLDField.raw("vacation_mode", 36, 4),
        VLDField.linear(
            "temperature", 40, 8, raw_range=(0, 250),
            value_range=(-20.0, 60.0), unit="°C",
            reserved_values=frozenset(range(251, 256)),
        ),
        VLDField.linear(
            "humidity", 48, 8, raw_range=(0, 200),
            value_range=(0.0, 100.0), unit="%",
            reserved_values=frozenset(range(201, 256)),
        ),
        VLDField.raw("illumination", 56, 16, raw_max=60000, unit="lx"),
        VLDField.linear(
            "battery_state", 72, 5, raw_range=(0, 20),
            value_range=(0.0, 100.0), unit="%",
            reserved_values=frozenset(range(21, 32)),
        ),
    ), payload_size=10, name="D2-06-01 sensor values"),
    allowed_raw_values={"message_type": frozenset({0})},
)


_D2_14_COMMON_FIELDS = (
    VLDField.linear(
        "temperature", 0, 10, raw_range=(0, 1000),
        value_range=(-40.0, 60.0), unit="°C",
        reserved_values=frozenset(range(1001, 1024)),
    ),
    VLDField.linear(
        "humidity", 10, 8, raw_range=(0, 200),
        value_range=(0.0, 100.0), unit="%",
        reserved_values=frozenset(range(201, 256)),
    ),
    VLDField.raw("illumination", 18, 17, raw_max=100000, unit="lx"),
    VLDField.raw("acceleration_status", 35, 2),
    VLDField.linear(
        "acceleration_x", 37, 10, raw_range=(0, 1000),
        value_range=(-2.5, 2.5), unit="g",
        reserved_values=frozenset(range(1001, 1024)),
    ),
    VLDField.linear(
        "acceleration_y", 47, 10, raw_range=(0, 1000),
        value_range=(-2.5, 2.5), unit="g",
        reserved_values=frozenset(range(1001, 1024)),
    ),
    VLDField.linear(
        "acceleration_z", 57, 10, raw_range=(0, 1000),
        value_range=(-2.5, 2.5), unit="g",
        reserved_values=frozenset(range(1001, 1024)),
    ),
)

D2_14_40_SCHEMA = EEPWireSchema(
    "D2-14-40",
    "Indoor multisensor",
    VLDLayout(_D2_14_COMMON_FIELDS, payload_size=9, name="D2-14-40"),
)

D2_14_41_SCHEMA = EEPWireSchema(
    "D2-14-41",
    "Indoor multisensor with contact",
    VLDLayout(
        _D2_14_COMMON_FIELDS + (VLDField.boolean("contact", 67),),
        payload_size=9,
        name="D2-14-41",
    ),
)


def d2_compatibility_adapter(eep: str) -> EEPCompatibilityAdapter:
    """Return a parity adapter for a schema-backed D2 profile.

    Imports are local to keep this optional module independent from the EEP
    registry during package import.  D2-00-01 uses its dedicated selected
    variant codec because several compound fields are little-endian.
    """

    from .eep import D2_00_01, D2_06_01, D2_14_40, D2_14_41

    adapters = {
        "D2-00-01": EEPCompatibilityAdapter(
            D2_00_01_SCHEMA, D2_00_01.decode_message,
            {name: name for name in D2_00_01_SCHEMA.field_names
             if not name.endswith("_raw") or name in {
                 "figure_value_raw", "setpoint_raw", "measurement_raw",
                 "setpoint_range_raw", "measurement_interval_raw",
             }},
        ),
        "D2-06-01": EEPCompatibilityAdapter(
            D2_06_01_SCHEMA, D2_06_01.decode_message,
            {
                "message_type": "message_type",
                "burglary_alarm": "burglary_alarm",
                "protection_alarm": "protection_alarm",
                "handle_position": "handle_position",
                "window_state": "window_state",
                "button_right": "button_right",
                "button_left": "button_left",
                "motion": "motion",
                "vacation_mode": "vacation_mode",
                "temperature": "temperature",
                "humidity": "humidity",
                "illumination": "illumination",
                "battery_state": "battery_state",
            },
        ),
        "D2-14-40": EEPCompatibilityAdapter(
            D2_14_40_SCHEMA, D2_14_40.decode_message,
            {
                "temperature": "temperature", "humidity": "humidity",
                "illumination": "illumination",
                "acceleration_status": "acceleration_status",
                "acceleration_x": "acceleration_x",
                "acceleration_y": "acceleration_y",
                "acceleration_z": "acceleration_z",
            },
        ),
        "D2-14-41": EEPCompatibilityAdapter(
            D2_14_41_SCHEMA, D2_14_41.decode_message,
            {
                "temperature": "temperature", "humidity": "humidity",
                "illumination": "illumination",
                "acceleration_status": "acceleration_status",
                "acceleration_x": "acceleration_x",
                "acceleration_y": "acceleration_y",
                "acceleration_z": "acceleration_z", "contact": "contact",
            },
        ),
    }
    try:
        return adapters[eep]
    except KeyError as exc:
        raise KeyError("no schema compatibility adapter for %s" % eep) from exc


__all__ = [
    "D2_00_01_SCHEMA",
    "D2_00_01_VARIANT_A",
    "D2_00_01_VARIANT_B",
    "D2_00_01_VARIANT_C",
    "D2_00_01_VARIANT_D",
    "D2_00_01_VARIANT_E",
    "D2_06_01_SCHEMA",
    "D2_14_40_SCHEMA",
    "D2_14_41_SCHEMA",
    "D20001BitSegment",
    "D20001DerivedField",
    "D20001Schema",
    "D20001VariantSchema",
    "D20001WireField",
    "EEPCompatibilityAdapter",
    "EEPWireSchema",
    "d2_compatibility_adapter",
]
