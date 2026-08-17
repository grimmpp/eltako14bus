"""Passive mDNS discovery for supported LAN gateways.

The :mod:`zeroconf` dependency is optional and imported only by
:meth:`LanGatewayDiscovery.start`. Discovery never opens a gateway connection
or sends an Eltako telegram.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import logging
from threading import RLock
from typing import Any, Callable, Iterable, Mapping

from .const import GatewayDeviceType

LOGGER = logging.getLogger(__name__)

SERVICE_TYPE_SMARTCONN = "_bsc-sc-socket._tcp.local."
SERVICE_TYPE_TCM515 = "_tcm515._tcp.local."
SUPPORTED_SERVICE_TYPES = (SERVICE_TYPE_SMARTCONN, SERVICE_TYPE_TCM515)


def _normalise_service_type(value: str) -> str:
    value = str(value).strip().lower()
    return value if value.endswith(".") else value + "."


def _normalise_name(value: str) -> str:
    return str(value).strip().lower().rstrip(".")


def _text(value: Any) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)


def _properties(info: Any) -> Mapping[str, Any]:
    return {_text(key).strip().lower(): value for key, value in (getattr(info, "properties", None) or {}).items()}


def _gateway_type(service_type: str, name: str, info: Any) -> GatewayDeviceType:
    """Map reference product names, then use the service-family fallback."""
    properties = _properties(info)
    product_parts = [name]
    for key in ("product", "model", "device", "description"):
        if properties.get(key) is not None:
            product_parts.append(_text(properties[key]))
    product = " ".join(product_parts).lower().replace("_", "-")
    if "virtual-network-gateway-adapter" in product:
        return GatewayDeviceType.LAN_ESP2
    if "smartconn" in product or "eul" in product:
        return GatewayDeviceType.LAN
    if service_type in (SERVICE_TYPE_SMARTCONN, SERVICE_TYPE_TCM515):
        return GatewayDeviceType.LAN
    raise ValueError(f"unsupported LAN gateway service type: {service_type}")


def _ipv4_address(info: Any) -> str | None:
    for raw in (getattr(info, "addresses", None) or ()):
        try:
            address = ipaddress.ip_address(raw)
        except (ValueError, TypeError):
            continue
        if address.version == 4:
            return str(address)
    raw = getattr(info, "address", None)
    if raw is not None:
        try:
            address = ipaddress.ip_address(raw)
        except (ValueError, TypeError):
            return None
        if address.version == 4:
            return str(address)
    return None


@dataclass(frozen=True, slots=True)
class LanGatewayService:
    """Resolved metadata and endpoint information for one LAN gateway."""

    name: str
    hostname: str
    ipv4_address: str | None
    port: int
    service_type: str
    gateway_device_type: GatewayDeviceType

    @property
    def endpoint(self) -> tuple[str, int] | None:
        """Return the IPv4 TCP endpoint, or ``None`` when no IPv4 is present."""
        return None if self.ipv4_address is None else (self.ipv4_address, self.port)


class LanGatewayDiscovery:
    """Passive discovery backed by an injectable Zeroconf browser."""

    def __init__(
        self,
        *,
        service_types: Iterable[str] = SUPPORTED_SERVICE_TYPES,
        zeroconf_factory: Callable[[], Any] | None = None,
        browser_factory: Callable[[Any, str, Any], Any] | None = None,
        on_change: Callable[[str, LanGatewayService], None] | None = None,
    ) -> None:
        self.service_types = tuple(_normalise_service_type(item) for item in service_types)
        self._zeroconf_factory = zeroconf_factory
        self._browser_factory = browser_factory
        self._on_change = on_change
        self._zeroconf: Any = None
        self._browsers: list[Any] = []
        self._services: dict[tuple[str, str], LanGatewayService] = {}
        self._lock = RLock()
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def services(self) -> tuple[LanGatewayService, ...]:
        with self._lock:
            return tuple(sorted(self._services.values(), key=lambda item: item.name))

    def start(self) -> None:
        """Start mDNS browsers; import ``zeroconf`` only at this point."""
        with self._lock:
            if self._running:
                return
            if self._zeroconf_factory is None or self._browser_factory is None:
                try:
                    from zeroconf import ServiceBrowser, Zeroconf
                except ImportError as exc:
                    raise RuntimeError(
                        "LAN discovery requires the optional 'discovery' extra "
                        "(pip install 'eltako14bus[discovery]')"
                    ) from exc
                self._zeroconf_factory = Zeroconf
                self._browser_factory = lambda zc, service_type, listener: ServiceBrowser(zc, service_type, listener)
            self._zeroconf = self._zeroconf_factory()
            self._running = True
            try:
                listener = _ServiceListener(self)
                self._browsers = [
                    self._browser_factory(self._zeroconf, service_type, listener)
                    for service_type in self.service_types
                ]
            except Exception:
                self._running = False
                self._close_zeroconf()
                raise

    def stop(self) -> None:
        """Stop browsers and close the mDNS socket."""
        with self._lock:
            if not self._running and self._zeroconf is None:
                return
            for browser in self._browsers:
                cancel = getattr(browser, "cancel", None)
                if callable(cancel):
                    cancel()
            self._browsers = []
            self._running = False
            self._close_zeroconf()

    def _close_zeroconf(self) -> None:
        zeroconf = self._zeroconf
        self._zeroconf = None
        close = getattr(zeroconf, "close", None)
        if callable(close):
            close()

    def add_service(self, service_type: str, name: str, info: Any | None = None) -> LanGatewayService | None:
        return self._upsert("add", service_type, name, info)

    def update_service(self, service_type: str, name: str, info: Any | None = None) -> LanGatewayService | None:
        return self._upsert("update", service_type, name, info)

    def remove_service(self, service_type: str, name: str) -> LanGatewayService | None:
        key = (_normalise_service_type(service_type), _normalise_name(name))
        with self._lock:
            service = self._services.pop(key, None)
        if service is not None:
            self._notify("remove", service)
        return service

    def _upsert(self, action: str, service_type: str, name: str, info: Any | None) -> LanGatewayService | None:
        service_type = _normalise_service_type(service_type)
        if service_type not in self.service_types:
            return None
        if info is None:
            info_getter = getattr(self._zeroconf, "get_service_info", None)
            info = info_getter(service_type, name) if callable(info_getter) else None
        if info is None:
            LOGGER.debug("mDNS service %s has no resolvable ServiceInfo", name)
            return None
        service = LanGatewayService(
            name=_text(name),
            hostname=_text(getattr(info, "server", "") or "").rstrip("."),
            ipv4_address=_ipv4_address(info),
            port=int(getattr(info, "port", 0) or 0),
            service_type=service_type,
            gateway_device_type=_gateway_type(service_type, _text(name), info),
        )
        key = (service_type, _normalise_name(name))
        with self._lock:
            self._services[key] = service
        self._notify(action, service)
        return service

    def _notify(self, action: str, service: LanGatewayService) -> None:
        if self._on_change is not None:
            self._on_change(action, service)

    def find_endpoints(
        self,
        *,
        gateway_device_type: GatewayDeviceType | str | None = None,
        service_type: str | None = None,
        name: str | None = None,
    ) -> tuple[LanGatewayService, ...]:
        expected_type = GatewayDeviceType.find(gateway_device_type) if gateway_device_type is not None else None
        expected_service = _normalise_service_type(service_type) if service_type else None
        expected_name = _normalise_name(name) if name else None
        return tuple(
            service for service in self.services
            if (expected_type is None or service.gateway_device_type is expected_type)
            and (expected_service is None or service.service_type == expected_service)
            and (expected_name is None or _normalise_name(service.name) == expected_name)
            and service.endpoint is not None
        )

    def find_endpoint(self, **filters: Any) -> LanGatewayService | None:
        """Return the first matching IPv4 endpoint, or ``None``."""
        return next(iter(self.find_endpoints(**filters)), None)


class _ServiceListener:
    """Adapt Zeroconf callbacks to the public discovery component."""

    def __init__(self, discovery: LanGatewayDiscovery) -> None:
        self._discovery = discovery

    def add_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self._discovery.add_service(service_type, name)

    def update_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self._discovery.update_service(service_type, name)

    def remove_service(self, zeroconf: Any, service_type: str, name: str) -> None:
        self._discovery.remove_service(service_type, name)


__all__ = [
    "LanGatewayDiscovery",
    "LanGatewayService",
    "SERVICE_TYPE_SMARTCONN",
    "SERVICE_TYPE_TCM515",
    "SUPPORTED_SERVICE_TYPES",
]
