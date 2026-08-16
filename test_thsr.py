import unittest
from datetime import date
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from app.models import THSRBookingRequest
from app.main import app, create_thsr_booking
from app.thsr_browser import thsr_browser
from app.thsr_browser import THSRBookingBrowser


class THSRBookingRequestTests(unittest.TestCase):
    def test_accepts_legacy_pascal_case_payload(self):
        request = THSRBookingRequest.model_validate(
            {
                "Id": "A123456789",
                "Email": "abc@example.com",
                "Phone": "0912345678",
                "StartStation": 2,
                "DestStation": 12,
                "Date": "2026/08/01",
                "Time": "700P",
                "TrainNo": "821",
                "HeadCount": 1,
            }
        )

        self.assertEqual(request.id, "A123456789")
        self.assertEqual(request.ride_date, date(2026, 8, 1))
        self.assertEqual(request.train_no, "821")
        self.assertEqual(request.departure_time.value, "700P")

    def test_accepts_snake_case_payload(self):
        request = THSRBookingRequest.model_validate(
            {
                "id": "A123456789",
                "phone": "0912345678",
                "start_station": 2,
                "dest_station": 7,
                "ride_date": "2026-08-01",
                "departure_time": "900A",
                "head_count": 2,
            }
        )

        self.assertEqual(request.start_station, 2)
        self.assertEqual(request.dest_station, 7)
        self.assertEqual(request.head_count, 2)

    def test_accepts_current_early_morning_time_slots(self):
        request = THSRBookingRequest.model_validate(
            {
                "Id": "A123456789",
                "Phone": "0912345678",
                "StartStation": 2,
                "DestStation": 7,
                "Date": "2026-08-01",
                "Time": "500A",
                "HeadCount": 1,
            }
        )

        self.assertEqual(request.departure_time.value, "500A")

    def test_requires_train_number_or_time(self):
        with self.assertRaises(ValidationError):
            THSRBookingRequest.model_validate(
                {
                    "Id": "A123456789",
                    "Phone": "0912345678",
                    "StartStation": 2,
                    "DestStation": 7,
                    "Date": "2026-08-01",
                    "HeadCount": 1,
                }
            )

    def test_requires_one_passenger_id_per_ticket_when_provided(self):
        with self.assertRaises(ValidationError):
            THSRBookingRequest.model_validate(
                {
                    "Id": "A123456789",
                    "Phone": "0912345678",
                    "StartStation": 2,
                    "DestStation": 7,
                    "Date": "2026/08/01",
                    "TrainNo": "165",
                    "HeadCount": 2,
                    "PassengerIds": ["A123456789"],
                }
            )

    def test_rejects_same_station(self):
        with self.assertRaises(ValidationError):
            THSRBookingRequest.model_validate(
                {
                    "Id": "A123456789",
                    "Phone": "0912345678",
                    "StartStation": 2,
                    "DestStation": 2,
                    "Date": "2026-08-01",
                    "TrainNo": "821",
                    "HeadCount": 1,
                }
            )


class THSRBookingResultTests(unittest.TestCase):
    def test_disables_browser_automation_flag(self):
        self.assertIn(
            "--disable-blink-features=AutomationControlled",
            THSRBookingBrowser.BROWSER_ARGS,
        )
        self.assertEqual(THSRBookingBrowser.HEADLESS_CHANNEL, "chromium")

    def test_normalizes_new_headless_user_agent(self):
        user_agent = THSRBookingBrowser._normalize_user_agent(
            "Mozilla/5.0 HeadlessChrome/131.0.0.0 Safari/537.36"
        )

        self.assertEqual(
            user_agent,
            "Mozilla/5.0 Chrome/131.0.0.0 Safari/537.36",
        )

    def test_converts_departure_time_to_search_slot(self):
        self.assertEqual(THSRBookingBrowser._time_to_slot_code("21:41"), "930P")
        self.assertEqual(THSRBookingBrowser._time_to_slot_code("12:05"), "1200N")

    def test_rejects_time_outside_search_slots(self):
        with self.assertRaises(RuntimeError):
            THSRBookingBrowser._time_to_slot_code("03:15")

    def test_parses_success_result(self):
        result = THSRBookingBrowser._parse_booking_result(
            '<main class="step-4"></main>',
            "訂位代號：AB123456\n車次：821\n座位：3車 12E\n總金額 NT$ 1,490",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["booking_code"], "AB123456")
        self.assertEqual(result["train_no"], "821")
        self.assertEqual(result["seat_info"], "3車 12E")
        self.assertEqual(result["price"], 1490)

    def test_rejects_unknown_result(self):
        result = THSRBookingBrowser._parse_booking_result("<main></main>", "查詢中")

        self.assertFalse(result["success"])
        self.assertIsNone(result["booking_code"])


class THSRApiTests(unittest.TestCase):
    def test_exposes_only_structured_thsr_booking_route(self):
        paths = app.openapi()["paths"]

        self.assertIn("/thsr/booking", paths)
        self.assertNotIn("/Booking", paths)
        self.assertNotIn("/thsr/stations", paths)

    def test_openapi_uses_legacy_request_field_names(self):
        schema = app.openapi()["components"]["schemas"]["THSRBookingRequest"]

        self.assertIn("Id", schema["properties"])
        self.assertIn("StartStation", schema["properties"])
        self.assertIn("HeadCount", schema["required"])


class THSRRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_retries_until_booking_succeeds(self):
        booking = THSRBookingRequest.model_validate(
            {
                "Id": "A123456789",
                "Phone": "0912345678",
                "StartStation": 2,
                "DestStation": 7,
                "Date": "2026/07/21",
                "TrainNo": "693",
                "HeadCount": 2,
            }
        )
        request = AsyncMock()
        request.headers = {}
        request.is_disconnected.return_value = False
        failure = THSRBookingBrowser._failure("驗證碼錯誤")
        success = {
            "success": True,
            "message": "高鐵訂位成功",
            "booking_code": "AB123456",
            "train_no": "693",
            "seat_info": None,
            "price": 1400,
        }

        with (
            patch.object(
                thsr_browser,
                "book_ticket",
                new=AsyncMock(side_effect=[failure, failure, success]),
            ) as book_ticket,
            patch("app.main.cancellable_sleep", new=AsyncMock(return_value=True)) as sleep,
        ):
            response = await create_thsr_booking(booking, request)

        self.assertTrue(response.success)
        self.assertEqual(response.train_no, "693")
        self.assertEqual(book_ticket.await_count, 3)
        self.assertEqual(sleep.await_count, 2)

if __name__ == "__main__":
    unittest.main()
