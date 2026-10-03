# MousePad 🎮 ➔ 🖱️

MousePad 將 Linux USB 搖桿轉換成桌面滑鼠與鍵盤操作，支援 X11 與 Wayland。使用 Linux `uinput` 建立虛擬輸入裝置，不需要 `xdotool`，也不依賴 `DISPLAY`。

## 安裝需求與權限

需要 Python 3、Linux `uinput`、可讀取的 `/dev/input/js*`，以及可寫入的 `/dev/uinput`。Python 程式只使用標準函式庫。

```bash
sudo apt install python3
sudo modprobe uinput
```

需要跨開機載入時，可將 `uinput` 寫入 `/etc/modules-load.d/mousepad.conf`。

正式使用建立專用群組並安裝持續生效的裝置權限規則：

```bash
sudo groupadd -f mousepad
sudo usermod -aG mousepad "$USER"
sudo install -m 0644 70-mousepad.rules /etc/udev/rules.d/70-mousepad.rules
sudo install -m 0644 mousepad.modules.conf /etc/modules-load.d/mousepad.conf
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=misc --sysname-match=uinput
sudo udevadm trigger --subsystem-match=input --sysname-match='js*'
```

手動執行需登出再登入，才能取得新群組；下方系統服務透過 `SupplementaryGroups` 直接取得所需群組，不必等重新登入。`mousepad` 群組可以送出桌面輸入，`input` 群組可以讀取輸入裝置；僅授權需要此功能的帳號，不要將 `/dev/uinput` 設成所有人可寫。

## 執行與參數

在專案根目錄執行：

```bash
python3 mousepad.py --list
python3 mousepad.py
python3 mousepad.py --wait
python3 mousepad.py -d /dev/input/js0 -s 18 -z 7000
```

未指定裝置時，選擇排序後的第一個 `/dev/input/js*`；多個搖桿請使用 `--device`。裝置編號可能隨插拔變動，也可指定 `/dev/input/by-id/` 下指向 joystick 的固定路徑。

- `--speed`：最大速度，以每 15 毫秒的游標位移量表示；預設 `18`，必須是大於零的有限數值。
- `--deadzone`：忽略中央漂移的範圍；預設 `7000`，有效範圍 `0–32766`。
- `--wait`：沒有搖桿時等待；拔除後清理輸出，再偵測可用的搖桿。
- `Ctrl+C` 或 `SIGTERM`：停止並釋放已按下的滑鼠鍵。

背景服務啟用 `--wait`，開機未接搖桿時仍持續等待，插上後自動連線。一次只使用一支搖桿；接上另一支不會取代目前的搖桿。拔除目前裝置時，釋放按鍵並挑選下一個可讀取的裝置；重接也會自動偵測。使用 `--device` 固定裝置後，只等待該路徑，不會改用其他搖桿。未使用 `--wait` 的手動執行在斷線後結束。程式會防止同時啟動兩份新版 MousePad。

游標保留小數位移，方便微幅操作；捲動有獨立的計時，不會降低游標更新頻率。按鍵與軸對應目前仍固定為 Logitech Dual Action／RumblePad 2 類型，其他控制器需要確認對應。

## 🎮 預設鍵位對應表 (Logitech Dual Action)

