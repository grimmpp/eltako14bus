"""Optional ESP3 conversion helpers for ESP2 gateway adapters.

The core package does not require the third-party ``enocean`` package.  When
it is installed, :class:`ESP3MessageAdapter` can create ESP3 ``Packet``
instances from the library's ESP2 messages.  Incoming packets are converted
defensively: malformed or unsupported packets are logged and ignored instead
of terminating the communicator thread.
"""

import logging

from .message import ESP2Message, RPSMessage, Regular1BSMessage, Regular4BSMessage, VLDMessage, prettify


class ESP3MessageAdapter:
    """Translate between ESP2 messages and enocean-compatible ESP3 packets."""

    def __init__(self, logger=None):
        self.log = logger or logging.getLogger("eltakobus.esp3")

    @staticmethod
    def _enocean_types():
        try:
            from enocean.protocol.packet import PACKET, Packet, RORG
        except ImportError as exc:
            raise RuntimeError(
                "ESP3 support requires the optional 'enocean' dependency"
            ) from exc
        return Packet, PACKET, RORG

    def convert_esp2_to_esp3(self, message, packet_factory=None):
        """Return an ESP3 RADIO_ERP1 packet or ``None`` for unsupported input.

        RADIO_ERP1 optional data is always seven bytes: sub-telegram,
        destination, signal quality, and security level.  The final security
        byte is required by the ESP3 specification even when it is zero.
        """
        if packet_factory is None:
            Packet, packet_types, rorgs = self._enocean_types()
            packet_factory = lambda data, optional: Packet(
                packet_types.RADIO_ERP1, data, optional
            )
            radio_erp1 = packet_types.RADIO_ERP1
            rorg_rps, rorg_bs1, rorg_bs4 = rorgs.RPS, rorgs.BS1, rorgs.BS4
        else:
            # Test doubles can provide a simple factory without importing
            # enocean.  Numeric ESP3 values are part of the wire protocol.
            radio_erp1 = 1
            rorg_rps, rorg_bs1, rorg_bs4 = 0xF6, 0xD5, 0xA5

        try:
            if isinstance(message, RPSMessage):
                rorg, data = rorg_rps, [message.data[0]]
            elif isinstance(message, Regular1BSMessage):
                rorg, data = rorg_bs1, [message.data[0]]
            elif isinstance(message, Regular4BSMessage):
                rorg, data = rorg_bs4, list(message.data)
            else:
                self.log.warning("Cannot convert unsupported ESP2 message: %r", message)
                return None

            if len(message.address) != 4 or len(data) not in (1, 4):
                raise ValueError("invalid ESP2 radio data or address length")
            command = [rorg] + data + list(message.address) + [message.status]
            sub_telegram = 3 if getattr(message, "outgoing", False) else 0
            optional = [sub_telegram, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x00]
            packet = packet_factory(command, optional)
            packet.rorg = rorg
            packet.packet_type = radio_erp1
            return packet
        except (TypeError, ValueError, IndexError, AttributeError) as exc:
            self.log.warning("Ignoring ESP2-to-ESP3 conversion error: %s", exc)
            return None

    def convert_esp3_to_esp2(self, packet):
        """Return a prettified ESP2 message, or ``None`` on bad input.

        This method intentionally never raises for malformed packets received
        from a radio module.  The caller can continue processing subsequent
        telegrams.
        """
        try:
            raw_rorg = getattr(packet, "rorg", None)
            if raw_rorg is None:
                return self._convert_response(packet)
            rorg = int(raw_rorg)
            data = list(packet.data)
            optional = list(packet.optional or [])
            if rorg == 0xF6:
                org = 0x05
            elif rorg == 0xD5:
                org = 0x06
            elif rorg == 0xA5:
                org = 0x07
            elif rorg == 0xD2:
                if len(data) < 6:
                    raise ValueError("ESP3 VLD radio packet has too few data bytes")
                sub_telegram = optional[0] if optional else 0
                return VLDMessage(
                    address=bytes(data[-5:-1]),
                    status=data[-1],
                    data=bytes(data[1:-5]),
                    outgoing=sub_telegram == 3,
                )
            else:
                return self._convert_response(packet)

            if len(data) < (10 if org == 0x07 else 7):
                raise ValueError("ESP3 radio packet has too few data bytes")
            sub_telegram = optional[0] if optional else 0
            h_seq = 0x6B if sub_telegram == 3 else 0x0B
            if org == 0x07:
                body = bytes([h_seq, org] + data[1:])
            else:
                body = bytes([h_seq, org] + data[1:2] + [0, 0, 0] + data[2:])
            if len(body) != 11:
                raise ValueError("converted ESP2 body has invalid length")
            return prettify(ESP2Message(body))
        except (TypeError, ValueError, IndexError, AttributeError) as exc:
            self.log.warning("Ignoring ESP3-to-ESP2 conversion error: %s", exc)
            return None

    def _convert_response(self, packet):
        """Convert known successful common-command responses."""
        try:
            response = int(packet.response)
            response_data = list(packet.response_data)
            if response != 0:
                self.log.warning(
                    "Ignoring ESP3 response with return code %s", response
                )
                return None
            if len(response_data) == 4:
                org, payload = 0x98, response_data + [0, 0, 0, 0]
            elif len(response_data) == 32:
                org, payload = 0x8C, response_data[4:8] + response_data[12:16]
            elif len(response_data) == 2:
                org, payload = 0x99, response_data + [0, 0]
            else:
                self.log.warning(
                    "Ignoring unsupported ESP3 response payload length: %d",
                    len(response_data),
                )
                return None
            if org == 0x98:
                body = [0x8B, org] + payload + [0]
            elif org == 0x8C:
                body = [0x8B, org] + payload + [0]
            else:
                body = [0x8B, org] + payload + [0, 0, 0, 0, 0]
            return prettify(ESP2Message(bytes(body)))
        except (TypeError, ValueError, IndexError, AttributeError) as exc:
            self.log.warning("Ignoring ESP3 response conversion error: %s", exc)
            return None

    def handle_packet(self, packet, callback, translate=True):
        """Deliver a packet while isolating conversion failures.

        Returns the converted message when one was delivered, otherwise
        ``None``.  Callback exceptions are also logged so the receive worker
        remains alive.
        """
        try:
            message = self.convert_esp3_to_esp2(packet) if translate else packet
        except Exception:
            self.log.exception("Unexpected ESP3 conversion failure; packet ignored")
            return None
        if message is None or callback is None:
            return message
        try:
            callback(message)
        except Exception:
            self.log.exception("ESP3 receive callback failed")
        return message
