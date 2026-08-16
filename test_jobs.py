import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.jobs import JobManager, cancellable_sleep
from app.main import (
    app,
    create_booking,
    create_thsr_booking,
    health_check,
    list_booking_jobs,
    get_booking_job,
    cancel_booking_job,
)
from app.models import BookingRequest, OrderType, THSRBookingRequest
from app.browser import tra_browser
from app.thsr_browser import thsr_browser
from fastapi import HTTPException


class JobManagerTests(unittest.IsolatedAsyncioTestCase):
    async def test_register_and_get_job(self):
        jm = JobManager(max_concurrency=3)
        cancel_event = await jm.register_job("job_1", service="tra")

        self.assertIsInstance(cancel_event, asyncio.Event)
        self.assertFalse(cancel_event.is_set())

        job = await jm.get_job("job_1")
        self.assertIsNotNone(job)
        self.assertEqual(job.job_id, "job_1")
        self.assertEqual(job.service, "tra")
        self.assertEqual(job.status, "running")
        self.assertEqual(job.retry_count, 0)

    async def test_update_and_cancel_job(self):
        jm = JobManager(max_concurrency=3)
        cancel_event = await jm.register_job("job_2", service="thsr")

        await jm.update_job("job_2", retry_count=2, message="重試中")
        job = await jm.get_job("job_2")
        self.assertEqual(job.retry_count, 2)
        self.assertEqual(job.message, "重試中")

        cancelled = await jm.cancel_job("job_2")
        self.assertTrue(cancelled)
        self.assertTrue(cancel_event.is_set())

        job_after = await jm.get_job("job_2")
        self.assertEqual(job_after.status, "cancelled")

    async def test_list_jobs_and_active_count(self):
        jm = JobManager(max_concurrency=3)
        await jm.register_job("job_a", service="tra")
        await jm.register_job("job_b", service="thsr")

        self.assertEqual(jm.get_active_count(), 2)

        await jm.cancel_job("job_a")
        self.assertEqual(jm.get_active_count(), 1)

        jobs = await jm.list_jobs()
        self.assertEqual(len(jobs), 2)


class CancellableSleepTests(unittest.IsolatedAsyncioTestCase):
    async def test_sleep_completes_when_not_cancelled(self):
        cancel_event = asyncio.Event()
        result = await cancellable_sleep(0.05, cancel_event, step=0.01)
        self.assertTrue(result)

    async def test_sleep_aborts_when_cancel_event_set(self):
        cancel_event = asyncio.Event()
        cancel_event.set()
        result = await cancellable_sleep(5.0, cancel_event, step=0.01)
        self.assertFalse(result)

    async def test_sleep_aborts_on_client_disconnect(self):
        cancel_event = asyncio.Event()
        request = AsyncMock()
        request.is_disconnected.return_value = True

        result = await cancellable_sleep(5.0, cancel_event, request=request, step=0.01)
        self.assertFalse(result)
        self.assertTrue(cancel_event.is_set())


class JobEndpointsTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_check_endpoint(self):
        data = await health_check()
        self.assertIn("status", data)
        self.assertEqual(data["max_concurrency"], 3)
        self.assertIn("services", data)

    async def test_job_endpoints_lifecycle(self):
        with self.assertRaises(HTTPException) as cm:
            await get_booking_job("non_existent_job_123")
        self.assertEqual(cm.exception.status_code, 404)

        with self.assertRaises(HTTPException) as cm:
            await cancel_booking_job("non_existent_job_123")
        self.assertEqual(cm.exception.status_code, 404)


class CancellationFlowTests(unittest.IsolatedAsyncioTestCase):
    async def test_tra_booking_immediate_disconnect(self):
        booking = BookingRequest.model_validate({
            "pid": "A123456789",
            "start_station": "臺北",
            "end_station": "高雄",
            "ride_date": "2026-08-20",
            "order_type": OrderType.BY_TIME,
            "start_time": "08:00",
            "end_time": "10:00",
            "qty": 1,
        })
        request = AsyncMock()
        request.headers = {"X-Job-ID": "test_tra_disconn"}
        request.is_disconnected.return_value = True

        with self.assertRaises(HTTPException) as cm:
            await create_booking(booking, request)
        self.assertEqual(cm.exception.status_code, 499)

    async def test_thsr_booking_immediate_disconnect(self):
        booking = THSRBookingRequest.model_validate({
            "id": "A123456789",
            "phone": "0912345678",
            "start_station": 2,
            "dest_station": 7,
            "ride_date": "2026-08-20",
            "train_no": "693",
            "head_count": 1,
        })
        request = AsyncMock()
        request.headers = {"X-Job-ID": "test_thsr_disconn"}
        request.is_disconnected.return_value = True

        with self.assertRaises(HTTPException) as cm:
            await create_thsr_booking(booking, request)
        self.assertEqual(cm.exception.status_code, 499)


if __name__ == "__main__":
    unittest.main()
