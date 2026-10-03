# Drone 地景飛行模擬器

靜態網頁，使用 Google Maps JavaScript API 的 3D 地圖與街景，以及瀏覽器 Gamepad API。沒有 API 金鑰也可以在 3D 訓練場飛行，使用透視投影的四旋翼模型、地面網格、陰影與旋翼動畫。可選空拍機、穿越機與迷你機；外觀不影響飛行性能。訓練場不是 Google 地景。

## 線上執行網址

[開啟無人機模擬器](https://drone-flight-osd.strongershen.chatgpt.site)

目前為私人測試網站，需要使用有權限的帳號登入。沒有 Google API 金鑰也能使用 3D 訓練場；Google 地景與街景需在頁面設定輸入金鑰。

預計正式部署網址：[https://mit.com.tw/drone-emu/](https://mit.com.tw/drone-emu/)（尚未部署）。

## GCP 設定

1. 建立專用 GCP 專案並連結帳單帳戶。
2. 啟用 **Maps JavaScript API**，建立網站用 API 金鑰。
3. 在金鑰的「應用程式限制」選擇網站，加入 `https://drone-flight-osd.strongershen.chatgpt.site/*`。本機測試可另外允許 `http://localhost:8767/*`；部署正式版時再加入 `https://mit.com.tw/drone-emu/*`。
4. 在「API 限制」只允許 Maps JavaScript API。
5. 開啟網頁的「連接 Google 地圖」，輸入金鑰與起始座標。金鑰僅放在頁面記憶體，不寫入檔案、瀏覽器儲存空間或本站伺服器。

網站金鑰在瀏覽器中可見，必須使用來源與 API 限制保護，不能當成伺服器端機密。網站若重新整理，需要重新輸入金鑰；更換金鑰也請重新整理。

## 費用 OSD

- 只估算本機瀏覽器記錄的地圖建立與街景物件建立次數，資料儲存在 localStorage；資料可能因清除儲存空間、私密模式或其他裝置而遺失。
- 地圖數量以建立 3D 地圖計算，載入失敗也可能記錄，並非 GCP 計費事件的精確讀值。
- 可以手動填入 GCP 本月總用量作為基準；更新後，本機後續次數會繼續累加。
- 免費額度以同一帳單帳戶各 SKU 的月用量計算，不是每個瀏覽器各有一份免費額度。
- 依 2026-10-03 全球隨用隨付價格估算 Immersive Maps 與 Dynamic Street View，不含其他 API、稅額、優惠、帳單匯率。月份以 UTC 切換。
- 一般預算提醒與本站門檻不會自動停止收費。請在 GCP 管理配額／支出控制，實際帳單以 GCP 為準。
- 未串接 Cloud Billing、Monitoring 或 BigQuery 帳單匯出。若需要帳戶級 OSD，後續需授權唯讀後端存取；請勿將服務帳戶私密金鑰放在網頁。

官方價格：https://developers.google.com/maps/billing-and-pricing/pricing
計費事件：https://developers.google.com/maps/billing-and-pricing/sku-details

## 操作

- 開啟後按「起飛」，約 3 秒升至 15 公尺；可用「重新開始」回到地面，或在 3D 訓練場與已連接的 Google 地景之間切換。
- 起飛自動升到模擬高度 15 公尺；降落原地下降。高度以起點為基準，Google 視角使用固定海拔基準，沒有地面碰撞、地形高度計算或真實飛行物理。
- WASD 移動，方向鍵升降／轉向，空白鍵起降，V 街景，P 暫停；亦提供按住式方向按鈕。
- 按飛行畫面內的「操作 OSD」查看鍵盤／搖桿說明並調整對應，可用關閉按鈕或 Esc 收起。開啟時暫停飛行，關閉後按 P 或「繼續」恢復。
- 搖桿預設使用 Logitech 軸與按鈕配置，可在操作 OSD 調整。一次使用一支；失焦、頁面隱藏或斷線時暫停。
- Linux 請先執行 `sudo systemctl stop mousepad`，避免同時發送滑鼠與飛行輸入；離開後用 `sudo systemctl start mousepad` 恢復。
- 街景只在開啟時查詢附近 300 公尺，不會跟著飛行逐幀更新。重用同一個全景物件，關閉僅隱藏視窗。

## 本機執行

```bash
python3 -m http.server 8767 --directory dist --bind 127.0.0.1
```

開啟 `http://localhost:8767`。Gamepad API 需要 HTTPS 或 localhost。頁面不會自動啟用 GCP API、建立帳單或讀取帳戶權限。

## 部署到 mit.com.tw/drone-emu/

目前仍使用上方的私人測試網址；正式站尚未部署。部署時將 `dist/` **內的檔案**放到網站的 `/drone-emu/` 目錄，讓 `index.html` 可由 `https://mit.com.tw/drone-emu/` 存取。JS、CSS 與模組引用使用相對路徑，支援此子目錄部署。

正式站需要 HTTPS 與 JavaScript 模組的正確 MIME 類型。Google Maps 金鑰的網站限制須允許 `https://mit.com.tw/drone-emu/*`。瀏覽器用量儲存空間依網站來源分開，從測試站切到正式站後，請重新確認 OSD 本月用量基準。

不要將 API 金鑰、服務帳戶憑證、`.env` 或 Sites 的 Git／部署憑證上傳至 GitHub 或網站目錄。此版本由使用者在頁面輸入網站用金鑰，不需要將金鑰寫進原始碼。
