"""Protocol-vector tests for generic EnOcean Universal Teach-In telegrams."""

import unittest
from dataclasses import FrozenInstanceError

import eltakobus
from eltakobus.radio import RadioTelegram, TelegramDirection
from eltakobus.ute import (
    UTECommunication,
    UTEParseError,
    UTEProfile,
    UTERequest,
    UTERequestType,
    UTEResponse,
    UTEResponseCode,
)


SENDER = bytes.fromhex("0582f709")
GATEWAY = bytes.fromhex("ffdec801")


def incoming(payload: str, *, sender: bytes = SENDER, optional: bool = True):
    metadata = dict(
        destination=b"\xff" * 4,
        subtelegram_count=1,
        rssi_dbm=-85,
        security_level=0,
    ) if optional else {}
    return RadioTelegram(
        0xD4,
        bytes.fromhex(payload),
        sender,
        0,
        TelegramDirection.INCOMING,
        **metadata,
    )


class TestUTERequest(unittest.TestCase):
    """Validate query bit fields, EEP identity and lossless rebuilding."""

    def test_openocean_capture_vector_is_decoded(self):
        request = UTERequest.from_telegram(incoming("a00146000e01d2"))

        self.assertEqual("D2-01-0E", request.profile.eep)
        self.assertEqual(0x046, request.profile.manufacturer)
        self.assertEqual(1, request.channel_count)
        self.assertEqual(1, request.channel)
        self.assertEqual(UTECommunication.BIDIRECTIONAL, request.communication)
        self.assertEqual(UTERequestType.NOT_SPECIFIC, request.request_type)
        self.assertTrue(request.response_expected)
        self.assertTrue(request.teach_in)
        self.assertFalse(request.delete)

    def test_query_round_trip_preserves_all_protocol_fields(self):
        request = UTERequest(
            profile=UTEProfile(0xD2, 0x14, 0x41, 0x7FF),
            sender=SENDER,
            channel_count=0xFF,
            communication=UTECommunication.UNIDIRECTIONAL,
            response_expected=False,
            request_type=UTERequestType.DELETE,
            status=0x80,
        )
        telegram = request.to_telegram()

        self.assertEqual(bytes.fromhex("50ffff074114d2"), telegram.payload)
        self.assertEqual(b"\xff" * 4, telegram.destination)
        self.assertEqual(TelegramDirection.OUTGOING, telegram.direction)
        self.assertEqual(request, UTERequest.from_telegram(telegram))

    def test_control_bit_matrix_round_trips_without_cross_talk(self):
        profile = UTEProfile(0xD2, 0xFF, 0x80, 0x7FF)
        for communication in UTECommunication:
            for response_expected in (False, True):
                for request_type in UTERequestType:
                    with self.subTest(
                        communication=communication,
                        response_expected=response_expected,
                        request_type=request_type,
                    ):
                        request = UTERequest(
                            profile,
                            SENDER,
                            0xFF,
                            communication,
                            response_expected,
                            request_type,
                        )
                        decoded = UTERequest.from_telegram(request.to_telegram())
                        self.assertEqual(request, decoded)
                        self.assertEqual(
                            response_expected,
                            not bool(request.to_telegram().payload[0] & 0x40),
                        )

    def test_module_and_package_exports_are_available(self):
        self.assertIs(UTERequest, eltakobus.UTERequest)
        self.assertIs(UTEResponse, eltakobus.UTEResponse)
        self.assertIs(UTEResponseCode, eltakobus.UTEResponseCode)

    def test_query_rejects_wrong_shape_reserved_values_and_response(self):
        invalid = (
            RadioTelegram(0xD2, b"\0" * 7, SENDER, 0),
            RadioTelegram(0xD4, b"\0" * 6, SENDER, 0),
            incoming("300146000e01d2"),
            incoming("000146080e01d2"),
            incoming("910146000e01d2"),
        )
        for telegram in invalid:
            with self.subTest(payload=telegram.payload.hex()):
                with self.assertRaises(UTEParseError):
                    UTERequest.from_telegram(telegram)

    def test_models_are_immutable_and_validate_ranges(self):
        profile = UTEProfile(0xD2, 1, 2, 3)
        with self.assertRaises(FrozenInstanceError):
            profile.rorg = 0
        with self.assertRaises(ValueError):
            UTEProfile(0xD2, 1, 2, 0x800)
        with self.assertRaises(ValueError):
            UTERequest(
                profile, SENDER, 256, UTECommunication.BIDIRECTIONAL,
                True, UTERequestType.TEACH_IN,
            )


class TestUTEResponse(unittest.TestCase):
    """Verify every response code and destination-sensitive serialization."""

    def test_accepted_response_matches_reference_vector(self):
        request = UTERequest.from_telegram(incoming("a00146000e01d2"))
        response = request.build_response(
            GATEWAY, UTEResponseCode.TEACH_IN_ACCEPTED
        )
        telegram = response.to_telegram()

        self.assertEqual(bytes.fromhex("910146000e01d2"), telegram.payload)
        self.assertEqual(SENDER, telegram.destination)
        self.assertEqual(GATEWAY, telegram.sender)
        self.assertEqual(
            bytes.fromhex("03") + SENDER + b"\xff\x00",
            telegram.to_esp3_fields()[1],
        )
        self.assertEqual(response, UTEResponse.from_telegram(telegram))
        self.assertTrue(response.accepted)

    def test_all_response_codes_round_trip(self):
        request = UTERequest.from_telegram(incoming("200146000e01d2"))
        for code in UTEResponseCode:
            with self.subTest(code=code):
                response = request.build_response(GATEWAY, code)
                decoded = UTEResponse.from_telegram(response.to_telegram())
                self.assertEqual(code, decoded.response_code)
                self.assertEqual(
                    code in (
                        UTEResponseCode.TEACH_IN_ACCEPTED,
                        UTEResponseCode.DELETE_ACCEPTED,
                    ),
                    decoded.accepted,
                )

    def test_response_success_must_match_an_explicit_request_type(self):
        teach_in = UTERequest.from_telegram(incoming("000146000e01d2"))
        delete = UTERequest.from_telegram(incoming("100146000e01d2"))

        with self.assertRaisesRegex(ValueError, "cannot accept deletion"):
            teach_in.build_response(GATEWAY, UTEResponseCode.DELETE_ACCEPTED)
        with self.assertRaisesRegex(ValueError, "cannot accept teach-in"):
            delete.build_response(GATEWAY, UTEResponseCode.TEACH_IN_ACCEPTED)
        self.assertEqual(
            UTEResponseCode.NOT_ACCEPTED,
            teach_in.build_response(
                GATEWAY, UTEResponseCode.NOT_ACCEPTED
            ).response_code,
        )

    def test_parsed_response_without_optional_data_needs_destination_to_send(self):
        response = UTEResponse.from_telegram(
            incoming("910146000e01d2", sender=GATEWAY, optional=False)
        )
        self.assertIsNone(response.destination)
        with self.assertRaisesRegex(ValueError, "destination is required"):
            response.to_telegram()
        self.assertEqual(SENDER, response.to_telegram(SENDER).destination)

    def test_response_rejects_query_and_invalid_control_bits(self):
        for payload in ("000146000e01d2", "d10146000e01d2", "110146000e01d2"):
            with self.subTest(payload=payload):
                with self.assertRaises(UTEParseError):
                    UTEResponse.from_telegram(incoming(payload))


if __name__ == "__main__":
    unittest.main()
