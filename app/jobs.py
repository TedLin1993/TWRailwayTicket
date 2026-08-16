'''
訂票工作與併發管理模組。
提供全域 Semaphore(3) 限制與合作式取消機制。
'''
import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from fastapi import Request
from pydantic import BaseModel


class JobInfo(BaseModel):
    '''訂票工作資訊模型。'''
    job_id: str
    service: str  # 'tra' 或 'thsr'
    status: str   # 'running', 'completed', 'cancelled', 'failed'
    retry_count: int = 0
    message: Optional[str] = None
    booking_code: Optional[str] = None
    created_at: str
    updated_at: str


class JobManager:
    '''記憶體內的訂票工作登錄與取消管理器。'''

    def __init__(self, max_concurrency: int = 3):
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.max_concurrency = max_concurrency
        self._jobs: Dict[str, dict] = {}
        self._lock = asyncio.Lock()

    async def register_job(self, job_id: str, service: str) -> asyncio.Event:
        '''註冊新訂票工作並返回專屬取消 Event。'''
        now = datetime.now(timezone.utc).isoformat()
        cancel_event = asyncio.Event()
        async with self._lock:
            self._jobs[job_id] = {
                'job_id': job_id,
                'service': service,
                'status': 'running',
                'retry_count': 0,
                'message': '工作已建立，排隊等待進入瀏覽器',
                'booking_code': None,
                'created_at': now,
                'updated_at': now,
                'cancel_event': cancel_event,
            }
        return cancel_event

    async def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        retry_count: Optional[int] = None,
        message: Optional[str] = None,
        booking_code: Optional[str] = None,
    ):
        '''更新工作狀態與進度。'''
        now = datetime.now(timezone.utc).isoformat()
        async with self._lock:
            job = self._jobs.get(job_id)
            if job:
                if status:
                    job['status'] = status
                if retry_count is not None:
                    job['retry_count'] = retry_count
                if message:
                    job['message'] = message
                if booking_code:
                    job['booking_code'] = booking_code
                job['updated_at'] = now

    async def cancel_job(self, job_id: str) -> bool:
        '''觸發特定工作的取消事件。'''
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False
            if job['status'] == 'running':
                job['status'] = 'cancelled'
                job['message'] = '使用者已請求取消'
                job['updated_at'] = datetime.now(timezone.utc).isoformat()
                job['cancel_event'].set()
                return True
            return False

    async def get_job(self, job_id: str) -> Optional[JobInfo]:
        '''取得單一工作資訊。'''
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            return JobInfo(
                job_id=job['job_id'],
                service=job['service'],
                status=job['status'],
                retry_count=job['retry_count'],
                message=job['message'],
                booking_code=job.get('booking_code'),
                created_at=job['created_at'],
                updated_at=job['updated_at'],
            )

    async def list_jobs(self, limit: int = 50) -> List[JobInfo]:
        '''列出最近的工作清單。'''
        async with self._lock:
            jobs = list(self._jobs.values())
            jobs.sort(key=lambda x: x['created_at'], reverse=True)
            return [
                JobInfo(
                    job_id=j['job_id'],
                    service=j['service'],
                    status=j['status'],
                    retry_count=j['retry_count'],
                    message=j['message'],
                    booking_code=j.get('booking_code'),
                    created_at=j['created_at'],
                    updated_at=j['updated_at'],
                )
                for j in jobs[:limit]
            ]

    def get_active_count(self) -> int:
        '''取得目前執行中的工作數量。'''
        return sum(1 for j in self._jobs.values() if j['status'] == 'running')


async def cancellable_sleep(
    seconds: float,
    cancel_event: asyncio.Event,
    request: Optional[Request] = None,
    step: float = 0.5,
) -> bool:
    '''
    可中斷的等待函式。
    若等待期間 cancel_event 被觸發或用戶端連線中斷，則提前返回 False。
    若順利完成等待，返回 True。
    '''
    elapsed = 0.0
    while elapsed < seconds:
        if cancel_event.is_set():
            return False
        if request and await request.is_disconnected():
            cancel_event.set()
            return False
        wait_chunk = min(step, seconds - elapsed)
        await asyncio.sleep(wait_chunk)
        if cancel_event.is_set():
            return False
        if request and await request.is_disconnected():
            cancel_event.set()
            return False
        elapsed += wait_chunk
    return True


job_manager = JobManager(max_concurrency=3)
