"""Keep the gateway overview aligned with the implemented transport surface."""

import unittest
from pathlib import Path


class GatewayDocumentationTest(unittest.TestCase):
    """Ensure users can find the supported gateway families and transports."""

    def test_gateway_overview_documents_implemented_transport_choices(self):
        """The overview must mention serial, TCP, ESP3 and CoAP usage."""
        root = Path(__file__).parents[1]
        overview = (root / "docs" / "GATEWAYS.md").read_text(encoding="utf-8")
        for term in (
            "FAM14",
            "FAM-USB",
            "USB300",
            "RS485SerialInterfaceV2",
            "ESP2TCPSerialInterface",
            "ESP3FrameParser",
            "CoAPInterface",
            "zeroconf",
        ):
            with self.subTest(term=term):
                self.assertIn(term, overview)

    def test_overview_is_linked_from_readme(self):
        """The gateway documentation is part of the developer entry points."""
        root = Path(__file__).parents[1]
        readme = (root / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/GATEWAYS.md", readme)


if __name__ == "__main__":
    unittest.main()
