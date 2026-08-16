"""Offline tests for the complete common A5-38-08 gateway commands."""

import unittest

from eltakobus.eep import (
    A5_38_08, CentralCommandBlind, CentralCommandControlVariable,
    CentralCommandSwitching,
)
from eltakobus.error import WrongOrgError
from eltakobus.message import RPSMessage


ADDRESS = bytes.fromhex("01020304")


class TestA53808Commands(unittest.TestCase):
    """Protect command identifiers, DB positions and bit meanings."""

    def test_normal_switching_does_not_lock_by_default(self):
        """Regular light commands use the documented unlocked bytes 0x09/0x08."""
        on = A5_38_08(1, switching=CentralCommandSwitching(0, 1, 0, 0, 1)).encode_message(ADDRESS)
        off = A5_38_08(1, switching=CentralCommandSwitching(0, 1, 0, 0, 0)).encode_message(ADDRESS)
        self.assertEqual((0x09, 0x08), (on.data[3], off.data[3]))

    def test_setpoint_shift_round_trip(self):
        """Command 0x03 stores a -12.7..12.8 K shift in DB1."""
        command = A5_38_08(3, setpoint_shift=1.2, learn_button=1)
        decoded = A5_38_08.decode_message(command.encode_message(ADDRESS))
        self.assertAlmostEqual(1.2, decoded.setpoint_shift, places=1)
        self.assertEqual(1, decoded.learn_button)

    def test_basic_setpoint_round_trip(self):
        """Command 0x04 stores the absolute basic setpoint in 0.2 °C steps."""
        command = A5_38_08(4, basic_setpoint=20.0, learn_button=1)
        decoded = A5_38_08.decode_message(command.encode_message(ADDRESS))
        self.assertAlmostEqual(20.0, decoded.basic_setpoint, places=1)

    def test_control_variable_round_trip(self):
        """Command 0x05 preserves override, mode, energy and occupancy bits."""
        control = CentralCommandControlVariable(50, controller_mode=2,
                                                controller_state=1,
                                                learn_button=1,
                                                energy_holdoff=1,
                                                occupancy=2)
        decoded = A5_38_08.decode_message(A5_38_08(5, control_variable=control).encode_message(ADDRESS))
        self.assertAlmostEqual(50.0, decoded.control_variable.control_variable, delta=0.5)
        self.assertEqual((2, 1, 1, 1, 2), (
            decoded.control_variable.controller_mode,
            decoded.control_variable.controller_state,
            decoded.control_variable.learn_button,
            decoded.control_variable.energy_holdoff,
            decoded.control_variable.occupancy,
        ))

    def test_fan_stage_round_trip(self):
        """Command 0x06 accepts stages 0..3 and 255 for automatic mode."""
        for stage in (0, 2, 3, 255):
            with self.subTest(stage=stage):
                message = A5_38_08(6, fan_stage=stage).encode_message(ADDRESS)
                decoded = A5_38_08.decode_message(message)
                self.assertEqual(stage, decoded.fan_stage.fan_stage)

    def test_blind_command_round_trip(self):
        """Command 0x07 preserves blind parameters and control flags."""
        blind = CentralCommandBlind(parameter_1=25, parameter_2=75,
                                    function=4, learn_button=1,
                                    send_status=1, position_angle=1,
                                    service_mode=0)
        decoded = A5_38_08.decode_message(
            A5_38_08(7, blind=blind).encode_message(ADDRESS))
        self.assertEqual((25, 75, 4, 1, 1, 1, 0), (
            decoded.blind.parameter_1, decoded.blind.parameter_2,
            decoded.blind.function, decoded.blind.learn_button,
            decoded.blind.send_status, decoded.blind.position_angle,
            decoded.blind.service_mode))

    def test_decode_rejects_wrong_org(self):
        """Central commands only accept 4BS organization 0x07 telegrams."""
        with self.assertRaises(WrongOrgError):
            A5_38_08.decode_message(RPSMessage(ADDRESS, 0, bytes(1)))


if __name__ == "__main__":
    unittest.main()
