#!/usr/bin/env python3
"""將 Linux 搖桿輸入轉換成 uinput 滑鼠與鍵盤事件。"""

import argparse
import errno
import fcntl
import glob
import math
import os
import select
import signal
import socket
import struct
import sys
import time

EVENT_FORMAT = '=IhBB'
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
JS_EVENT_BUTTON = 0x01
JS_EVENT_AXIS = 0x02
JS_EVENT_INIT = 0x80
TICK = 0.015
SCROLL_INTERVAL = 0.12
KEYS = {0: 14, 4: 15, 5: 57, 6: 1, 7: 28, 8: 102,
        9: 107, 10: 104, 11: 109}
BUTTONS = {1: 272, 2: 273, 3: 274}


class UInputOutput:
    """持續開啟一個虛擬滑鼠／鍵盤；離開時釋放按鍵。"""

    def __init__(self, path='/dev/uinput'):
        self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        self.held = set()
        self.created = False
        try:
            # linux/uinput.h: UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT
            for kind in (1, 2):
                fcntl.ioctl(self.fd, 0x40045564, kind)
            # 宣告基本鍵盤按鍵，讓 udev／libinput 辨識為鍵盤及滑鼠。
            for code in set(range(1, 32)) | set(KEYS.values()) | set(BUTTONS.values()):
                fcntl.ioctl(self.fd, 0x40045565, code)
            for code in (0, 1, 8):
                fcntl.ioctl(self.fd, 0x40045566, code)
            # UI_DEV_SETUP: input_id followed by name and ff_effects_max.
            setup = struct.pack('=HHHH80sI', 3, 0x1234, 0x5678, 1,
                                b'MousePad virtual mouse and keyboard', 0)
            fcntl.ioctl(self.fd, 0x405c5503, setup)
            fcntl.ioctl(self.fd, 0x5501)  # UI_DEV_CREATE
            self.created = True
        except BaseException:
            os.close(self.fd)
            self.fd = None
            raise

    def emit(self, kind, code, value):
        packet = struct.pack('@llHHi', 0, 0, kind, code, value)
        if os.write(self.fd, packet) != len(packet):
            raise OSError('虛擬輸入事件寫入不完整')

    def sync(self):
        self.emit(0, 0, 0)

    def move(self, x, y):
        if x or y:
            self.emit(2, 0, x)
            self.emit(2, 1, y)
            self.sync()

    def scroll(self, amount):
        self.emit(2, 8, amount)
        self.sync()

    def button(self, code, down):
        if down == (code in self.held):
            return
        if down:
            self.held.add(code)
        self.emit(1, code, int(down))
        self.sync()
        if not down:
            self.held.discard(code)

    def key(self, code):
        self.button(code, True)
        self.button(code, False)

    def close(self):
        if self.fd is None:
            return
        try:
            if self.created:
                try:
                    for code in tuple(self.held):
                        self.button(code, False)
                finally:
                    fcntl.ioctl(self.fd, 0x5502)  # UI_DEV_DESTROY
        finally:
            os.close(self.fd)
            self.fd = None


def device_name(path):
    try:
        with open(f'/sys/class/input/{os.path.basename(os.path.realpath(path))}/device/name') as file:
            return file.read().strip()
    except OSError:
        return '未知搖桿'


class MousePadController:
    def __init__(self, device_path, output, speed=18.0, deadzone=7000):
        self.device_path = device_path
        self.output = output
        self.max_speed = speed
        self.deadzone = deadzone
        self.dx = self.dy = self.scroll_dy = 0
        self.remainder_x = self.remainder_y = 0.0
        self.hat_states = {4: 0, 5: 0}
        self.next_scroll = 0.0

    def velocity(self, value):
        value = max(-32767, min(32767, value))
        if abs(value) <= self.deadzone:
            return 0.0
        magnitude = (abs(value) - self.deadzone) / (32767 - self.deadzone)
        return math.copysign(magnitude * self.max_speed, value)

    def tick(self, now, elapsed):
        # 保留小數位移，並依經過時間計算速度，捲動不會阻塞游標。
        factor = min(elapsed, 0.1) / TICK
        vx, vy = self.velocity(self.dx), self.velocity(self.dy)
        self.remainder_x = self.remainder_x + vx * factor if vx else 0.0
        self.remainder_y = self.remainder_y + vy * factor if vy else 0.0
        x, y = int(self.remainder_x), int(self.remainder_y)
        self.remainder_x -= x
        self.remainder_y -= y
        self.output.move(x, y)
        if abs(self.scroll_dy) > 10000:
            if now >= self.next_scroll:
                self.output.scroll(-1 if self.scroll_dy > 0 else 1)
                self.next_scroll = now + SCROLL_INTERVAL
        else:
            self.next_scroll = now

    def handle_axis(self, number, value, initial=False):
        if number == 0:
            self.dx = value
        elif number == 1:
            self.dy = value
        elif number == 3:
            self.scroll_dy = value
        elif number in self.hat_states:
            state = -1 if value < -16000 else 1 if value > 16000 else 0
            if not initial and state and state != self.hat_states[number]:
                codes = (102, 107) if number == 4 else (104, 109)
                self.output.key(codes[0 if state < 0 else 1])
            self.hat_states[number] = state

    def handle_button(self, number, value):
        if number in BUTTONS:
            self.output.button(BUTTONS[number], bool(value))
        elif value and number in KEYS:
            self.output.key(KEYS[number])

    def run(self):
        fd = os.open(self.device_path, os.O_RDONLY | os.O_NONBLOCK)
        try:
            print(f'MousePad 已啟動：{device_name(self.device_path)} ({self.device_path})',
                  flush=True)
            print('左搖桿：游標；右搖桿：捲動；按鈕 2／3／4：左／右／中鍵。', flush=True)
            last_tick = time.monotonic()
            while True:
                now = time.monotonic()
                ready, _, _ = select.select([fd], [], [], max(0, TICK - (now - last_tick)))
                if ready:
                    try:
                        data = os.read(fd, EVENT_SIZE * 64)
                    except BlockingIOError:
                        continue
                    if not data:
                        raise OSError(errno.ENODEV, '搖桿已中斷連線')
                    if len(data) % EVENT_SIZE:
                        raise OSError('搖桿事件資料不完整')
                    for _, value, kind, number in struct.iter_unpack(EVENT_FORMAT, data):
                        initial = bool(kind & JS_EVENT_INIT)
                        kind &= ~JS_EVENT_INIT
                        if kind == JS_EVENT_AXIS:
                            self.handle_axis(number, value, initial)
                        elif kind == JS_EVENT_BUTTON and not initial:
                            self.handle_button(number, value)
                now = time.monotonic()
                if now - last_tick >= TICK:
                    self.tick(now, now - last_tick)
                    last_tick = now
        finally:
            os.close(fd)