| 手把部位 | 控制動作 | 對應功能 |
| :--- | :--- | :--- |
| **左類比搖桿** | 上/下/左/右 | 🖱️ 滑鼠游標移動 (Cursor Movement) |
| **右類比搖桿** | 上/下 | 📜 頁面上下滾動 (Scroll Wheel) |
| **按鈕 2 (A 鍵)** | 單擊 / 長按 | 🖱️ 滑鼠左鍵 (Left Click) |
| **按鈕 3 (B 鍵)** | 單擊 / 長按 | 🖱️ 滑鼠右鍵 (Right Click) |
| **按鈕 1 (X 鍵)** | 按下 | ⌫ **`Backspace` (退格刪除鍵)** |
| **按鈕 4 (Y 鍵)** | 單擊 / 長按 | 🖱️ 滑鼠中鍵 (Middle Click) |
| **L1 鍵 (左上肩鍵)** | 按下 | ⇥ **`Tab` 鍵** |
| **R1 鍵 (右上肩鍵)** | 按下 | ␣ **`Space` (空白鍵)** |
| **L2 鍵 (左下扳機)** | 按下 | ⎋ **`Esc` (退出鍵)** |
| **R2 鍵 (右下扳機)** | 按下 | ↵ **`Enter` (確認 / 換行鍵)** |
| **Select 鍵** | 按下 | ↖ **`Home` 鍵** |
| **Start 鍵** | 按下 | ↘ **`End` 鍵** |
| **L3 (左搖桿下壓)** | 按下 / 十字鍵【上】 | ⇞ **`Page Up` (上一頁)** |
| **R3 (右搖桿下壓)** | 按下 / 十字鍵【下】 | ⇟ **`Page Down` (下一頁)** |
| **十字鍵 (D-Pad)** | 左 / 右 | ↖ **`Home`** / ↘ **`End`** |

---

## 開機背景服務

使用系統層級的 systemd 服務，在開機時啟動，不必先登入桌面。程式以一般帳號執行，服務設定的預設帳號是 `stronger`。虛擬裝置可供之後啟動的登入畫面與桌面辨識；登入畫面的實際操作仍需實機確認。

安裝前，編輯 `mousepad.service` 的 `User`、`Group` 與 `ExecStart`，讓帳號及專案路徑符合機器。先安裝上方的 udev 與模組設定；停止既有手動程序或舊的使用者服務，再安裝系統服務：

```bash
sudo install -m 0644 mousepad.service /etc/systemd/system/mousepad.service
sudo systemctl daemon-reload
sudo systemctl enable --now mousepad
systemctl status mousepad
journalctl -u mousepad -n 50
```

管理服務使用系統層級指令（不加 `--user`）：

```bash
sudo systemctl stop mousepad
sudo systemctl restart mousepad
sudo systemctl disable --now mousepad
```

固定特定搖桿時，在 `ExecStart` 的 `--wait` 後加上 `-d /dev/input/by-id/...-joystick`，再執行 `daemon-reload` 與 `restart`。開機時未接裝置會繼續等待。

## 更換搖桿與相容性

只要提供 Linux `/dev/input/js*` 介面，就能被偵測。自動偵測不代表按鍵對應一致：目前固定採用 Logitech Dual Action／RumblePad 2 的配置；其他品牌、Xbox／PlayStation 類控制器可能需要調整軸與按鍵對應，請先確認游標、捲動與按鍵功能。列出裝置使用 `python3 mousepad.py --list`。

## 開發與測試

```bash
python3 -m py_compile mousepad.py
python3 -m unittest discover -s tests -v
```

測試使用 `unittest` 與模擬輸出，不會產生桌面輸入。涵蓋小數位移、游標與捲動計時、十字鍵狀態、按鍵對應、參數檢查、裝置斷線、重新偵測、裝置選擇及清理流程。

實機測試前停止既有服務，確認游標、捲動、點擊、拖曳、快捷鍵、拔除與重新啟動。請記錄控制器型號、裝置路徑與桌面環境。macOS 與 Windows 尚未實作。

## 無人機模擬器

`drone-site/dist/` 是無人機 Web 模擬器的靜態原始碼，支援 3D 訓練場、Google 3D 地圖、街景、搖桿操作與配額／費用估算 OSD。

- 目前測試網址：[Drone 地景飛行模擬器](https://drone-flight-osd.strongershen.chatgpt.site)（私人網站）。
- 預計正式網址：`https://mit.com.tw/drone-emu/`（尚未部署）。
- 金鑰設定、操作與部署方式請參考 [無人機模擬器 README](drone-site/README.md)。

操作模擬器前先停止 MousePad，避免同時輸出滑鼠與飛行操作；結束後再啟動服務。API 金鑰與部署憑證不得提交至 GitHub。
