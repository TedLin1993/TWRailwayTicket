# TWRailwayTicket

以 FastAPI 提供台鐵與台灣高鐵訂票 API，透過 Playwright 操作官方訂票網站，並使用 `ddddocr` 辨識圖形驗證碼。

> [!WARNING]
> 本專案僅供個人研究與技術學習之用，不得用於任何未經授權之商業、營利或其他用途。

## 功能

- 台鐵依車次或時段訂票
- 台灣高鐵依車次或時段訂票
- 自動處理訂票流程與圖形驗證碼
- 訂票失敗後每 10 秒持續重試
- OpenAPI 文件與健康檢查端點
- 相容高鐵舊版 PascalCase 與新版 snake_case 請求欄位

## 環境需求

- Python 3.10 以上
- Playwright Chromium

## 安裝

```bash
git clone https://github.com/TedLin1993/TWRailwayTicket.git
cd TWRailwayTicket

python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
playwright install chromium
```

Linux 環境若缺少 Chromium 系統套件，可改用：

```bash
playwright install --with-deps chromium
```

## 啟動

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

啟動後可開啟：

- Swagger UI：<http://localhost:8000/docs>
- ReDoc：<http://localhost:8000/redoc>
- 健康檢查：<http://localhost:8000/health>

高鐵瀏覽器預設以 headless 模式執行。若要顯示瀏覽器視窗以便除錯：

```bash
THSR_HEADLESS=false uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## API

### 基本資訊

```bash
curl http://localhost:8000/
```

回應包含版本、台鐵車站名稱及高鐵車站編號。

### 台鐵車站

```bash
curl http://localhost:8000/stations
```

### 台鐵訂票

端點：`POST /booking`

依車次訂票：

```bash
curl -X POST http://localhost:8000/booking \
  -H 'Content-Type: application/json' \
  -d '{
    "pid": "A123456789",
    "start_station": "臺中",
    "end_station": "臺北",
    "ride_date": "2026-08-01",
    "order_type": "BY_TRAIN",
    "train_no": "122",
    "qty": 1
  }'
```

依時段訂票：

```bash
curl -X POST http://localhost:8000/booking \
  -H 'Content-Type: application/json' \
  -d '{
    "pid": "A123456789",
    "start_station": "臺中",
    "end_station": "臺北",
    "ride_date": "2026-08-01",
    "order_type": "BY_TIME",
    "start_time": "08:00",
    "end_time": "10:00",
    "qty": 1
  }'
```

`qty` 可設定為 1 至 6。`order_type` 為 `BY_TRAIN` 時必須提供 `train_no`。

### 高鐵訂票

端點：`POST /thsr/booking`

高鐵車站編號：

| 編號 | 車站 | 編號 | 車站 |
| ---: | --- | ---: | --- |
| 1 | 南港 | 7 | 台中 |
| 2 | 台北 | 8 | 彰化 |
| 3 | 板橋 | 9 | 雲林 |
| 4 | 桃園 | 10 | 嘉義 |
| 5 | 新竹 | 11 | 台南 |
| 6 | 苗栗 | 12 | 左營 |

依車次訂票：

```bash
curl -X POST http://localhost:8000/thsr/booking \
  -H 'Content-Type: application/json' \
  -d '{
    "Id": "A123456789",
    "Email": "user@example.com",
    "Phone": "0912345678",
    "StartStation": 2,
    "DestStation": 7,
    "Date": "2026/08/01",
    "TrainNo": "821",
    "HeadCount": 1
  }'
```

依時段訂票：

```bash
curl -X POST http://localhost:8000/thsr/booking \
  -H 'Content-Type: application/json' \
  -d '{
    "Id": "A123456789",
    "Phone": "0912345678",
    "StartStation": 2,
    "DestStation": 12,
    "Date": "2026/08/01",
    "Time": "700P",
    "HeadCount": 1
  }'
```

`TrainNo` 與 `Time` 至少需要提供一個。`Time` 使用高鐵網站的半小時時段代碼，例如 `900A`、`1200N`、`700P`；完整可用值可由 Swagger UI 的 schema 查看。請求也接受 `id`、`phone`、`start_station`、`dest_station`、`ride_date`、`departure_time`、`train_no`、`head_count` 等 snake_case 欄位。

若提供 `PassengerIds` 以使用早鳥票流程，其數量必須與 `HeadCount` 相同；未提供時使用原價全票流程。`HeadCount` 可設定為 1 至 10。

成功回應範例：

```json
{
  "success": true,
  "message": "高鐵訂位成功",
  "booking_code": "AB123456",
  "train_no": "821",
  "seat_info": "3車 12E",
  "price": 1490
}
```

## 測試

```bash
python -m unittest test_thsr.py
python test_ocr.py
```

`test_ocr.py` 只驗證 `ddddocr` 能否初始化；高鐵測試則涵蓋資料驗證、回應解析與 API 重試行為。

## 注意事項

- 台鐵與高鐵官方網站改版後，Playwright selector 或訂票流程可能需要同步調整。
- 訂票呼叫可能耗時較久；目前失敗時會每 10 秒持續重試，不設最大次數。呼叫端與反向代理的 timeout 應配合調整。
- OCR 無法保證每次辨識成功，短時間大量請求也可能觸發官方網站的限制。
- 本服務沒有內建驗證、授權、流量限制或資料加密，不應直接暴露在公開網路。
- 訂位成功不代表已付款或完成取票，請依官方流程在期限內完成後續作業。

## 免責聲明

本專案為非官方工具，與國營臺灣鐵路股份有限公司及台灣高速鐵路股份有限公司無關。使用者須自行承擔自動化訂票、個人資料處理與訂位結果相關責任。