def select_device(requested=None):
    """只在等待裝置時挑選；已連線的搖桿不會被新裝置取代。"""
    if requested:
        return requested if os.path.exists(requested) else None
    for path in sorted(glob.glob('/dev/input/js*')):
        if os.access(path, os.R_OK):
            return path
    return None


def run_connected(device, speed, deadzone):
    # 建立虛擬裝置前先確認搖桿可讀，避免無裝置時反覆建立輸出。
    joystick = os.open(device, os.O_RDONLY | os.O_NONBLOCK)
    os.close(joystick)
    output = UInputOutput()
    try:
        time.sleep(0.5)
        MousePadController(device, output, speed, deadzone).run()
    finally:
        output.close()


def run_devices(args):
    waiting = False
    while True:
        device = select_device(args.device)
        if device is None:
            if not args.wait:
                raise RuntimeError('找不到可讀取的搖桿，請檢查連線與權限')
            if not waiting:
                print('等待搖桿連線……', flush=True)
                waiting = True
            time.sleep(1)
            continue
        waiting = False
        try:
            run_connected(device, args.speed, args.deadzone)
            return
        except OSError as error:
            if not args.wait or error.errno not in (
                    errno.ENODEV, errno.ENOENT, errno.ENXIO, errno.EIO):
                raise
            print(f'裝置暫時無法使用：{device}；將重新偵測。', flush=True)
            time.sleep(1)


def positive_speed(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError('速度必須是大於零的有限數值')
    return number


def valid_deadzone(value):
    number = int(value)
    if not 0 <= number < 32767:
        raise argparse.ArgumentTypeError('死區必須介於 0 與 32766')
    return number


def stop(signum, frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser(description='MousePad：Linux 搖桿滑鼠（X11／Wayland）')
    parser.add_argument('-d', '--device', help='搖桿路徑；預設選擇第一個 /dev/input/js*')
    parser.add_argument('-s', '--speed', type=positive_speed, default=18.0,
                        help='最大游標速度，每 15 毫秒的位移量（預設 18）')
    parser.add_argument('-z', '--deadzone', type=valid_deadzone, default=7000,
                        help='搖桿死區（預設 7000）')
    parser.add_argument('-l', '--list', action='store_true', help='列出搖桿')
    parser.add_argument('--wait', action='store_true', help='等待搖桿並在斷線後自動重新連線')
    args = parser.parse_args()
    if not sys.platform.startswith('linux'):
        parser.error('目前僅支援 Linux')
    devices = sorted(glob.glob('/dev/input/js*'))
    if args.list:
        for path in devices:
            print(f'{path}：{device_name(path)}')
        if not devices:
            print('找不到搖桿，請確認 USB 連線。')
        return 0
    # 抽象 UNIX socket 在程序結束時自動釋放，避免兩份 MousePad 重複輸出。
    lock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            lock.bind('\0mousepad-uinput-controller')
        except OSError as error:
            raise RuntimeError('已有 MousePad 執行個體，請先停止再啟動') from error
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        run_devices(args)
    except KeyboardInterrupt:
        print('\nMousePad 已停止。')
        return 0
    except PermissionError as error:
        print(f'權限不足：{error}。請參考 README 的裝置權限設定。', file=sys.stderr)
        return 1
    except (OSError, RuntimeError) as error:
        print(f'MousePad 錯誤：{error}', file=sys.stderr)
        return 1
    finally:
        lock.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
