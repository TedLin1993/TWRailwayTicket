from fastapi import FastAPI, HTTPException
from datetime import date
import random
import string

from .models import BookingRequest, BookingResponse, TrainType

app = FastAPI(
    title="台鐵訂票系統",
    description="""
## 🚂 台灣鐵路訂票 API

提供簡單的訂票功能，送出訂票請求即可完成訂票。

### 使用方式
使用 `/booking` 端點提交訂票資料
    """,
    version="1.0.0"
)


def generate_booking_code() -> str:
    """產生 8 碼訂票代碼"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))


@app.get("/", tags=["首頁"])
def root():
    """API 首頁"""
    return {
        "message": "歡迎使用台鐵訂票系統",
        "docs": "/docs",
        "version": "1.0.0"
    }


@app.post("/booking", response_model=BookingResponse, tags=["訂票"], summary="送出訂票")
def create_booking(booking: BookingRequest):
    """
    送出訂票請求
    
    **必填欄位：**
    - **from_station**: 起站名稱 (如：台北)
    - **to_station**: 終站名稱 (如：高雄)
    - **train_no**: 車次號碼 (如：110)
    - **travel_date**: 乘車日期 (YYYY-MM-DD)
    - **passenger_name**: 乘客姓名
    - **passenger_id**: 身分證字號 (10碼)
    - **phone**: 聯絡電話
    - **seat_count**: 訂票張數 (1-6張，預設1張)
    - **train_type**: 列車類型 (自強號/莒光號/區間車/普悠瑪/太魯閣)
    """
    # 驗證乘車日期
    if booking.travel_date < date.today():
        raise HTTPException(status_code=400, detail="乘車日期不可早於今日")
    
    # 模擬訂票成功
    booking_code = generate_booking_code()
    
    return BookingResponse(
        success=True,
        message="訂票成功",
        booking_code=booking_code,
        booking_details={
            "乘客姓名": booking.passenger_name,
            "起站": booking.from_station,
            "終站": booking.to_station,
            "車次": booking.train_no,
            "車種": booking.train_type.value,
            "乘車日期": str(booking.travel_date),
            "張數": booking.seat_count,
            "聯絡電話": booking.phone
        }
    )


@app.get("/health", tags=["健康檢查"])
def health_check():
    """健康檢查"""
    return {"status": "ok"}
