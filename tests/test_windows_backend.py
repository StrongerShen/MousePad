import ctypes
import errno
import unittest
from unittest.mock import Mock, patch

import mousepad
import windows_backend as windows


class WindowsTests(unittest.TestCase):
    def caps(self):
        caps = windows.JoyCaps()
        caps.caps = 0x13  # Z、R、POV
        caps.buttons = 12
        for axis in ('x', 'y', 'z', 'r'):
            setattr(caps, axis + 'max', 65535)
        return caps

    def test_axis_ranges_and_diagonal_hat(self):
        state = windows.JoyState(x=0, y=65535, z=32767, r=32768, pov=4500)
        self.assertEqual(windows.axes(state, self.caps()),
                         [-32767, 32767, 0, 0, 32767, -32767])
        state.pov = 65535
        self.assertEqual(windows.axes(state, self.caps())[4:], [0, 0])
        self.assertEqual(windows.normalize(200, 100, 100), 0)

    def output(self):
        output = windows.WindowsOutput.__new__(windows.WindowsOutput)
        output.held = set()
        output.emit = Mock()
        return output

    def test_drag_release_and_negative_scroll(self):
        output = self.output()
        output.button(272, True)
        output.button(272, True)
        output.move(-10, 5)
        output.scroll(-1)
        output.close()
        events = [call.args[0] for call in output.emit.call_args_list]
        self.assertEqual([event.mouse.flags for event in events], [2, 1, 0x800, 4])
        self.assertEqual(events[1].mouse.dx, -10)
        self.assertEqual(events[2].mouse.data, 0xFFFFFF88)
        self.assertFalse(output.held)

    def test_keyboard_mapping_and_failed_release_cleanup(self):
        output = self.output()
        output.key(104)
        events = [call.args[0] for call in output.emit.call_args_list]
        self.assertEqual([(event.type, event.key.vk, event.key.flags) for event in events],
                         [(1, 0x21, 1), (1, 0x21, 3)])
        output.emit = Mock(side_effect=[None, OSError('失敗'), None])
        with self.assertRaises(OSError):
            output.key(14)
        self.assertIn(14, output.held)
        output.close()
        self.assertFalse(output.held)

    def test_poll_initial_buttons_and_disconnect(self):
        caps = self.caps()
        states = [windows.JoyState(x=32767, y=32767, r=32767, pov=65535, buttons=b)
                  for b in (2, 2, 0, 2)]
        joystick = Mock()
        joystick.read.side_effect = states + [OSError(errno.ENODEV, '拔除')]
        output = Mock()
        controller = mousepad.MousePadController('0', output)
        with patch('windows_backend.time.sleep'), self.assertRaises(OSError):
            windows.poll(joystick, 0, caps, controller, .015)
        self.assertEqual(output.button.call_args_list,
                         [unittest.mock.call(272, False), unittest.mock.call(272, True)])

    def test_diagnose_does_not_operate_desktop(self):
        joystick = Mock()
        joystick.read.side_effect = [windows.JoyState(pov=65535), KeyboardInterrupt]
        controller = Mock()
        with patch('windows_backend.time.sleep'), patch('windows_backend.sys.stdout') as stdout, \
                self.assertRaises(KeyboardInterrupt):
            windows.poll(joystick, 0, self.caps(), controller, .015, diagnose=True)
        self.assertFalse(controller.mock_calls)
        self.assertTrue(stdout.write.call_args.args[0].startswith('\x1b[H\x1b[J'))
        self.assertFalse(stdout.write.call_args.args[0].endswith('\n'))

    def test_diagnostic_screen_restores_terminal_on_interrupt(self):
        import sys
        kernel = Mock()
        kernel.GetConsoleMode.return_value = 1
        kernel.SetConsoleMode.return_value = 1
        with patch.dict(sys.modules, {'msvcrt': Mock()}), \
                patch('windows_backend.c.WinDLL', return_value=kernel, create=True), \
                patch('windows_backend.sys.stdout') as stdout:
            with self.assertRaises(KeyboardInterrupt):
                with windows.diagnostic_screen():
                    raise KeyboardInterrupt
        self.assertEqual([call.args[0] for call in stdout.write.call_args_list],
                         ['\x1b[?1049h\x1b[?25l', '\x1b[?25h\x1b[?1049l'])
        self.assertEqual(kernel.SetConsoleMode.call_count, 2)

    def test_diagnose_rejects_redirected_output(self):
        with patch('windows_backend.sys.stdout.isatty', return_value=False):
            with self.assertRaisesRegex(RuntimeError, '互動式終端機'):
                with windows.diagnostic_screen():
                    self.fail('重新導向輸出時不應進入診斷畫面')

    def test_sendinput_failure_is_reported(self):
        output = self.output()
        output.emit = windows.WindowsOutput.emit.__get__(output)
        output.send = Mock(return_value=0)
        with self.assertRaises(OSError):
            output.move(1, 1)

    def test_windows_input_abi(self):
        self.assertEqual(ctypes.sizeof(windows.Input),
                         40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28)

    def test_unused_windows_slot_is_skipped(self):
        joystick = windows.WindowsJoystick.__new__(windows.WindowsJoystick)
        joystick.count = Mock(return_value=2)
        joystick.get_state = Mock(side_effect=[0, 165])
        joystick.get_caps = Mock(return_value=0)
        self.assertEqual([index for index, caps in joystick.devices()], [0])

    def test_shutdown_releases_mouse_after_poll_failure(self):
        from types import SimpleNamespace
        kernel = Mock()
        kernel.CreateMutexW.return_value = 100
        joystick = Mock()
        joystick.devices.return_value = [(0, self.caps())]
        output = Mock()
        args = SimpleNamespace(list=False, device='0', diagnose=False,
                               wait=False, speed=18, deadzone=7000)
        with patch('windows_backend.WindowsJoystick', return_value=joystick), \
                patch('windows_backend.WindowsOutput', return_value=output), \
                patch('windows_backend.c.WinDLL', return_value=kernel, create=True), \
                patch('windows_backend.c.get_last_error', return_value=0, create=True), \
                patch('windows_backend.poll', side_effect=KeyboardInterrupt), \
                patch('builtins.print'), self.assertRaises(KeyboardInterrupt):
            windows.run_windows(args, mousepad.MousePadController, .015)
        output.close.assert_called_once()
        kernel.CloseHandle.assert_called_once_with(100)


if __name__ == '__main__':
    unittest.main()
