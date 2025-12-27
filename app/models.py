"""
台鐵訂票系統 - 資料模型
"""
from datetime import date, time
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class CustIdType(str, Enum):
    """證件類型"""
    PERSON_ID = "PERSON_ID"  # 身分證
    PASSPORT = "PASSPORT"    # 護照


class TripType(str, Enum):
    """行程類型"""
    ONEWAY = "ONEWAY"        # 單程
    ROUNDTRIP = "ROUNDTRIP"  # 來回


class OrderType(str, Enum):
    """訂票方式"""
    BY_TIME = "BY_TIME"      # 依時間
    BY_TRAIN = "BY_TRAIN"    # 依車次


class SeatPref(str, Enum):
    """座位偏好"""
    NONE = "NONE"            # 無偏好
    WINDOW = "WINDOW"        # 靠窗
    AISLE = "AISLE"          # 走道


class TrainType(str, Enum):
    """列車類型代碼"""
    TAROKO_PUYUMA = "11"     # 太魯閣/普悠瑪
    TZEQIANG = "1"           # 自強號
    JUGUANG = "2"            # 莒光號
    FUXING = "3"             # 復興號
    LOCAL_EXPRESS = "4"      # 區間快
    LOCAL = "5"              # 區間車


# 車站代碼對照表
STATION_CODES = {
    "基隆": "0900",
    "七堵": "0910",
    "松山": "0980",
    "臺北": "1000",
    "台北": "1000",
    "萬華": "1010",
    "板橋": "1020",
    "桃園": "1080",
    "中壢": "1120",
    "新竹": "1210",
    "苗栗": "1310",
    "豐原": "3200",
    "臺中": "3300",
    "台中": "3300",
    "彰化": "3360",
    "員林": "3390",
    "斗六": "3470",
    "嘉義": "4000",
    "新營": "4060",
    "臺南": "4220",
    "台南": "4220",
    "岡山": "4300",
    "高雄": "4400",
    "屏東": "5000",
    "潮州": "5050",
    "枋寮": "5110",
    "花蓮": "7000",
    "臺東": "6000",
    "台東": "6000",
}


class BookingRequest(BaseModel):
    """訂票請求"""
    pid: str = Field(..., min_length=10, max_length=10, description="身分證字號")
    start_station: str = Field(..., description="起站名稱，如：台北、臺中")
    end_station: str = Field(..., description="終站名稱，如：高雄")
    ride_date: date = Field(..., description="乘車日期")
    start_time: str = Field(default="00:00", description="起始時間 (HH:MM)")
    end_time: str = Field(default="23:59", description="結束時間 (HH:MM)")
    qty: int = Field(default=1, ge=1, le=6, description="訂票張數 (1-6)")
    
    cust_id_type: CustIdType = Field(default=CustIdType.PERSON_ID, description="證件類型")
    trip_type: TripType = Field(default=TripType.ONEWAY, description="行程類型")
    order_type: OrderType = Field(default=OrderType.BY_TIME, description="訂票方式")
    seat_pref: SeatPref = Field(default=SeatPref.NONE, description="座位偏好")
    train_types: List[TrainType] = Field(
        default=[TrainType.TAROKO_PUYUMA, TrainType.TZEQIANG, TrainType.JUGUANG, 
                 TrainType.FUXING, TrainType.LOCAL_EXPRESS, TrainType.LOCAL],
        description="列車類型 (可多選)"
    )

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "pid": "A123456789",
                    "start_station": "臺中",
                    "end_station": "臺北",
                    "ride_date": "2025-12-28",
                    "start_time": "12:30",
                    "end_time": "20:30",
                    "qty": 1
                }
            ]
        }
    }


class BookingResponse(BaseModel):
    """訂票結果"""
    success: bool
    message: str
    booking_code: Optional[str] = None
    train_no: Optional[str] = None
    train_type: Optional[str] = None
    seat_info: Optional[str] = None
    price: Optional[int] = None
    html_response: Optional[str] = None
