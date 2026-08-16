import asyncio
import os
import secrets
import uuid

from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from starlette.responses import JSONResponse

from .browser_manager import browser_manager
from .jobs import job_manager, cancellable_sleep
from .models import (
    BookingRequest,
    BookingResponse,
    OrderType,
    STATION_CODES,
    THSRBookingRequest,
    THSRBookingResponse,
    THSR_STATIONS,
)
from .browser import tra_browser
from .thsr_browser import thsr_browser

API_KEY_ENV = "BOOKING_API_KEY"
PUBLIC_PATHS = {"/health"}


def _extract_api_key(request: Request) -> str | None:
    """從 Bearer token 或 X-API-Key Header 取得 API key。"""
    authorization = request.headers.get("Authorization", "")
    scheme, separator, token = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and token.strip():
        return token.strip()

    api_key = request.headers.get("X-API-Key")
    return api_key.strip() if api_key and api_key.strip() else None


def _api_key_matches(provided: str | None, expected: str) -> bool:
    """使用常數時間比較 API key。"""
    if not provided or not expected:
        return False
    return secrets.compare_digest(
        provided.encode("utf-8"),
        expected.encode("utf-8"),
    )


def _extract_job_id(request: Request) -> str:
    """從 Request Header 提取 X-Job-ID，或自動產生 12 碼 UUID。"""
    try:
        headers = getattr(request, "headers", None)
        if headers is not None and hasattr(headers, "get"):
            header_val = headers.get("X-Job-ID")
            if isinstance(header_val, str) and header_val.strip():
                return header_val.strip()
    except Exception:
        pass
    return uuid.uuid4().hex[:12]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式生命週期管理"""
    try:
        thsr_headless = os.getenv("THSR_HEADLESS", "true").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        await browser_manager.start(headless=thsr_headless)
        await tra_browser.start(headless=thsr_headless)
        await thsr_browser.start(headless=thsr_headless)
        yield
    finally:
        await browser_manager.stop()


app = FastAPI(
    title="台鐵與高鐵訂票系統",
    description="""
## 🚂 台灣鐵路與高鐵訂票 API

使用 Playwright 瀏覽器自動化連接台鐵與高鐵官方訂票系統。

### 使用方式
使用 `/booking` 提交台鐵訂票資料，或使用 `/thsr/booking` 提交高鐵訂票資料。

