# Repository Guidelines

## 回覆語言規範

所有回覆（包含進度說明、問題詢問與最終結果）一律使用臺灣通用的繁體中文，採用臺灣常見的用語與語意表達，不使用中國簡體字或中國大陸慣用的普通話措辭。程式碼、指令、檔案路徑及專有名稱保留原文。

## Project Structure & Module Organization

- `mousepad.py` contains the CLI, Linux joystick event reader, `MousePadController`, and background cursor movement loop. On Linux it reads `/dev/input/js*` and emits events through `/dev/uinput`.
- `macos_hid.py` reads joystick axes, buttons, and hats through macOS IOKit. `macos_backend.py` emits CoreGraphics mouse and keyboard events. Keep the controller mapping shared with Linux.
- `mousepad.service` defines the system-level systemd service, running as a regular user. `70-mousepad.rules` and `mousepad.modules.conf` configure device access and module loading.
- `README.md` documents dependencies, controller mappings, and usage in Traditional Chinese.
- `drone-site/dist/` contains the authored static drone simulator; `drone-site/README.md` documents Google Maps setup, controls, OSD, and deployment.

`tests/test_mousepad.py` contains mocked `unittest` checks. The Python utility has no separate source or asset directories. Keep related controller logic together and update the documented mappings when behavior changes.

## Build, Test, and Development Commands

Run commands from the repository root. Linux interactive use requires Python 3, an X11 or Wayland desktop, a readable joystick device, and write access to `/dev/uinput`. macOS interactive use requires a logged-in desktop, a joystick, and Accessibility permission.

- `sudo apt install python3`: install runtime dependencies on Debian/Ubuntu.
- `python3 mousepad.py --help`: inspect available CLI options.
- `python3 mousepad.py --list`: discover joystick devices.
- `python3 mousepad.py -d /dev/input/js0 -s 18 -z 7000`: run with an explicit device, cursor speed, and deadzone.
- `python3 -m py_compile mousepad.py`: check Python syntax; no build step is required.
- `python3 -m unittest discover -s tests -v`: run mocked controller and cleanup tests.
- `python3 mousepad.py --list`: list macOS joystick indices through IOKit HID.
- `systemctl status mousepad`: inspect an installed service.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for functions and variables, `PascalCase` for classes, and uppercase names for constants. Follow the existing Python standard-library approach and pass subprocess arguments as lists. Keep joystick axis/button comments accurate: event indices are zero-based, while controller labels are often one-based. No formatter or linter is configured.

## Testing Guidelines

Tests use standard-library `unittest`; no coverage threshold is configured. For behavior changes, stop any running MousePad service before manual testing to avoid duplicate input. Verify cursor movement, deadzone behavior, scrolling, D-pad transitions, mouse press/release, keyboard mappings, and Ctrl+C shutdown on an X11 or Wayland desktop. Record the controller model and device path tested. If adding automated tests, use `tests/test_*.py` and mock output devices so tests do not generate desktop input.

## Commit & Pull Request Guidelines

Use concise imperative subjects, such as `Fix repeated D-pad key events`. Describe the change, link relevant issues, and report validation commands and hardware results. Update `README.md` for mapping or CLI changes.

## Service Configuration

Before installing the system service, adapt `User`, `Group`, and `ExecStart` to the target machine. Install the udev and module settings documented in README. The service uses `--wait` to reconnect devices. After changing an installed unit, run `sudo systemctl daemon-reload` and `sudo systemctl restart mousepad`.

## GitHub & Deployment

The main repository is `StrongerShen/MousePad`. Commit the authored files in `drone-site/dist/`; exclude credentials, `.env`, `.openai`, `.sites-runtime`, and Git metadata. The simulator currently runs on Sites; deployment to `https://mit.com.tw/drone-emu/` is planned and uses relative asset paths.
