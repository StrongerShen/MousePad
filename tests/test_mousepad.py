import argparse
import errno
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mousepad


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.output = Mock()
        self.controller = mousepad.MousePadController('/dev/input/js0', self.output)

    def test_small_motion_accumulates_and_neutral_clears_remainder(self):
        self.controller.dx = 7100
        for tick in range(30):
            self.controller.tick(tick * mousepad.TICK, mousepad.TICK)
        self.assertGreater(sum(call.args[0] for call in self.output.move.call_args_list), 0)
        self.controller.dx = 0
        self.controller.tick(1, mousepad.TICK)
        self.assertEqual(self.controller.remainder_x, 0)

    def test_scrolling_does_not_reduce_cursor_updates(self):
        self.controller.dx = 32767
        self.controller.scroll_dy = 32767
        for tick in range(16):
            self.controller.tick(tick * mousepad.TICK, mousepad.TICK)
        self.assertEqual(self.output.move.call_count, 16)
        self.assertTrue(all(call.args == (18, 0) for call in self.output.move.call_args_list))
        self.assertEqual(self.output.scroll.call_count, 2)
        self.output.scroll.assert_called_with(-1)

    def test_hat_requires_transition_and_initial_state_does_not_send_key(self):
        self.controller.handle_axis(4, -32767, initial=True)
        self.controller.handle_axis(4, -32767)
        self.output.key.assert_not_called()
        self.controller.handle_axis(4, 0)
        self.controller.handle_axis(4, -32767)
        self.controller.handle_axis(4, -32767)
        self.output.key.assert_called_once_with(102)

    def test_mouse_press_release_and_keyboard_release(self):
        self.controller.handle_button(1, 1)
        self.controller.handle_button(1, 0)
        self.assertEqual(self.output.button.call_args_list,
                         [unittest.mock.call(272, True), unittest.mock.call(272, False)])
        self.controller.handle_button(0, 0)
        self.output.key.assert_not_called()
        self.controller.handle_button(0, 1)
        self.output.key.assert_called_once_with(14)

    def test_minimum_axis_value_is_clamped(self):
        self.assertEqual(self.controller.velocity(-32768), -18)

    def test_invalid_parameters(self):
        for value in ('0', '-1', 'nan', 'inf'):
            with self.assertRaises(argparse.ArgumentTypeError):
                mousepad.positive_speed(value)
        for value in ('-1', '32767'):
            with self.assertRaises(argparse.ArgumentTypeError):
                mousepad.valid_deadzone(value)

    def test_disconnect_closes_joystick(self):
        with patch('mousepad.os.open', return_value=10), \
             patch('mousepad.os.close') as close, \
             patch('mousepad.select.select', return_value=([10], [], [])), \
             patch('mousepad.os.read', return_value=b''), \
             patch('builtins.print'):
            with self.assertRaises(OSError):
                self.controller.run()
            close.assert_called_once_with(10)


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.args = SimpleNamespace(device=None, speed=18, deadzone=7000, wait=True)

    def test_waits_without_device_then_connects(self):
        with patch('mousepad.select_device', side_effect=[None, '/dev/input/js0']), \
             patch('mousepad.time.sleep') as sleep, \
             patch('mousepad.run_connected') as run, patch('builtins.print'):
            mousepad.run_devices(self.args)
        sleep.assert_called_once_with(1)
        run.assert_called_once_with('/dev/input/js0', 18, 7000)

    def test_disconnect_selects_replacement_device(self):
        with patch('mousepad.select_device', side_effect=['/dev/input/js0', '/dev/input/js1']), \
             patch('mousepad.time.sleep'), patch('builtins.print'), \
             patch('mousepad.run_connected', side_effect=[OSError(errno.ENODEV, '拔除'), None]) as run:
            mousepad.run_devices(self.args)
        self.assertEqual([call.args[0] for call in run.call_args_list],
                         ['/dev/input/js0', '/dev/input/js1'])

    def test_connected_device_is_not_reselected(self):
        with patch('mousepad.select_device', return_value='/dev/input/js0') as select_device, \
             patch('mousepad.run_connected'):
            mousepad.run_devices(self.args)
        select_device.assert_called_once()

    def test_explicit_missing_device_does_not_fall_back(self):
        with patch('mousepad.os.path.exists', return_value=False), \
             patch('mousepad.glob.glob') as glob:
            self.assertIsNone(mousepad.select_device('/dev/input/by-id/chosen-joystick'))
        glob.assert_not_called()

    def test_auto_selection_skips_unreadable_device(self):
        with patch('mousepad.glob.glob', return_value=['/dev/input/js0', '/dev/input/js1']), \
             patch('mousepad.os.access', side_effect=[False, True]):
            self.assertEqual(mousepad.select_device(), '/dev/input/js1')

    def test_permission_error_is_not_hidden_as_disconnection(self):
        with patch('mousepad.select_device', return_value='/dev/input/js0'), \
             patch('mousepad.run_connected', side_effect=PermissionError(errno.EACCES, 'denied')):
            with self.assertRaises(PermissionError):
                mousepad.run_devices(self.args)

    def test_disconnect_cleans_output_before_returning_to_selector(self):
        output = Mock()
        with patch('mousepad.os.open', return_value=10), patch('mousepad.os.close'), \
             patch('mousepad.UInputOutput', return_value=output), patch('mousepad.time.sleep'), \
             patch('mousepad.MousePadController') as controller:
            controller.return_value.run.side_effect = OSError(errno.ENODEV, '拔除')
            with self.assertRaises(OSError):
                mousepad.run_connected('/dev/input/js0', 18, 7000)
        output.close.assert_called_once()

    def test_manual_mode_without_device_returns_error(self):
        self.args.wait = False
        with patch('mousepad.select_device', return_value=None):
            with self.assertRaises(RuntimeError):
                mousepad.run_devices(self.args)


class OutputTests(unittest.TestCase):
    def make_output(self):
        output = mousepad.UInputOutput.__new__(mousepad.UInputOutput)
        output.fd = 10
        output.created = True
        output.held = {272, 273}
        return output

    def test_cleanup_releases_buttons_before_destroy_and_is_idempotent(self):
        output = self.make_output()
        events = []
        with patch.object(output, 'emit', side_effect=lambda *args: events.append(args)), \
             patch('mousepad.fcntl.ioctl', side_effect=lambda *args: events.append('destroy')), \
             patch('mousepad.os.close') as close:
            output.close()
            output.close()
        self.assertIn((1, 272, 0), events)
        self.assertIn((1, 273, 0), events)
        self.assertEqual(events[-1], 'destroy')
        close.assert_called_once_with(10)

    def test_cleanup_closes_fd_even_if_release_fails(self):
        output = self.make_output()
        with patch.object(output, 'emit', side_effect=OSError('write failed')), \
             patch('mousepad.fcntl.ioctl') as ioctl, \
             patch('mousepad.os.close') as close:
            with self.assertRaises(OSError):
                output.close()
        ioctl.assert_called_once_with(10, 0x5502)
        close.assert_called_once_with(10)

    def test_failed_device_setup_closes_fd(self):
        with patch('mousepad.os.open', return_value=10), \
             patch('mousepad.fcntl.ioctl', side_effect=OSError('setup failed')), \
             patch('mousepad.os.close') as close:
            with self.assertRaises(OSError):
                mousepad.UInputOutput()
            close.assert_called_once_with(10)


if __name__ == '__main__':
    unittest.main()
