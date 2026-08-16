"""台灣高鐵訂票流程的 Playwright 實作。"""

import asyncio
import re
from typing import Optional

from playwright.async_api import (
    Browser,
    Locator,
    Page,
)

from .browser_manager import BrowserManager, browser_manager
from .models import THSRBookingRequest, THSRDepartureTime


class THSRBookingBrowser:
    """以高鐵官方網路訂位頁執行單程成人票訂位。"""

    BOOKING_URL = "https://irs.thsrc.com.tw/IMINT/"
    BROWSER_ARGS = BrowserManager.OPTIMIZED_ARGS
    HEADLESS_CHANNEL = BrowserManager.HEADLESS_CHANNEL

    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
        self._user_agent: Optional[str] = None
        self._start_lock = asyncio.Lock()

    async def start(self, headless: bool = True):
        """啟動高鐵訂票專用瀏覽器。"""
        async with self._start_lock:
            self.browser = await browser_manager.start(headless=headless)
            self.playwright = browser_manager.playwright
            self._user_agent = browser_manager.user_agent

    async def stop(self):
        """關閉瀏覽器及 Playwright runtime。"""
        await browser_manager.stop()
        self.browser = None
        self.playwright = None
        self._user_agent = None

    @staticmethod
    def _normalize_user_agent(user_agent: str) -> str:
        """新版 Headless 仍帶 HeadlessChrome；改為對應的正常 Chrome UA。"""
        return BrowserManager.normalize_user_agent(user_agent)

    async def _new_context(self):
        if not self.browser:
            raise RuntimeError("高鐵瀏覽器尚未啟動")
        options = {"locale": "zh-TW"}
        if self._user_agent:
            options["user_agent"] = self._user_agent
        return await self.browser.new_context(**options)

    def _recognize_captcha(self, image: bytes) -> str:
        ocr = browser_manager.get_ocr()
        result = ocr.classification(image)
        return re.sub(r"[^0-9A-Za-z]", "", result).upper()[:4]

    async def book_ticket(self, booking: THSRBookingRequest) -> dict:
        """完成查詢、選車、填寫乘車人資料與送出訂位。"""
        if not self.browser:
            await self.start()

        try:
            departure_time = (
                booking.departure_time.value if booking.departure_time else None
            )
            use_early_bird = bool(booking.passenger_ids)
            if booking.train_no and not use_early_bird and not departure_time:
                departure_time = await self._resolve_train_departure_time(booking)
        except Exception as exc:
            return self._failure(f"高鐵訂票過程發生錯誤: {exc}")

        context = await self._new_context()
        page = await context.new_page()
        try:
            await page.goto(
                self.BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_selector("form#BookingS1Form, img.captcha-img", timeout=30_000)
            await self._accept_cookie_policy(page)
            await self._fill_query_form(
                page,
                booking,
                query_by_train=bool(booking.train_no and use_early_bird),
                departure_time=departure_time,
            )
            await self._submit_form(page, "form#BookingS1Form")
            await self._wait_for_result(page, "main.step-2, main.step-3, main.step-4")

            error = await self._page_error(page)
            if error:
                return self._failure(error)

            if await page.locator("main.step-2").count():
                await self._select_train(page, booking.train_no)
                await self._wait_for_result(page, "main.step-3, main.step-4")
                error = await self._page_error(page)
                if error:
                    return self._failure(error)

            if not await page.locator("main.step-3").count():
                return self._failure("高鐵訂位流程未進入旅客資料確認頁")

            if not use_early_bird:
                await self._assert_not_early_bird(page)
            await self._fill_confirm_form(page, booking)
            await self._submit_confirm_form(page)
            await self._wait_for_result(page, "main.step-4")

            error = await self._page_error(page)
            if error:
                return self._failure(error)

            html = await page.content()
            text = await page.locator("body").inner_text()
            return self._parse_booking_result(html, text)
        except Exception as exc:
            return self._failure(f"高鐵訂票過程發生錯誤: {exc}")
        finally:
            try:
                await context.close()
            except Exception:
                pass

    async def _fill_query_form(
        self,
        page: Page,
        booking: THSRBookingRequest,
        *,
        query_by_train: Optional[bool] = None,
        departure_time: Optional[str] = None,
    ):
        form = page.locator("form#BookingS1Form")
        await self._select_if_present(form, "tripCon:typesoftrip", "0")
        await self._select_if_present(form, "trainCon:trainRadioGroup", "0")
        await self._select_if_present(form, "seatCon:seatRadioGroup", "0")

        await form.locator('[name="selectStartStation"]').select_option(
            str(booking.start_station)
        )
        await form.locator('[name="selectDestinationStation"]').select_option(
            str(booking.dest_station)
        )
        date_value = booking.ride_date.strftime("%Y/%m/%d")
        for field_name in ("toTimeInputField", "backTimeInputField"):
            date_input = form.locator(f'[name="{field_name}"]')
            await date_input.evaluate(
                """
                (element, value) => {
                    element.value = value;
                    element.setAttribute("value", value);
                    element.dispatchEvent(new Event("input", { bubbles: true }));
                    element.dispatchEvent(new Event("change", { bubbles: true }));
                }
                """,
                date_value,
            )

        if query_by_train is None:
            query_by_train = bool(booking.train_no)

        if query_by_train:
            await self._check_if_present(form, "bookingMethod", "radio33")
            await form.locator('[name="toTrainIDInputField"]').fill(booking.train_no)
        else:
            await self._check_if_present(form, "bookingMethod", "radio31")
            selected_time = departure_time or (
                booking.departure_time.value if booking.departure_time else None
            )
            if not selected_time:
                raise RuntimeError("原價全票查詢缺少出發時段")
            await form.locator('[name="toTimeTable"]').select_option(
                selected_time
            )

        await form.locator(
            '[name="ticketPanel:rows:0:ticketAmount"]'
        ).select_option(f"{booking.head_count}F")
        train_requirement = form.locator(
            '[name="trainTypeContainer:typesoftrain"]'
        )
        if await train_requirement.count() and await train_requirement.is_enabled():
            await train_requirement.select_option(
                "0" if booking.passenger_ids else "2"
            )

        captcha = form.locator("img.captcha-img")
        captcha_code = self._recognize_captcha(await captcha.screenshot())
        if len(captcha_code) != 4:
            raise RuntimeError("高鐵驗證碼辨識失敗")
        await form.locator('[name="homeCaptcha:securityCode"]').fill(captcha_code)

    async def _accept_cookie_policy(self, page: Page):
        policy = page.locator("#cookiePolicy")
        if not await policy.count() or not await policy.is_visible():
            return
        accept_button = policy.locator("#cookieAccpetBtn")
        if not await accept_button.count():
            raise RuntimeError("找不到高鐵 Cookie Policy 同意按鈕")
        await accept_button.click()

    async def _select_train(self, page: Page, train_no: Optional[str]):
        form = page.locator("form#BookingS2Form")
        trains = form.locator(
            'input[name="TrainQueryDataViewPanel:TrainGroup"]:not([disabled])'
        )
        if not await trains.count():
            raise RuntimeError("查無可選擇的高鐵班次")

        selected = trains.first
        if train_no:
            selected = None
            for index in range(await trains.count()):
                train = trains.nth(index)
                label_text = await train.evaluate(
                    """
                    (element) => {
                        const label = element.closest("label");
                        return label ? label.innerText : "";
                    }
                    """
                )
                if re.search(
                    rf"directions_railway\s*{re.escape(train_no)}\b",
                    label_text,
                ):
                    selected = train
                    break
            if selected is None:
                raise RuntimeError(f"原價全票查詢結果找不到指定車次 {train_no}")

        await selected.check()
        await self._submit_form(page, "form#BookingS2Form")

    async def _resolve_train_departure_time(
        self, booking: THSRBookingRequest
    ) -> str:
        """先用車次查詢取得出發時間；只讀取結果，不送出訂位。"""
        context = await self._new_context()
        page = await context.new_page()
        try:
            await page.goto(
                self.BOOKING_URL,
                wait_until="domcontentloaded",
                timeout=60_000,
            )
            await page.wait_for_selector("form#BookingS1Form", timeout=30_000)
            await self._accept_cookie_policy(page)
            await self._fill_query_form(page, booking, query_by_train=True)
            await self._submit_form(page, "form#BookingS1Form")
            await self._wait_for_result(page, "main.step-2, main.step-3")
            error = await self._page_error(page)
            if error:
                raise RuntimeError(error)
            main_text = await page.locator("main").inner_text()
            match = re.search(r"\b([01]\d|2[0-3]):([0-5]\d)\b", main_text)
            if not match:
                raise RuntimeError(f"無法取得指定車次 {booking.train_no} 的出發時間")
            return self._time_to_slot_code(match.group(0))
        finally:
            try:
                await context.close()
            except Exception:
                pass

    @staticmethod
    def _time_to_slot_code(departure_time: str) -> str:
        """將 HH:MM 向下對齊為高鐵表單的半小時時段代碼。"""
        hour, minute = (int(part) for part in departure_time.split(":"))
        minute = 30 if minute >= 30 else 0
        if hour == 0:
            code = "1230A" if minute else "1201A"
        elif hour < 12:
            code = f"{hour}{minute:02d}A"
        elif hour == 12:
            code = "1230P" if minute else "1200N"
        else:
            code = f"{hour - 12}{minute:02d}P"

        if code not in {item.value for item in THSRDepartureTime}:
            raise RuntimeError(
                f"高鐵車次出發時間不在可查詢時段內: {departure_time}"
            )
        return code

    async def _assert_not_early_bird(self, page: Page):
        details = await page.locator("main.step-3").inner_text()
        if "早鳥" in details:
            raise RuntimeError("高鐵回傳早鳥票種，已停止送出訂位")

    async def _fill_confirm_form(self, page: Page, booking: THSRBookingRequest):
        form = page.locator("form#BookingS3FormSP, form#BookingS3Form")
        await self._select_if_present(form, "idInputRadio", "0")
        await self._fill_first_available(
            form,
            ("#idNumber", '[name="dummyId"]'),
            booking.id,
            "身分證欄位",
        )
        await self._fill_first_available(
            form,
            ("#mobilePhone", '[name="dummyPhone"]'),
            booking.phone,
            "手機欄位",
        )
        if booking.email:
            await self._fill_first_available(
                form,
                ("#email", '[name="email"]'),
                booking.email,
                "Email 欄位",
            )

        await self._check_first_available(
            form,
            (
                "#memberSystemRadio3",
                'input[name="TicketMemberSystemInputPanel:TakerMemberSystemDataView:memberSystemRadioGroup"][value="radio45"]',
            ),
        )
        if booking.passenger_ids:
            passenger_fields = form.locator(
                'input[name*="passengerDataIdNumber"]'
            )
            if await passenger_fields.count() < len(booking.passenger_ids):
                raise RuntimeError("高鐵早鳥乘客證件欄位數量不足")
            for index, passenger_id in enumerate(booking.passenger_ids):
                await passenger_fields.nth(index).fill(passenger_id)
        agree = form.locator('[name="agree"]')
        if await agree.count() and not await agree.is_checked():
            await agree.check()

    async def _fill_first_available(
        self,
        form: Locator,
        selectors: tuple[str, ...],
        value: str,
        label: str,
    ):
        for selector in selectors:
            field = form.locator(selector)
            if await field.count():
                await field.fill(value)
                return
        raise RuntimeError(f"找不到高鐵{label}")

    async def _check_first_available(
        self,
        form: Locator,
        selectors: tuple[str, ...],
    ):
        for selector in selectors:
            field = form.locator(selector)
            if await field.count():
                await field.check()
                return
        raise RuntimeError("找不到高鐵非會員選項")

    async def _check_if_present(self, form: Locator, name: str, value: str):
        option = form.locator(f'input[name="{name}"][value="{value}"]')
        if await option.count():
            await option.check()

    async def _select_if_present(self, form: Locator, name: str, value: str):
        field = form.locator(f'select[name="{name}"]')
        if await field.count():
            await field.select_option(value)

    async def _submit_form(self, page: Page, form_selector: str):
        form = page.locator(form_selector)
        submit = form.locator(
            'input[name="SubmitButton"], button[type="submit"], input[type="submit"]'
        ).last
        if not await submit.count():
            raise RuntimeError(f"找不到表單送出按鈕: {form_selector}")
        await submit.click(timeout=60_000)

    async def _submit_confirm_form(self, page: Page):
        form = page.locator("form#BookingS3FormSP, form#BookingS3Form")
        submit = form.locator("#isSubmit")
        if not await submit.count():
            raise RuntimeError("找不到高鐵完成訂位按鈕")
        await submit.click(timeout=60_000)

    async def _wait_for_result(self, page: Page, expected_steps: str):
        await page.wait_for_selector(
            f"{expected_steps}, .feedbackPanelERROR:visible, div.error-content:visible",
            timeout=60_000,
        )

    async def _page_error(self, page: Page) -> Optional[str]:
        error = page.locator(
            ".feedbackPanelERROR:visible, div.error-content:visible"
        ).first
        if not await error.count():
            return None
        message = (await error.inner_text()).strip()
        return message or "高鐵訂位系統回傳未知錯誤"

    @staticmethod
    def _failure(message: str) -> dict:
        return {
            "success": False,
            "message": message,
            "booking_code": None,
            "train_no": None,
            "seat_info": None,
            "price": None,
        }

    @classmethod
    def _parse_booking_result(cls, html: str, text: str) -> dict:
        def extract(patterns):
            for pattern in patterns:
                match = re.search(pattern, text, re.IGNORECASE)
                if match:
                    return match.group(1).strip()
            return None

        booking_code = extract(
            [
                r"訂位(?:代號|代碼)\s*[：:]?\s*([A-Z0-9]{6,12})",
                r"booking\s*(?:code|number)\s*[：:]?\s*([A-Z0-9]{6,12})",
            ]
        )
        train_no = extract([r"車次\s*[：:]?\s*(\d{2,4})", r"(\d{2,4})\s*車次"])
        seat_info = extract(
            [
                r"座位\s*[：:]?\s*([^\n]+)",
                r"(\d+\s*車\s*\d+\s*號)",
            ]
        )
        price_text = extract(
            [r"(?:票價|總金額|應付金額)\D{0,10}(\d[\d,]*)", r"NT\$\s*([\d,]+)"]
        )
        price = int(price_text.replace(",", "")) if price_text else None

        if booking_code or "main step-4" in html or "step-4" in html:
            message = "高鐵訂位成功"
            if booking_code:
                message += f"，訂位代號: {booking_code}"
            return {
                "success": True,
                "message": message,
                "booking_code": booking_code,
                "train_no": train_no,
                "seat_info": seat_info,
                "price": price,
            }

        return cls._failure("無法辨識高鐵訂位結果")


thsr_browser = THSRBookingBrowser()
