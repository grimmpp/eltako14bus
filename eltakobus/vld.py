"""Declarative, dependency-free bit fields for EnOcean VLD payloads.

VLD offsets are counted in the notation used by the EnOcean EEP documents:
offset zero is the most-significant bit of the first payload byte.  The engine
is deliberately independent of EEP registration, XML parsers and transports.
It can therefore be used for official profiles, vendor-specific telegrams and
standalone conformance tests alike.
"""

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from enum import Enum
import math
from types import MappingProxyType
from typing import Any, Optional


class VLDFieldType(str, Enum):
    """Conversion applied to the raw unsigned field value."""

    RAW = "raw"
    LINEAR = "linear"
    ENUM = "enum"
    BOOLEAN = "boolean"


class VLDValueStatus(str, Enum):
    """Classification of a decoded raw value."""

    VALID = "valid"
    RESERVED = "reserved"
    ERROR = "error"
    UNMAPPED = "unmapped"


def _integer(name: str, value: Any, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("%s must be an integer" % name)
    if value < minimum:
        raise ValueError("%s must be at least %d" % (name, minimum))
    return value


def _number(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("%s must be a finite number" % name)
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("%s must be a finite number" % name)
    return result


def _payload_bytes(name: str, value: Any) -> bytes:
    if isinstance(value, (str, int)):
        raise TypeError("%s must be bytes-like" % name)
    try:
        return bytes(value)
    except (TypeError, ValueError) as exc:
        raise TypeError("%s must be bytes-like" % name) from exc


def _pair(name: str, value: Any) -> tuple[Any, Any]:
    try:
        pair = tuple(value)
    except TypeError as exc:
        raise TypeError("%s must contain exactly two values" % name) from exc
    if len(pair) != 2:
        raise ValueError("%s must contain exactly two values" % name)
    return pair[0], pair[1]


@dataclass(frozen=True, slots=True)
class VLDDecodedField:
    """One decoded field, including its wire value and validity state."""

    name: str
    raw: int
    value: Any
    status: VLDValueStatus = VLDValueStatus.VALID
    unit: Optional[str] = None
    reason: Optional[str] = None

    @property
    def is_valid(self) -> bool:
        """Whether ``value`` is a usable decoded value."""

        return self.status is VLDValueStatus.VALID


@dataclass(frozen=True, slots=True)
class VLDField:
    """Immutable definition of one MSB-first VLD bit field.

    Prefer the :meth:`raw`, :meth:`linear`, :meth:`enum` and
    :meth:`boolean` constructors.  ``raw_min`` and ``raw_max`` describe valid
    operational values; special values may sit outside that interval while
    still fitting into ``width``.
    """

    name: str
    offset: int
    width: int
    field_type: VLDFieldType = VLDFieldType.RAW
    raw_min: int = 0
    raw_max: Optional[int] = None
    physical_min: Optional[float] = None
    physical_max: Optional[float] = None
    unit: Optional[str] = None
    enum_values: Mapping[int, Any] = field(default_factory=dict)
    false_raw: int = 0
    true_raw: int = 1
    reserved_values: frozenset[int] = field(default_factory=frozenset)
    error_values: Mapping[int, str] = field(default_factory=dict)
    description: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must be a non-empty string")
        if self.unit is not None and not isinstance(self.unit, str):
            raise TypeError("unit must be a string or None")
        if self.description is not None and not isinstance(self.description, str):
            raise TypeError("description must be a string or None")
        object.__setattr__(self, "offset", _integer("offset", self.offset))
        object.__setattr__(self, "width", _integer("width", self.width, minimum=1))

        try:
            field_type = VLDFieldType(self.field_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("field_type must be raw, linear, enum or boolean") from exc
        object.__setattr__(self, "field_type", field_type)

        maximum = (1 << self.width) - 1
        raw_min = _integer("raw_min", self.raw_min)
        raw_max = maximum if self.raw_max is None else _integer("raw_max", self.raw_max)
        if raw_max > maximum:
            raise ValueError("raw_max does not fit into width")
        if raw_min > raw_max:
            raise ValueError("raw_min must not exceed raw_max")
        object.__setattr__(self, "raw_min", raw_min)
        object.__setattr__(self, "raw_max", raw_max)

        reserved = frozenset(self.reserved_values)
        errors = dict(self.error_values)
        enums = dict(self.enum_values)
        for raw in reserved:
            self._validate_wire_value("reserved value", raw, maximum)
        for raw, reason in errors.items():
            self._validate_wire_value("error value", raw, maximum)
            if not isinstance(reason, str) or not reason:
                raise ValueError("error descriptions must be non-empty strings")
        if reserved.intersection(errors):
            raise ValueError("a raw value cannot be both reserved and an error")

        if field_type is VLDFieldType.LINEAR:
            if self.physical_min is None or self.physical_max is None:
                raise ValueError("linear fields require physical_min and physical_max")
            physical_min = _number("physical_min", self.physical_min)
            physical_max = _number("physical_max", self.physical_max)
            if physical_min == physical_max:
                raise ValueError("physical_min and physical_max must differ")
            if raw_min == raw_max:
                raise ValueError("linear fields require at least two raw values")
            object.__setattr__(self, "physical_min", physical_min)
            object.__setattr__(self, "physical_max", physical_max)
        elif self.physical_min is not None or self.physical_max is not None:
            raise ValueError("physical ranges are only valid for linear fields")

        if field_type is VLDFieldType.ENUM:
            if not enums:
                raise ValueError("enum fields require at least one mapping")
            semantic_values = []
            for raw, semantic in enums.items():
                self._validate_wire_value("enum value", raw, maximum)
                if not raw_min <= raw <= raw_max:
                    raise ValueError("enum raw values must be inside the operational range")
                try:
                    hash(semantic)
                except TypeError as exc:
                    raise TypeError("enum semantic values must be hashable") from exc
                if semantic in semantic_values:
                    raise ValueError("enum semantic values must be unique")
                semantic_values.append(semantic)
            if set(enums).intersection(reserved) or set(enums).intersection(errors):
                raise ValueError("enum values cannot also be reserved or errors")
        elif enums:
            raise ValueError("enum_values are only valid for enum fields")

        false_raw = _integer("false_raw", self.false_raw)
        true_raw = _integer("true_raw", self.true_raw)
        if field_type is VLDFieldType.BOOLEAN:
            if false_raw == true_raw:
                raise ValueError("false_raw and true_raw must differ")
            for raw in (false_raw, true_raw):
                self._validate_wire_value("boolean value", raw, maximum)
                if not raw_min <= raw <= raw_max:
                    raise ValueError("boolean values must be inside the operational range")
                if raw in reserved or raw in errors:
                    raise ValueError("boolean values cannot also be reserved or errors")
        elif false_raw != 0 or true_raw != 1:
            raise ValueError("custom boolean values require a boolean field")

        object.__setattr__(self, "reserved_values", reserved)
        object.__setattr__(self, "error_values", MappingProxyType(errors))
        object.__setattr__(self, "enum_values", MappingProxyType(enums))
        object.__setattr__(self, "false_raw", false_raw)
        object.__setattr__(self, "true_raw", true_raw)

    @staticmethod
    def _validate_wire_value(name: str, value: Any, maximum: int) -> None:
        value = _integer(name, value)
        if value > maximum:
            raise ValueError("%s does not fit into width" % name)

    def __hash__(self) -> int:
        return hash((
            self.name, self.offset, self.width, self.field_type,
            self.raw_min, self.raw_max, self.physical_min, self.physical_max,
            self.unit, tuple(sorted(self.enum_values.items())), self.false_raw,
            self.true_raw, self.reserved_values,
            tuple(sorted(self.error_values.items())),
            self.description,
        ))

    @classmethod
    def raw(cls, name: str, offset: int, width: int, **kwargs: Any) -> "VLDField":
        """Create an unsigned raw field."""

        return cls(name, offset, width, VLDFieldType.RAW, **kwargs)

    @classmethod
    def linear(
        cls,
        name: str,
        offset: int,
        width: int,
        *,
        raw_range: tuple[int, int],
        value_range: tuple[float, float],
        **kwargs: Any,
    ) -> "VLDField":
        """Create a linearly scaled field, including descending scales."""

        raw_range = _pair("raw_range", raw_range)
        value_range = _pair("value_range", value_range)
        return cls(
            name, offset, width, VLDFieldType.LINEAR,
            raw_min=raw_range[0], raw_max=raw_range[1],
            physical_min=value_range[0], physical_max=value_range[1],
            **kwargs,
        )

    @classmethod
    def enum(
        cls,
        name: str,
        offset: int,
        width: int,
        values: Mapping[int, Any],
        **kwargs: Any,
    ) -> "VLDField":
        """Create an enumerated field mapping wire values to semantic values."""

        return cls(
            name, offset, width, VLDFieldType.ENUM,
            enum_values=values, **kwargs,
        )

    @classmethod
    def boolean(
        cls,
        name: str,
        offset: int,
        width: int = 1,
        *,
        false_raw: int = 0,
        true_raw: int = 1,
        **kwargs: Any,
    ) -> "VLDField":
        """Create a boolean field with explicit false and true wire values."""

        return cls(
            name, offset, width, VLDFieldType.BOOLEAN,
            false_raw=false_raw, true_raw=true_raw, **kwargs,
        )

    def extract_raw(self, payload: bytes) -> int:
        """Extract the unsigned raw value from a bytes-like payload."""

        payload = _payload_bytes("payload", payload)
        required_bits = self.offset + self.width
        if len(payload) * 8 < required_bits:
            raise ValueError(
                "payload is too short for field %r (needs %d bits)" %
                (self.name, required_bits)
            )
        shift = len(payload) * 8 - required_bits
        return (int.from_bytes(payload, "big") >> shift) & ((1 << self.width) - 1)

    def decode(self, payload: bytes) -> VLDDecodedField:
        """Decode this field while preserving special and unknown raw values."""

        raw = self.extract_raw(payload)
        if raw in self.error_values:
            return VLDDecodedField(
                self.name, raw, None, VLDValueStatus.ERROR, self.unit,
                self.error_values[raw],
            )
        if raw in self.reserved_values:
            return VLDDecodedField(
                self.name, raw, None, VLDValueStatus.RESERVED, self.unit,
                "reserved raw value",
            )
        if not self.raw_min <= raw <= self.raw_max:
            return VLDDecodedField(
                self.name, raw, None, VLDValueStatus.UNMAPPED, self.unit,
                "raw value is outside the operational range",
            )

        if self.field_type is VLDFieldType.RAW:
            value = raw
        elif self.field_type is VLDFieldType.LINEAR:
            value = self.physical_min + (
                (raw - self.raw_min) *
                (self.physical_max - self.physical_min) /
                (self.raw_max - self.raw_min)
            )
        elif self.field_type is VLDFieldType.ENUM:
            if raw not in self.enum_values:
                return VLDDecodedField(
                    self.name, raw, None, VLDValueStatus.UNMAPPED, self.unit,
                    "raw value has no enum mapping",
                )
            value = self.enum_values[raw]
        else:
            if raw not in (self.false_raw, self.true_raw):
                return VLDDecodedField(
                    self.name, raw, None, VLDValueStatus.UNMAPPED, self.unit,
                    "raw value has no boolean mapping",
                )
            value = raw == self.true_raw
        return VLDDecodedField(self.name, raw, value, unit=self.unit)

    def encode_raw(self, value: Any) -> int:
        """Convert a semantic value into a validated unsigned wire value."""

        if self.field_type is VLDFieldType.RAW:
            raw = _integer(self.name, value)
        elif self.field_type is VLDFieldType.BOOLEAN:
            if type(value) is not bool:
                raise TypeError("%s must be a boolean" % self.name)
            raw = self.true_raw if value else self.false_raw
        elif self.field_type is VLDFieldType.ENUM:
            matches = [raw for raw, semantic in self.enum_values.items()
                       if semantic == value]
            if not matches:
                raise ValueError("%s has no enum mapping for %r" % (self.name, value))
            raw = matches[0]
        else:
            physical = _number(self.name, value)
            lower = min(self.physical_min, self.physical_max)
            upper = max(self.physical_min, self.physical_max)
            if not lower <= physical <= upper:
                raise ValueError(
                    "%s must be between %s and %s%s" %
                    (self.name, lower, upper, " " + self.unit if self.unit else "")
                )
            represented = self.raw_min + (
                (physical - self.physical_min) *
                (self.raw_max - self.raw_min) /
                (self.physical_max - self.physical_min)
            )
            raw = round(represented)
            if not math.isclose(represented, raw, rel_tol=0.0, abs_tol=1e-9):
                raise ValueError(
                    "%s value %r is not exactly representable on the wire" %
                    (self.name, value)
                )

        maximum = (1 << self.width) - 1
        if raw > maximum or not self.raw_min <= raw <= self.raw_max:
            raise ValueError("%s raw value is outside the operational range" % self.name)
        if raw in self.reserved_values or raw in self.error_values:
            raise ValueError("%s cannot encode a reserved or error value" % self.name)
        return raw

    def encode_into(self, payload: bytes, value: Any) -> bytes:
        """Return a payload with this field replaced and all other bits kept."""

        payload = _payload_bytes("payload", payload)
        required_bits = self.offset + self.width
        if len(payload) * 8 < required_bits:
            raise ValueError(
                "payload is too short for field %r (needs %d bits)" %
                (self.name, required_bits)
            )
        raw = self.encode_raw(value)
        shift = len(payload) * 8 - required_bits
        mask = ((1 << self.width) - 1) << shift
        packed = (int.from_bytes(payload, "big") & ~mask) | (raw << shift)
        return packed.to_bytes(len(payload), "big")


@dataclass(frozen=True, slots=True)
class VLDDecodedMessage(Mapping[str, VLDDecodedField]):
    """Immutable decoded payload indexed by field name."""

    payload: bytes
    fields: Mapping[str, VLDDecodedField]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _payload_bytes("payload", self.payload))
        object.__setattr__(self, "fields", MappingProxyType(dict(self.fields)))

    def __hash__(self) -> int:
        return hash((self.payload, tuple(self.fields.items())))

    def __getitem__(self, name: str) -> VLDDecodedField:
        return self.fields[name]

    def __iter__(self) -> Iterator[str]:
        return iter(self.fields)

    def __len__(self) -> int:
        return len(self.fields)

    def value(self, name: str) -> Any:
        """Return a valid semantic value, or raise for a special raw value."""

        decoded = self.fields[name]
        if not decoded.is_valid:
            raise ValueError(
                "field %r is %s (raw %d): %s" %
                (name, decoded.status.value, decoded.raw, decoded.reason)
            )
        return decoded.value


@dataclass(frozen=True, slots=True)
class VLDLayout:
    """Immutable, non-overlapping set of fields for one VLD payload variant."""

    fields: tuple[VLDField, ...]
    payload_size: Optional[int] = None
    name: Optional[str] = None

    def __post_init__(self) -> None:
        fields = tuple(self.fields)
        if not fields and self.payload_size is None:
            raise ValueError("an empty layout requires an explicit payload_size")
        if any(not isinstance(item, VLDField) for item in fields):
            raise TypeError("fields must contain only VLDField definitions")
        names = [item.name for item in fields]
        if len(names) != len(set(names)):
            raise ValueError("field names must be unique")

        occupied: set[int] = set()
        for item in fields:
            bits = set(range(item.offset, item.offset + item.width))
            if occupied.intersection(bits):
                raise ValueError("VLD fields must not overlap")
            occupied.update(bits)

        required_size = max(
            ((item.offset + item.width + 7) // 8 for item in fields),
            default=0,
        )
        if self.payload_size is None:
            payload_size = required_size
        else:
            payload_size = _integer("payload_size", self.payload_size, minimum=1)
            if payload_size < required_size:
                raise ValueError("payload_size is too small for the declared fields")
        object.__setattr__(self, "fields", fields)
        object.__setattr__(self, "payload_size", payload_size)

    def decode(self, payload: bytes) -> VLDDecodedMessage:
        """Decode an exact-size payload into immutable field results."""

        payload = _payload_bytes("payload", payload)
        if len(payload) != self.payload_size:
            raise ValueError(
                "layout requires exactly %d payload bytes, got %d" %
                (self.payload_size, len(payload))
            )
        return VLDDecodedMessage(
            payload,
            {definition.name: definition.decode(payload)
             for definition in self.fields},
        )

    def encode(
        self,
        values: Mapping[str, Any],
        *,
        base_payload: Optional[bytes] = None,
        require_all: bool = True,
    ) -> bytes:
        """Strictly encode values, optionally preserving unspecified bits.

        Unknown names are always rejected.  With the default ``require_all``
        every declared field must be supplied.  Set it to ``False`` for an
        intentional partial update; ``base_payload`` then preserves existing
        values and reserved bits.
        """

        if not isinstance(values, Mapping):
            raise TypeError("values must be a mapping")
        if type(require_all) is not bool:
            raise TypeError("require_all must be a boolean")
        definitions = {item.name: item for item in self.fields}
        unknown = set(values).difference(definitions)
        if unknown:
            raise ValueError("unknown VLD fields: %s" % ", ".join(sorted(unknown)))
        missing = set(definitions).difference(values)
        if require_all and missing:
            raise ValueError("missing VLD fields: %s" % ", ".join(sorted(missing)))

        if base_payload is None:
            payload = bytes(self.payload_size)
        else:
            payload = _payload_bytes("base_payload", base_payload)
            if len(payload) != self.payload_size:
                raise ValueError(
                    "layout requires exactly %d base payload bytes" %
                    self.payload_size
                )
        for definition in self.fields:
            if definition.name in values:
                payload = definition.encode_into(payload, values[definition.name])
        return payload


__all__ = [
    "VLDDecodedField",
    "VLDDecodedMessage",
    "VLDField",
    "VLDFieldType",
    "VLDLayout",
    "VLDValueStatus",
]
