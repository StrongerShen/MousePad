"""Windows WinMM 搖桿與 SendInput；只使用標準函式庫。"""

import ctypes as c
import errno
import math
import sys
import time
from contextlib import contextmanager, nullcontext

# 固定寬度型別，讓結構也能在 Linux 的模擬測試中正確排列。
WORD, DWORD, UINT, LONG = c.c_uint16, c.c_uint32, c.c_uint32, c.c_int32
KEYCODES = {14: 0x08, 15: 0x09, 57: 0x20, 1: 0x1B, 28: 0x0D,
            102: 0x24, 107: 0x23, 104: 0x21, 109: 0x22}
MOUSE_FLAGS = {272: (0x02, 0x04), 273: (0x08, 0x10), 274: (0x20, 0x40)}


class JoyCaps(c.Structure):
    _fields_ = [('mid', WORD), ('pid', WORD), ('name', c.c_wchar * 32)] + [
        (name, UINT) for name in (
            'xmin', 'xmax', 'ymin', 'ymax', 'zmin', 'zmax', 'buttons',
            'period_min', 'period_max', 'rmin', 'rmax', 'umin', 'umax',
            'vmin', 'vmax', 'caps', 'max_axes', 'axes', 'max_buttons')
    ] + [('regkey', c.c_wchar * 32), ('oem', c.c_wchar * 260)]


class JoyState(c.Structure):
    _fields_ = [(name, DWORD) for name in (
        'size', 'flags', 'x', 'y', 'z', 'r', 'u', 'v', 'buttons',
        'button_number', 'pov', 'reserved1', 'reserved2')]


class MouseInput(c.Structure):
    _fields_ = [('dx', LONG), ('dy', LONG), ('data', DWORD),
                ('flags', DWORD), ('time', DWORD), ('extra', c.c_size_t)]


class KeyInput(c.Structure):
    _fields_ = [('vk', WORD), ('scan', WORD), ('flags', DWORD),
                ('time', DWORD), ('extra', c.c_size_t)]


class InputUnion(c.Union):
    _fields_ = [('mouse', MouseInput), ('key', KeyInput)]


class Input(c.Structure):
    _anonymous_ = ('payload',)
    _fields_ = [('type', DWORD), ('payload', InputUnion)]


def function(lib, name, result, *arguments):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = list(arguments)
    return fn


class WindowsJoystick:
    def __init__(self):
        lib = c.WinDLL('winmm')
        self.count = function(lib, 'joyGetNumDevs', UINT)
        self.get_caps = function(lib, 'joyGetDevCapsW', UINT, c.c_size_t,
                                 c.POINTER(JoyCaps), UINT)
        self.get_state = function(lib, 'joyGetPosEx', UINT, UINT, c.POINTER(JoyState))

    def read(self, index):
        state = JoyState()
        state.size = c.sizeof(state)
        state.flags = 0xFF  # JOY_RETURNALL
        result = self.get_state(index, c.byref(state))
        if result:
            if result in (2, 6, 165, 167):  # 無效索引、無驅動程式、已拔除
                raise OSError(errno.ENODEV, f'搖桿 {index} 未連線（WinMM {result}）')
            raise RuntimeError(f'讀取搖桿 {index} 失敗（WinMM {result}）')
        return state

    def devices(self):
        devices = []
        for index in range(self.count()):
            try:
                self.read(index)
            except OSError:
                continue
            caps = JoyCaps()
            result = self.get_caps(index, c.byref(caps), c.sizeof(caps))
            if result:
                raise RuntimeError(f'讀取搖桿能力失敗（WinMM {result}）')
            devices.append((index, caps))
        return devices


def normalize(value, minimum, maximum):
    if maximum <= minimum:
        return 0
    value = max(minimum, min(maximum, value))
    return round((value - minimum) * 65534 / (maximum - minimum) - 32767)


def axes(state, caps):
    result = [normalize(getattr(state, name), getattr(caps, name + 'min'),
                        getattr(caps, name + 'max'))
              if number < 2 or caps.caps & (1 << (number - 2)) else 0
              for number, name in enumerate(('x', 'y', 'z', 'r'))]
    hat_x = hat_y = 0
    if caps.caps & 0x10 and state.pov != 0xFFFF:
        angle = math.radians(state.pov / 100)
        hat_x = round(math.sin(angle)) * 32767
        hat_y = -round(math.cos(angle)) * 32767
    return result + [hat_x, hat_y]


class WindowsOutput:
    def __init__(self):
        lib = c.WinDLL('user32', use_last_error=True)
        self.send = function(lib, 'SendInput', UINT, UINT, c.POINTER(Input), c.c_int)
        self.held = set()

    def emit(self, event):
        if self.send(1, c.byref(event), c.sizeof(Input)) != 1:
            raise OSError('SendInput 失敗；請確認桌面權限與目標程式的權限層級')

    def move(self, x, y):
        if x or y:
            self.emit(Input(type=0, mouse=MouseInput(dx=x, dy=y, flags=0x01)))

    def scroll(self, amount):
        self.emit(Input(type=0, mouse=MouseInput(data=(amount * 120) & 0xFFFFFFFF,
                                               flags=0x0800)))

    def button(self, code, down):
        if down == (code in self.held):
            return
        self.emit(Input(type=0, mouse=MouseInput(flags=MOUSE_FLAGS[code][0 if down else 1])))
        if down:
            self.held.add(code)
        else:
            self.held.discard(code)

    def key(self, code):
        flags = 0x01 if code in (102, 107, 104, 109) else 0
        self.emit(Input(type=1, key=KeyInput(vk=KEYCODES[code], flags=flags)))
        self.held.add(code)
        self.emit(Input(type=1, key=KeyInput(vk=KEYCODES[code], flags=flags | 0x02)))
        self.held.discard(code)

    def close(self):
        errors = []
        for code in tuple(self.held):
            try:
                if code in MOUSE_FLAGS:
                    self.button(code, False)
                else:
                    flags = 0x03 if code in (102, 107, 104, 109) else 0x02
                    self.emit(Input(type=1, key=KeyInput(vk=KEYCODES[code], flags=flags)))
                    self.held.discard(code)
            except OSError as error:
                errors.append(error)
        if errors:
            raise errors[0]


