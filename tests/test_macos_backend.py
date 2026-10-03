import errno
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import macos_backend
import macos_hid
import mousepad


class MacInputTests(unittest.TestCase):
    def test_hid_hat_and_buttons_use_existing_controller_mapping(self):
        output = Mock()
        controller = mousepad.MousePadController('0', output)
        hid = Mock()
        hid.connected.return_value = True
        hid.axes.return_value = 6
        hid.hats.return_value = 1
        hid.buttons.return_value = 12
        hid.axis.side_effect = lambda _joystick, axis: {0: 32767, 1: 0, 3: 0}.get(axis, 0)
        hid.hat.side_effect = [0, 0x08, 0x08]
        pressed = [False, True, True]
        hid.button.side_effect = lambda _joystick, button: pressed.pop(0) if button == 1 else False
        axes, buttons, hat = {}, {}, [None]
        for _ in range(3):
            macos_backend.poll_controller(hid, 99, controller, axes, buttons, hat,
                                          mousepad.TICK)
        self.assertEqual(output.key.call_args_list, [unittest.mock.call(102)])
        self.assertEqual(output.button.call_args_list, [unittest.mock.call(272, True)])
        self.assertEqual(output.move.call_count, 3)
        self.assertTrue(all(call.args == (18, 0) for call in output.move.call_args_list))

    def test_disconnect_prevents_input_and_is_identifiable(self):
        hid = Mock()
        hid.connected.return_value = False
        with self.assertRaises(OSError) as caught:
            macos_backend.poll_controller(hid, 99, Mock(), {}, {}, [None], 0.015)
        self.assertEqual(caught.exception.errno, errno.ENODEV)
        hid.axis.assert_not_called()


class HIDConversionTests(unittest.TestCase):
    def test_8_bit_joystick_axes_and_hat_values(self):
        hid = macos_hid.HIDJoystick.__new__(macos_hid.HIDJoystick)
        hid.axis_elements = {0: (10, 0, 255)}
        hid.hat_elements = [20]
        hid._read = Mock(side_effect=[0, 127, 255, 0, 2, 4, 6, 8])
        self.assertEqual([hid.axis(99, 0) for _ in range(3)],
                         [-32768, -129, 32767])
        self.assertEqual([hid.hat(99, 0) for _ in range(5)], [1, 2, 4, 8, 0])


class MacOutputTests(unittest.TestCase):
    def test_scroll_uses_nonvariadic_coregraphics_call(self):
        output = macos_backend.MacOutput.__new__(macos_backend.MacOutput)
        output.scroll_event = Mock(return_value=42)
        output._post = Mock()
        output.scroll(-1)
        output.scroll(1)
        self.assertEqual(output.scroll_event.call_args_list, [
            unittest.mock.call(None, 1, 1, -1, 0, 0),
            unittest.mock.call(None, 1, 1, 1, 0, 0),
        ])
        self.assertEqual(output._post.call_count, 2)

    def test_drag_and_shutdown_release_held_mouse_button(self):
        output = macos_backend.MacOutput.__new__(macos_backend.MacOutput)
        output.held = set()
        output._location = Mock(side_effect=lambda: macos_backend.CGPoint(100, 200))
        output.mouse_event = Mock(side_effect=lambda _source, kind, point, button:
                                  (kind, point.x, point.y, button))
        output._post = Mock()
        output.button(272, True)
        output.move(5, -3)
        output.close()
        self.assertEqual(output._post.call_args_list, [
            unittest.mock.call((1, 100, 200, 0)),
            unittest.mock.call((6, 105, 197, 0)),
            unittest.mock.call((2, 100, 200, 0)),
        ])
        self.assertEqual(output.held, set())

    def test_no_joystick_skips_accessibility_requirement(self):
        args = SimpleNamespace(list=True, device=None)
        with patch('macos_backend.HIDJoystick') as hid, \
             patch('macos_backend.MacOutput') as output, patch('builtins.print'):
            hid.return_value.devices.return_value = []
            self.assertEqual(macos_backend.run_macos(args, Mock(), 0.015), 0)
        output.assert_not_called()
        hid.return_value.quit.assert_called_once()


if __name__ == '__main__':
    unittest.main()
