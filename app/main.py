import asyncio
from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from .models import BookingRequest, BookingResponse, STATION_CODES, OrderType
from .browser import tra_browser

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時初始化瀏覽器 (使用無頭模式背景執行)
    await tra_browser.start(headless=True)
    yield
    # 關閉時清理瀏覽器
    await tra_browser.stop()


app = FastAPI(
    title="台鐵訂票系統",
    description="""
## 🚂 台灣鐵路訂票 API

使用 Playwright 瀏覽器自動化連接台鐵官方訂票系統。

### 使用方式
使用 `/booking` 端點提交訂票資料

### 注意事項
- 系統使用真實瀏覽器模擬訂票流程
- 首次訂票可能需要較長時間 (約 10-15 秒)
    """,
    version="2.0.0",
    lifespan=lifespan
)


@app.get("/", tags=["首頁"])
def root():
    """API 首頁"""
    return {
        "message": "歡迎使用台鐵訂票系統 (Playwright 版)",
        "docs": "/docs",
        "version": "2.0.0",
        "stations": list(STATION_CODES.keys())
    }


@app.post("/booking", response_model=BookingResponse, tags=["訂票"], summary="送出訂票")
async def create_booking(booking: BookingRequest):
    """
    送出訂票請求至台鐵官方系統 (使用瀏覽器自動化)
    
    **注意：** 系統會自動重試直到訂票成功為止，每次失敗間隔 10 秒。
    """
    # 驗證車站
    if booking.start_station not in STATION_CODES:
        raise HTTPException(status_code=400, detail=f"找不到車站: {booking.start_station}")
    if booking.end_station not in STATION_CODES:
        raise HTTPException(status_code=400, detail=f"找不到車站: {booking.end_station}")
    
    # 驗證依車次訂票必須有車次
    if booking.order_type == OrderType.BY_TRAIN and not booking.train_no:
        raise HTTPException(status_code=400, detail="依車次訂票時必須提供 train_no")
    
    # 格式化日期
    ride_date_str = booking.ride_date.strftime("%Y/%m/%d")
    
    # 無限重試循環
    retry_count = 0
    while True:
        retry_count += 1
        print(f"\n--- 開始第 {retry_count} 次訂票嘗試 ---")
        try:
            # 執行訂票
            result = await tra_browser.book_ticket(
                pid=booking.pid,
                start_station=booking.start_station,
                end_station=booking.end_station,
                ride_date=ride_date_str,
                order_type=booking.order_type,
                train_no=booking.train_no,
                start_time=booking.start_time,
                end_time=booking.end_time,
                qty=booking.qty
            )
            
            if result["success"]:
                print(f"訂票成功！ (嘗試次數: {retry_count})")
                return BookingResponse(
                    success=result["success"],
                    message=result["message"],
                    booking_code=result.get("booking_code"),
                    train_no=result.get("train_no"),
                    train_type=result.get("train_type"),
                    seat_info=result.get("seat_info"),
                    price=result.get("price"),
                    html_response=None
                )
            
            # 失敗處理
            print(f"訂票失敗: {result['message']}")
            print("等待 10 秒後重試...")
            await asyncio.sleep(10)
            
        except Exception as e:
            print(f"發生未預期錯誤: {e}")
            print("等待 10 秒後重試...")
            await asyncio.sleep(10)


@app.get("/stations", tags=["車站"])
def get_stations():
    """取得所有車站代碼"""
    return STATION_CODES


@app.get("/health", tags=["健康檢查"])
def health_check():
    """健康檢查"""
    return {"status": "ok", "browser": "playwright"}