@contextmanager
def diagnostic_screen():
    """開啟 Windows VT 替代畫面，離開時還原主控台模式與游標。"""
    if not sys.stdout.isatty():
        raise RuntimeError('--diagnose 需要互動式終端機，請在 Windows PowerShell 執行')
    import msvcrt
    kernel = c.WinDLL('kernel32', use_last_error=True)
    get_mode = function(kernel, 'GetConsoleMode', c.c_int, c.c_void_p, c.POINTER(DWORD))
    set_mode = function(kernel, 'SetConsoleMode', c.c_int, c.c_void_p, DWORD)
    handle = msvcrt.get_osfhandle(sys.stdout.fileno())
    mode = DWORD()
    if not get_mode(handle, c.byref(mode)):
        raise RuntimeError('無法取得終端機模式，請在 Windows PowerShell 執行 --diagnose')
    if not set_mode(handle, mode.value | 0x0004):  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        raise RuntimeError('終端機不支援 VT 畫面更新')
    try:
        sys.stdout.write('\x1b[?1049h\x1b[?25l')
        sys.stdout.flush()
        yield
    finally:
        try:
            sys.stdout.write('\x1b[?25h\x1b[?1049l')
            sys.stdout.flush()
        finally:
            set_mode(handle, mode.value)


def poll(joystick, index, caps, controller, tick, diagnose=False):
    previous_axes = previous_buttons = None
    last_tick = time.monotonic()
    while True:
        state = joystick.read(index)
        values = axes(state, caps)
        if diagnose:
            snapshot = (values, state.buttons)
            if snapshot != (previous_axes, previous_buttons):
                lines = [f'{caps.name}（索引 {index}）',
                         '操作搖桿以查看數值；按 Ctrl+C 結束。', '']
                lines.extend(f'軸 {i}: {value:+6d}' for i, value in enumerate(values))
                lines.append('')
                # 每列最多 8 個按鈕，避免一般終端機寬度下換行。
                for start in range(0, min(caps.buttons, 32), 8):
                    lines.append('按鈕: ' + '  '.join(
                        f'{i + 1}:{"●" if state.buttons & (1 << i) else "○"}'
                        for i in range(start, min(start + 8, caps.buttons, 32))))
                lines.append(f'方向帽 POV: {state.pov}')
                sys.stdout.write('\x1b[H\x1b[J' + '\n'.join(lines))
                sys.stdout.flush()
        else:
            for number, value in enumerate(values):
                if previous_axes is None or value != previous_axes[number]:
                    controller.handle_axis(number, value, initial=previous_axes is None)
            # 啟動時已按住的按鈕必須先放開，避免初始化觸發桌面操作。
            if previous_buttons is not None:
                changed = previous_buttons ^ state.buttons
                for number in range(min(caps.buttons, 32)):
                    if changed & (1 << number):
                        controller.handle_button(number, bool(state.buttons & (1 << number)))
            now = time.monotonic()
            controller.tick(now, now - last_tick)
            last_tick = now
        previous_axes, previous_buttons = values, state.buttons
        time.sleep(tick)


def run_windows(args, controller_class, tick):
    joystick = WindowsJoystick()
    if args.list:
        devices = joystick.devices()
        for index, caps in devices:
            print(f'{index}：{caps.name}；{caps.axes} 軸、{caps.buttons} 按鈕、'
                  f'POV：{"有" if caps.caps & 0x10 else "無"}')
        if not devices:
            print('找不到搖桿，請確認 USB／藍牙連線與 Windows 驅動程式。')
        return 0
    kernel = c.WinDLL('kernel32', use_last_error=True)
    create = function(kernel, 'CreateMutexW', c.c_void_p, c.c_void_p, c.c_int, c.c_wchar_p)
    close = function(kernel, 'CloseHandle', c.c_int, c.c_void_p)
    handle = create(None, False, 'Local\\MousePad-Windows-Controller')
    if not handle:
        raise OSError('無法建立 MousePad 執行個體鎖')
    try:
        if c.get_last_error() == 183:
            raise RuntimeError('已有 MousePad 執行個體，請先停止再啟動')
        waiting = False
        while True:
            devices = joystick.devices()
            selected = next(((i, caps) for i, caps in devices
                             if args.device is None or i == int(args.device)), None)
            if selected is None:
                if not args.wait:
                    raise RuntimeError('找不到指定或可讀取的 Windows 搖桿')
                if not waiting:
                    print('等待搖桿連線……', flush=True)
                    waiting = True
                time.sleep(1)
                continue
            waiting = False
            index, caps = selected
            output = None
            try:
                joystick.read(index)
                if not args.diagnose:
                    output = WindowsOutput()
                controller = controller_class(str(index), output, args.speed, args.deadzone)
                if not args.diagnose:
                    print(f'MousePad 已啟動：{caps.name} ({index})', flush=True)
                    print('Ctrl+C 結束。', flush=True)
                with diagnostic_screen() if args.diagnose else nullcontext():
                    poll(joystick, index, caps, controller, tick, args.diagnose)
            except OSError as error:
                if not args.wait or error.errno != errno.ENODEV:
                    raise
                print('搖桿已中斷連線，將重新偵測。', flush=True)
            finally:
                if output is not None:
                    output.close()
            time.sleep(1)
    finally:
        close(handle)
