"""
台鐵訂票系統 - 資料模型
"""
from datetime import date, time
from enum import Enum
from pydantic import BaseModel, Field


class TrainType(str, Enum):
    """列車類型"""
    TZEQIANG = "自強號"
    JUGUANG = "莒光號"
    LOCAL = "區間車"
    PUYUEMA = "普悠瑪"
    TAROKO = "太魯閣"


class BookingRequest(BaseModel):
    """訂票請求"""
    from_station: str = Field(..., description="起站名稱，如：台北")
    to_station: str = Field(..., description="終站名稱，如：高雄")
    train_no: str = Field(..., description="車次號碼")
    travel_date: date = Field(..., description="乘車日期")
    passenger_name: str = Field(..., min_length=2, max_length=50, description="乘客姓名")
    passenger_id: str = Field(..., min_length=10, max_length=10, description="身分證字號")
    phone: str = Field(..., min_length=10, max_length=15, description="聯絡電話")
    seat_count: int = Field(default=1, ge=1, le=6, description="訂票張數 (1-6)")
    train_type: TrainType = Field(default=TrainType.TZEQIANG, description="列車類型")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "from_station": "台北",
                    "to_station": "高雄",
                    "train_no": "110",
                    "travel_date": "2025-01-15",
                    "passenger_name": "王小明",
                    "passenger_id": "A123456789",
                    "phone": "0912345678",
                    "seat_count": 2,
                    "train_type": "自強號"
                }
            ]
        }
    }


class BookingResponse(BaseModel):
    """訂票結果"""
    success: bool
    message: str
    booking_code: str | None = None
    booking_details: dict | None = None
