from fastapi import FastAPI, HTTPException
from contextlib import asynccontextmanager

from .models import BookingRequest, BookingResponse, STATION_CODES
from .browser import tra_browser

@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    # 啟動時初始化瀏覽器
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
    
    **必填欄位：**
    - **pid**: 身分證字號 (10碼)
    - **start_station**: 起站名稱 (如：臺北、臺中)
    - **end_station**: 終站名稱
    - **ride_date**: 乘車日期 (YYYY-MM-DD)
    - **start_time**: 起始時間 (HH:MM)
    - **end_time**: 結束時間 (HH:MM)
    - **qty**: 訂票張數 (1-6張)
    
    **注意：** 訂票過程約需 10-15 秒
    """
    # 驗證車站
    if booking.start_station not in STATION_CODES:
        raise HTTPException(status_code=400, detail=f"找不到車站: {booking.start_station}")
    if booking.end_station not in STATION_CODES:
        raise HTTPException(status_code=400, detail=f"找不到車站: {booking.end_station}")
    
    # 格式化日期
    ride_date_str = booking.ride_date.strftime("%Y/%m/%d")
    
    # 執行訂票
    result = await tra_browser.book_ticket(
        pid=booking.pid,
        start_station=booking.start_station,
        end_station=booking.end_station,
        ride_date=ride_date_str,
        start_time=booking.start_time,
        end_time=booking.end_time,
        qty=booking.qty
    )
    
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


@app.get("/stations", tags=["車站"])
def get_stations():
    """取得所有車站代碼"""
    return STATION_CODES


@app.get("/health", tags=["健康檢查"])
def health_check():
    """健康檢查"""
    return {"status": "ok", "browser": "playwright"}