### 注意事項
- 系統使用真實瀏覽器模擬訂票流程
- 首次訂票可能需要較長時間 (約 10-15 秒)
    """,
    version="2.1.0",
    lifespan=lifespan
)


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    """除健康檢查外，所有 HTTP 端點都必須提供有效 API key。"""
    if request.url.path in PUBLIC_PATHS:
        return await call_next(request)

    expected = os.getenv(API_KEY_ENV, "").strip()
    if not expected:
        return JSONResponse(
            status_code=503,
            content={"detail": f"伺服器尚未設定 {API_KEY_ENV}"},
        )

    if not _api_key_matches(_extract_api_key(request), expected):
        return JSONResponse(
            status_code=401,
            content={"detail": "API key 無效或未提供"},
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


@app.get("/", tags=["首頁"])
def root():
    """API 首頁"""
    return {
        "message": "歡迎使用台鐵與高鐵訂票系統 (Playwright 版)",
        "docs": "/docs",
        "version": "2.1.0",
        "tra_stations": list(STATION_CODES.keys()),
        "thsr_stations": THSR_STATIONS,
    }


@app.post("/booking", response_model=BookingResponse, tags=["訂票"], summary="送出訂票")
async def create_booking(booking: BookingRequest, request: Request):
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
    
    job_id = _extract_job_id(request)
    cancel_event = await job_manager.register_job(job_id, service="tra")

    if await request.is_disconnected():
        await job_manager.update_job(job_id, status="cancelled", message="用戶端已中斷連線")
        raise HTTPException(status_code=499, detail="用戶端已中斷連線")

    # 格式化日期
    ride_date_str = booking.ride_date.strftime("%Y/%m/%d")
    
    async with job_manager.semaphore:
        if cancel_event.is_set() or await request.is_disconnected():
            await job_manager.update_job(job_id, status="cancelled", message="工作已取消或用戶端斷線")
            raise HTTPException(status_code=499, detail="訂票工作已取消或用戶端已中斷連線")

        retry_count = 0
        while not cancel_event.is_set():
            if await request.is_disconnected():
                cancel_event.set()
                break

            retry_count += 1
            print(f"\n--- [TRA Job {job_id}] 開始第 {retry_count} 次訂票嘗試 ---")
            await job_manager.update_job(
                job_id,
                status="running",
                retry_count=retry_count,
                message=f"執行第 {retry_count} 次訂票嘗試",
            )

            try:
                result = await tra_browser.book_ticket(
                    pid=booking.pid,
                    start_station=booking.start_station,
                    end_station=booking.end_station,
                    ride_date=ride_date_str,
                    order_type=booking.order_type,
                    train_no=booking.train_no,
                    start_time=booking.start_time,
                    end_time=booking.end_time,
                    qty=booking.qty,
                )

                if result["success"]:
                    print(f"[TRA Job {job_id}] 訂票成功！ (嘗試次數: {retry_count})")
                    await job_manager.update_job(
                        job_id,
                        status="completed",
                        retry_count=retry_count,
                        message=result["message"],
                        booking_code=result.get("booking_code"),
                    )
                    return BookingResponse(
                        success=True,
                        message=result["message"],
                        booking_code=result.get("booking_code"),
                        train_no=result.get("train_no"),
                        train_type=result.get("train_type"),
                        seat_info=result.get("seat_info"),
                        price=result.get("price"),
                        html_response=None,
                        job_id=job_id,
                    )

                print(f"[TRA Job {job_id}] 訂票失敗: {result['message']}")
                await job_manager.update_job(
                    job_id,
                    retry_count=retry_count,
                    message=f"第 {retry_count} 次失敗: {result['message']}",
                )
            except Exception as e:
                print(f"[TRA Job {job_id}] 發生未預期錯誤: {e}")
                await job_manager.update_job(
                    job_id,
                    retry_count=retry_count,
                    message=f"第 {retry_count} 次異常: {str(e)}",
                )

            print(f"[TRA Job {job_id}] 等待 10 秒後重試 (可中斷)...")
            should_continue = await cancellable_sleep(10.0, cancel_event, request)
            if not should_continue:
                break

        await job_manager.update_job(job_id, status="cancelled", message="工作已取消或用戶端斷線")
        raise HTTPException(status_code=499, detail="訂票工作已取消或用戶端已中斷連線")


@app.get("/stations", tags=["車站"])
def get_stations():
    """取得所有車站代碼"""
    return STATION_CODES


@app.post(
    "/thsr/booking",
    response_model=THSRBookingResponse,
    tags=["高鐵訂票"],
    summary="送出高鐵訂票",
)
async def create_thsr_booking(booking: THSRBookingRequest, request: Request):
    """持續重試單程成人票訂位，直到成功或呼叫端中斷連線。"""
    job_id = _extract_job_id(request)
    cancel_event = await job_manager.register_job(job_id, service="thsr")

    if await request.is_disconnected():
        await job_manager.update_job(job_id, status="cancelled", message="用戶端已中斷連線")
        raise HTTPException(status_code=499, detail="用戶端已中斷連線")

    async with job_manager.semaphore:
        if cancel_event.is_set() or await request.is_disconnected():
            await job_manager.update_job(job_id, status="cancelled", message="工作已取消或用戶端斷線")
            raise HTTPException(status_code=499, detail="訂票工作已取消或用戶端已中斷連線")

        retry_count = 0
        while not cancel_event.is_set():
            if await request.is_disconnected():
                cancel_event.set()
                break

            retry_count += 1
            print(f"\n--- [THSR Job {job_id}] 開始第 {retry_count} 次訂票嘗試 ---")
            await job_manager.update_job(
                job_id,
                status="running",
                retry_count=retry_count,
                message=f"執行第 {retry_count} 次訂票嘗試",
            )

            result = await thsr_browser.book_ticket(booking)
            if result["success"]:
                print(f"[THSR Job {job_id}] 高鐵訂票成功！(嘗試次數: {retry_count})")
                await job_manager.update_job(
                    job_id,
                    status="completed",
                    retry_count=retry_count,
                    message=result["message"],
                    booking_code=result.get("booking_code"),
                )
                return THSRBookingResponse(
                    job_id=job_id,
                    **result,
                )

            print(f"[THSR Job {job_id}] 高鐵訂票失敗 (第 {retry_count} 次): {result['message']}")
            await job_manager.update_job(
                job_id,
                retry_count=retry_count,
                message=f"第 {retry_count} 次失敗: {result['message']}",
            )

            should_continue = await cancellable_sleep(10.0, cancel_event, request)
            if not should_continue:
                break

        await job_manager.update_job(job_id, status="cancelled", message="工作已取消或用戶端斷線")
        raise HTTPException(status_code=499, detail="訂票工作已取消或用戶端已中斷連線")


@app.get("/booking/jobs", tags=["工作管理"], summary="查詢訂票工作清單")
async def list_booking_jobs(limit: int = 50):
    return await job_manager.list_jobs(limit=limit)


@app.get("/booking/jobs/{job_id}", tags=["工作管理"], summary="查詢單一訂票工作狀態")
async def get_booking_job(job_id: str):
    job = await job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"找不到訂票工作: {job_id}")
    return job


@app.post("/booking/jobs/{job_id}/cancel", tags=["工作管理"], summary="取消訂票工作")
@app.delete("/booking/jobs/{job_id}", tags=["工作管理"], summary="取消訂票工作")
async def cancel_booking_job(job_id: str):
    cancelled = await job_manager.cancel_job(job_id)
    if not cancelled:
        job = await job_manager.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"找不到訂票工作: {job_id}")
        return {"success": False, "job_id": job_id, "message": f"工作目前狀態為 {job.status}，無法取消"}
    return {"success": True, "job_id": job_id, "message": f"工作 {job_id} 已成功發送取消請求"}


@app.get("/health", tags=["健康檢查"])
async def health_check():
    """健康檢查"""
    browser_ok = bool(browser_manager.browser and browser_manager.browser.is_connected())
    return {
        "status": "ok" if browser_ok else "degraded",
        "browser": "playwright",
        "browser_connected": browser_ok,
        "services": ["tra", "thsr"],
        "active_jobs": job_manager.get_active_count(),
        "max_concurrency": job_manager.max_concurrency,
    }
