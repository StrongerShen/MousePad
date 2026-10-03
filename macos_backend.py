"""macOS 搖桿輸入與 CoreGraphics 桌面事件；僅在 macOS 載入。"""

import ctypes
import ctypes.util
import errno
import fcntl
import os
import sys
import time

from macos_hid import HIDJoystick


# mousepad.py 使用 Linux evdev 鍵碼；在輸出邊界轉成 macOS 虛擬鍵碼。
KEYCODES = {14: 0x33, 15: 0x30, 57: 0x31, 1: 0x35, 28: 0x24,
            102: 0x73, 107: 0x77, 104: 0x74, 109: 0x79}
MOUSE_BUTTONS = {272: 0, 273: 1, 274: 2}
MOUSE_DOWN = (1, 3, 25)
MOUSE_UP = (2, 4, 26)
MOUSE_DRAG = (6, 7, 27)


class CGPoint(ctypes.Structure):
    _fields_ = [('x', ctypes.c_double), ('y', ctypes.c_double)]


def _function(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


def accessibility_trusted(library):
    trusted = _function(library, 'AXIsProcessTrusted', ctypes.c_bool)
    if trusted():
        return True
    # macOS 提供的提示會開啟「輔助使用」設定；授權仍由使用者決定。
    create = _function(library, 'CFDictionaryCreateMutable', ctypes.c_void_p,
                       ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p)
    set_value = _function(library, 'CFDictionarySetValue', None, ctypes.c_void_p,
                          ctypes.c_void_p, ctypes.c_void_p)
    release = _function(library, 'CFRelease', None, ctypes.c_void_p)
    check = _function(library, 'AXIsProcessTrustedWithOptions', ctypes.c_bool,
                      ctypes.c_void_p)
    options = create(None, 0, None, None)
    if not options:
        return False
    try:
        prompt_key = ctypes.c_void_p.in_dll(library, 'kAXTrustedCheckOptionPrompt').value
        yes = ctypes.c_void_p.in_dll(library, 'kCFBooleanTrue').value
        set_value(options, prompt_key, yes)
        return check(options)
    finally:
        release(options)


class MacOutput:
    def __init__(self):
        path = ctypes.util.find_library('ApplicationServices')
        if not path:
            raise RuntimeError('找不到 macOS ApplicationServices')
        lib = ctypes.CDLL(path)
        if not accessibility_trusted(lib):
            raise RuntimeError('請在開啟的「輔助使用」設定中允許目前的終端機；若未出現提示，請至「系統設定 → 隱私權與安全性 → 輔助使用」手動加入並啟用，然後重新啟動終端機')
        self.create = _function(lib, 'CGEventCreate', ctypes.c_void_p, ctypes.c_void_p)
        self.location = _function(lib, 'CGEventGetLocation', CGPoint, ctypes.c_void_p)
        self.mouse_event = _function(lib, 'CGEventCreateMouseEvent', ctypes.c_void_p,
                                     ctypes.c_void_p, ctypes.c_uint32, CGPoint,
                                     ctypes.c_uint32)
        self.key_event = _function(lib, 'CGEventCreateKeyboardEvent', ctypes.c_void_p,
                                   ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool)
        # 固定參數版本可避免 Apple Silicon 上 ctypes 可變參數傳值失敗。
        self.scroll_event = _function(lib, 'CGEventCreateScrollWheelEvent2', ctypes.c_void_p,
                                      ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32,
                                      ctypes.c_int32, ctypes.c_int32, ctypes.c_int32)
        self.post = _function(lib, 'CGEventPost', None, ctypes.c_uint32, ctypes.c_void_p)
        self.release = _function(lib, 'CFRelease', None, ctypes.c_void_p)
        self.held = set()

    def _post(self, event):
        if not event:
            raise OSError('CoreGraphics 無法建立桌面事件')
        try:
            self.post(0, event)  # kCGHIDEventTap
        finally:
            self.release(event)

    def _location(self):
        event = self.create(None)
        if not event:
            raise OSError('CoreGraphics 無法讀取游標位置')
        try:
            return self.location(event)
        finally:
            self.release(event)

    def move(self, x, y):
        if not (x or y):
            return
        point = self._location()
        point.x += x
        point.y += y
        button = next((MOUSE_BUTTONS[code] for code in (272, 273, 274)
                       if code in self.held), 0)
        kind = MOUSE_DRAG[button] if self.held else 5  # kCGEventMouseMoved
        self._post(self.mouse_event(None, kind, point, button))

    def scroll(self, amount):
        self._post(self.scroll_event(None, 1, 1, amount, 0, 0))

    def button(self, code, down):
        if down == (code in self.held):
            return
        button = MOUSE_BUTTONS[code]
        event = self.mouse_event(None, MOUSE_DOWN[button] if down else MOUSE_UP[button],
                                 self._location(), button)
        self._post(event)
        if down:
            self.held.add(code)
        else:
            self.held.remove(code)

    def key(self, code):
        keycode = KEYCODES[code]
        self._post(self.key_event(None, keycode, True))
        self._post(self.key_event(None, keycode, False))

    def close(self):
        try:
            for code in tuple(self.held):
                self.button(code, False)
        finally:
            self.held.clear()


def poll_controller(hid, joystick, controller, previous_axes, previous_buttons,
                    previous_hat, tick):
    """讀取 HID 軸與按鈕，交給既有的 Logitech 對應邏輯。"""
    hid.update()
    if not hid.connected(joystick):
        raise OSError(errno.ENODEV, '搖桿已中斷連線')
    has_hat = hid.hats(joystick) > 0
    for index in range(min(hid.axes(joystick), 6)):
        if has_hat and index in (4, 5):
            continue
        value = hid.axis(joystick, index)
        if value != previous_axes.get(index):
            controller.handle_axis(index, value, initial=index not in previous_axes)
            previous_axes[index] = value
    if has_hat:
        value = hid.hat(joystick, 0)
        if value != previous_hat[0]:
            # HID hat: 左／右及上／下可同時按下。
            horizontal = -32767 if value & 0x08 else 32767 if value & 0x02 else 0
            vertical = -32767 if value & 0x01 else 32767 if value & 0x04 else 0
            controller.handle_axis(4, horizontal, initial=previous_hat[0] is None)
            controller.handle_axis(5, vertical, initial=previous_hat[0] is None)
            previous_hat[0] = value
    for index in range(min(hid.buttons(joystick), 12)):
        value = bool(hid.button(joystick, index))
        if index in previous_buttons and value != previous_buttons[index]:
            controller.handle_button(index, value)
        previous_buttons[index] = value
    controller.tick(time.monotonic(), tick)


def diagnose(hid, devices, requested):
    if not sys.stdout.isatty():
        raise RuntimeError('--diagnose 需要互動式終端機')
    device = next(((index, ident, name) for index, ident, name in devices
                   if requested is None or requested == index), None)
    if device is None:
        raise RuntimeError('找不到搖桿，請用 --list 確認連線與索引')
    index, ident, name = device
    joystick = hid.open(ident)
    try:
        sys.stdout.write('\x1b[?1049h\x1b[?25l')  # 替代畫面、不顯示游標
        sys.stdout.flush()
        axes, buttons, hats = {}, {}, {}
        try:
            while True:
                changed = False
                for axis in range(hid.axes(joystick)):
                    value = hid.axis(joystick, axis)
                    if axis not in axes or abs(value - axes[axis]) > 1000:
                        axes[axis] = value
                        changed = True
                for button in range(hid.buttons(joystick)):
                    value = bool(hid.button(joystick, button))
                    if button not in buttons or value != buttons[button]:
                        buttons[button] = value
                        changed = True
                for hat in range(hid.hats(joystick)):
                    value = hid.hat(joystick, hat)
                    if hat not in hats or value != hats[hat]:
                        hats[hat] = value
                        changed = True
                if changed:
                    lines = [f'{name}（索引 {index}）',
                             '操作搖桿以查看數值；按 Ctrl+C 結束。', '']
                    lines.extend(f'軸 {axis}: {value:+6d}' for axis, value in axes.items())
                    lines.append('')
                    lines.append('按鈕: ' + '  '.join(
                        f'{button + 1}:{"●" if down else "○"}'
                        for button, down in buttons.items()))
                    lines.extend(f'十字鍵 {hat}: {value}' for hat, value in hats.items())
                    sys.stdout.write('\x1b[H\x1b[J' + '\n'.join(lines))
                    sys.stdout.flush()
                time.sleep(0.03)
        finally:
            sys.stdout.write('\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()
    finally:
        hid.close(joystick)


def run_macos(args, controller_class, tick):
    hid = HIDJoystick()
    try:
        if args.list:
            devices = hid.devices()
            try:
                for index, _id, name in devices:
                    print(f'{index}：{name}')
                if not devices:
                    print('找不到搖桿，請確認 USB／藍牙連線。')
                return 0
            finally:
                hid.release_devices(devices)
        if args.diagnose:
            devices = hid.devices()
            try:
                diagnose(hid, devices, int(args.device) if args.device is not None else None)
            finally:
                hid.release_devices(devices)
        lock_path = f'/tmp/mousepad-{os.getuid()}.lock'
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError('已有 MousePad 執行個體，請先停止再啟動') from error
            selected = int(args.device) if args.device is not None else None
            waiting = False
            while True:
                devices = hid.devices()
                device = next(((i, ident, name) for i, ident, name in devices
                               if selected is None or selected == i), None)
                if device is None:
                    hid.release_devices(devices)
                    if not args.wait:
                        raise RuntimeError('找不到搖桿，請用 --list 確認連線與索引')
                    if not waiting:
                        print('等待搖桿連線……', flush=True)
                        waiting = True
                    time.sleep(1)
                    continue
                waiting = False
                index, ident, name = device
                try:
                    joystick = hid.open(ident)
                    output = MacOutput()
                    try:
                        controller = controller_class(str(index), output, args.speed,
                                                      args.deadzone)
                        print(f'MousePad 已啟動：{name} (索引 {index})', flush=True)
                        print('左搖桿：游標；右搖桿：捲動；按鈕 2／3／4：左／右／中鍵。',
                              flush=True)
                        previous_axes, previous_buttons, previous_hat = {}, {}, [None]
                        last_tick = time.monotonic()
                        while True:
                            now = time.monotonic()
                            poll_controller(hid, joystick, controller, previous_axes,
                                            previous_buttons, previous_hat,
                                            min(now - last_tick, 0.1))
                            last_tick = now
                            time.sleep(max(0, tick - (time.monotonic() - now)))
                    finally:
                        output.close()
                except OSError as error:
                    if not args.wait or error.errno not in (
                            errno.ENODEV, errno.ENOENT, errno.ENXIO, errno.EIO):
                        raise
                    print('搖桿已中斷；將重新偵測。', flush=True)
                    time.sleep(1)
                finally:
                    if hid.active == ident:
                        hid.close(ident)
                    hid.release_devices(devices)
                if not args.wait:
                    return 0
        finally:
            os.close(lock_fd)
    finally:
        hid.quit()
