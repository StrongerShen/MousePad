"""以 macOS IOKit 讀取 USB／藍牙 HID 搖桿，無需 Python 套件。"""

import ctypes
import ctypes.util
import errno


def _function(library, name, result, *arguments):
    function = getattr(library, name)
    function.restype = result
    function.argtypes = list(arguments)
    return function


class HIDJoystick:
    def __init__(self):
        io = ctypes.CDLL(ctypes.util.find_library('IOKit'))
        cf = ctypes.CDLL(ctypes.util.find_library('CoreFoundation'))
        ptr, integer = ctypes.c_void_p, ctypes.c_uint32
        self.create = _function(io, 'IOHIDManagerCreate', ptr, ptr, integer)
        self.match = _function(io, 'IOHIDManagerSetDeviceMatching', None, ptr, ptr)
        self.copy_devices = _function(io, 'IOHIDManagerCopyDevices', ptr, ptr)
        self.device_property = _function(io, 'IOHIDDeviceGetProperty', ptr, ptr, ptr)
        self.device_open = _function(io, 'IOHIDDeviceOpen', ctypes.c_int32, ptr, integer)
        self.device_close = _function(io, 'IOHIDDeviceClose', ctypes.c_int32, ptr, integer)
        self.copy_elements = _function(io, 'IOHIDDeviceCopyMatchingElements', ptr,
                                       ptr, ptr, integer)
        self.get_value = _function(io, 'IOHIDDeviceGetValue', ctypes.c_int32,
                                   ptr, ptr, ctypes.POINTER(ptr))
        self.value_integer = _function(io, 'IOHIDValueGetIntegerValue', ctypes.c_long, ptr)
        self.element_type = _function(io, 'IOHIDElementGetType', integer, ptr)
        self.element_page = _function(io, 'IOHIDElementGetUsagePage', integer, ptr)
        self.element_usage = _function(io, 'IOHIDElementGetUsage', integer, ptr)
        self.element_min = _function(io, 'IOHIDElementGetLogicalMin', ctypes.c_int, ptr)
        self.element_max = _function(io, 'IOHIDElementGetLogicalMax', ctypes.c_int, ptr)
        self.set_count = _function(cf, 'CFSetGetCount', ctypes.c_long, ptr)
        self.set_values = _function(cf, 'CFSetGetValues', None, ptr,
                                    ctypes.POINTER(ptr))
        self.array_count = _function(cf, 'CFArrayGetCount', ctypes.c_long, ptr)
        self.array_item = _function(cf, 'CFArrayGetValueAtIndex', ptr, ptr, ctypes.c_long)
        self.cf_string = _function(cf, 'CFStringCreateWithCString', ptr, ptr,
                                   ctypes.c_char_p, integer)
        self.string_bytes = _function(cf, 'CFStringGetCString', ctypes.c_bool,
                                      ptr, ctypes.c_char_p, ctypes.c_long, integer)
        self.number_value = _function(cf, 'CFNumberGetValue', ctypes.c_bool,
                                      ptr, ctypes.c_int, ptr)
        self.retain = _function(cf, 'CFRetain', ptr, ptr)
        self.release = _function(cf, 'CFRelease', None, ptr)
        self.manager = self.create(None, 0)
        if not self.manager:
            raise RuntimeError('IOKit 無法建立 HID 管理員')
        self.match(self.manager, None)
        self.active = None
        self.elements = None
        self.keys = {}
        for text in ('Product', 'PrimaryUsagePage', 'PrimaryUsage'):
            self.keys[text] = self.cf_string(None, text.encode(), 0x08000100)

    def _property_number(self, device, key):
        value = self.device_property(device, self.keys[key])
        result = ctypes.c_int()
        if not value or not self.number_value(value, 3, ctypes.byref(result)):
            return None
        return result.value

    def _name(self, device):
        value = self.device_property(device, self.keys['Product'])
        result = ctypes.create_string_buffer(256)
        if value and self.string_bytes(value, result, len(result), 0x08000100):
            return result.value.decode(errors='replace')
        return '未知搖桿'

    def devices(self):
        device_set = self.copy_devices(self.manager)
        if not device_set:
            return []
        try:
            count = self.set_count(device_set)
            pointers = (ctypes.c_void_p * count)()
            self.set_values(device_set, pointers)
            found = []
            for device in pointers:
                # Generic Desktop: joystick (4) or gamepad (5).
                if (self._property_number(device, 'PrimaryUsagePage') == 1 and
                        self._property_number(device, 'PrimaryUsage') in (4, 5)):
                    found.append((self._name(device), self.retain(device)))
            found.sort(key=lambda item: item[0])
            return [(index, device, name) for index, (name, device)
                    in enumerate(found)]
        finally:
            self.release(device_set)

    def release_devices(self, devices):
        for _index, device, _name in devices:
            self.release(device)

    def open(self, device):
        status = self.device_open(device, 0)
        if status:
            if status & 0xffffffff == 0xe00002e2:
                raise RuntimeError('無法讀取搖桿；請在「系統設定 → 隱私權與安全性 → 輸入監控」允許執行程式的終端機')
            raise OSError(f'IOKit 無法開啟搖桿：0x{status & 0xffffffff:08x}')
        elements = None
        try:
            elements = self.copy_elements(device, None, 0)
            if not elements:
                raise OSError('IOKit 無法讀取搖桿欄位')
            axes, buttons, hats = {}, {}, []
            for index in range(self.array_count(elements)):
                element = self.array_item(elements, index)
                kind = self.element_type(element)
                page = self.element_page(element)
                usage = self.element_usage(element)
                if kind == 1 and page == 1 and usage in (48, 49, 50, 53):
                    axes[{48: 0, 49: 1, 50: 2, 53: 3}[usage]] = (
                        element, self.element_min(element), self.element_max(element))
                elif kind == 1 and page == 1 and usage == 57:
                    hats.append(element)
                elif kind == 2 and page == 9 and 1 <= usage <= 64:
                    buttons[usage - 1] = element
            if not axes or not buttons:
                raise OSError('搖桿沒有可用的軸或按鈕')
            self.active = device
            self.elements = elements
            self.axis_elements = axes
            self.button_elements = buttons
            self.hat_elements = hats
            return device
        except BaseException:
            if elements:
                self.release(elements)
            self.device_close(device, 0)
            raise

    def close(self, device):
        try:
            self.device_close(device, 0)
        finally:
            self.release(self.elements)
            self.elements = None
            self.active = None

    def connected(self, device):
        return device == self.active

    def update(self):
        pass

    def _read(self, element):
        value = ctypes.c_void_p()
        status = self.get_value(self.active, element, ctypes.byref(value))
        if status or not value.value:
            raise OSError(errno.ENODEV, '搖桿已中斷連線')
        return self.value_integer(value)

    def axes(self, device):
        return max(self.axis_elements, default=-1) + 1

    def axis(self, device, index):
        element = self.axis_elements.get(index)
        if not element:
            return 0
        pointer, low, high = element
        if high <= low:
            return 0
        raw = self._read(pointer)
        return max(-32768, min(32767,
                               round((raw - low) * 65535 / (high - low) - 32768)))

    def buttons(self, device):
        return max(self.button_elements, default=-1) + 1

    def button(self, device, index):
        element = self.button_elements.get(index)
        return bool(self._read(element)) if element else False

    def hats(self, device):
        return len(self.hat_elements)

    def hat(self, device, index):
        value = self._read(self.hat_elements[index])
        # HID hat: 0 上、順時針至 7 左上；8（或超出範圍）為中心。
        return (1, 3, 2, 6, 4, 12, 8, 9)[value] if 0 <= value < 8 else 0

    def quit(self):
        for key in self.keys.values():
            self.release(key)
        self.release(self.manager)
