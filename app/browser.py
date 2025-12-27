"""
台鐵訂票系統 - Playwright 瀏覽器自動化
"""
import asyncio
from playwright.async_api import async_playwright, Page, Browser
from typing import Optional
import re


class TRABookingBrowser:
    """台鐵訂票瀏覽器自動化"""
    
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None
    
    async def start(self, headless: bool = True):
        """啟動瀏覽器"""
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=headless)
    
    async def stop(self):
        """關閉瀏覽器"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
    
    async def book_ticket(
        self,
        pid: str,
        start_station: str,
        end_station: str,
        ride_date: str,
        start_time: str = "00:00",
        end_time: str = "23:59",
        qty: int = 1,
        train_types: list = None
    ) -> dict:
        """
        執行訂票
        
        Returns:
            dict: {
                "success": bool,
                "message": str,
                "booking_code": str | None,
                "train_no": str | None,
                "seat_info": str | None,
                "price": int | None
            }
        """
        if not self.browser:
            await self.start()
        
        page = await self.browser.new_page()
        
        try:
            # Step 1: 前往訂票頁面
            await page.goto(
                "https://www.railway.gov.tw/tra-tip-web/tip/tip001/tip121/query",
                wait_until="networkidle",
                timeout=30000
            )
            
            # 等待表單載入
            await page.wait_for_selector('input[name="pid"]', timeout=10000)
            
            # Step 2: 填寫表單
            # 身分證
            await page.fill('input[name="pid"]', pid)
            
            # 起站
            await page.click('input[name="startStation"]')
            await page.fill('input[name="startStation"]', start_station)
            await asyncio.sleep(0.5)
            # 選擇下拉選項
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            
            # 終站
            await page.click('input[name="endStation"]')
            await page.fill('input[name="endStation"]', end_station)
            await asyncio.sleep(0.5)
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            
            # 乘車日期
            date_input = page.locator('input[name="ticketOrderParamList[0].rideDate"]')
            await date_input.clear()
            await date_input.fill(ride_date)
            
            # 票數
            if qty > 1:
                qty_input = page.locator('input[name="normalQty"]')
                await qty_input.clear()
                await qty_input.fill(str(qty))
            
            # Step 3: 點擊訂票按鈕
            # 等待 reCAPTCHA 載入完成
            await asyncio.sleep(2)
            
            # 找到並點擊訂票按鈕
            submit_btn = page.locator('label.btn-submit, button:has-text("訂票"), input[type="submit"]').first
            await submit_btn.click()
            
            # 等待頁面跳轉或結果
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            # Step 4: 解析結果
            page_content = await page.content()
            
            # 提取訂票資訊
            result = self._parse_booking_result(page_content)
            
            # 截圖保存
            await page.screenshot(path="booking_result.png")
            
            return result
            
        except Exception as e:
            return {
                "success": False,
                "message": f"訂票過程發生錯誤: {str(e)}",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }
        finally:
            await page.close()
    
    def _parse_booking_result(self, html: str) -> dict:
        """解析訂票結果頁面"""
        
        def extract_field(patterns, text):
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    return match.group(1).strip()
            return None
        
        # 訂票代碼
        booking_code = extract_field([
            r'訂票代碼[：:]\s*(\d+)',
            r'訂位代號[：:]\s*(\d+)',
            r'代號[：:]\s*(\d+)',
        ], html)
        
        # 車次
        train_no = extract_field([
            r'(\d+)\s*車次',
            r'車次[：:]\s*(\d+)',
        ], html)
        
        # 車種
        train_type = extract_field([
            r'(自強|莒光|區間快?|普悠瑪|太魯閣)',
        ], html)
        
        # 座位
        seat_info = extract_field([
            r'(\d+車\d+號)',
            r'座位[：:]\s*(\S+)',
        ], html)
        
        # 票價
        price_str = extract_field([
            r'(\d+)\s*元',
            r'票價[：:]\s*(\d+)',
        ], html)
        price = int(price_str) if price_str else None
        
        # 判斷結果
        if booking_code:
            message_parts = ["訂票成功！"]
            if booking_code:
                message_parts.append(f"訂票代碼: {booking_code}")
            if train_type and train_no:
                message_parts.append(f"車次: {train_type} {train_no}")
            if seat_info:
                message_parts.append(f"座位: {seat_info}")
            if price:
                message_parts.append(f"票價: {price}元")
            
            return {
                "success": True,
                "message": " | ".join(message_parts),
                "booking_code": booking_code,
                "train_no": f"{train_type} {train_no}" if train_type and train_no else train_no,
                "seat_info": seat_info,
                "price": price
            }
        elif "無符合條件" in html:
            return {
                "success": False,
                "message": "無符合條件的班次",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }
        elif "已售完" in html:
            return {
                "success": False,
                "message": "該班次已售完",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }
        elif "請選擇車次" in html or "班次" in html:
            return {
                "success": False,
                "message": "請手動選擇班次，系統已到達班次選擇頁面",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }
        else:
            return {
                "success": False,
                "message": "訂票結果未知，請查看截圖 booking_result.png",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }


# 全域瀏覽器實例
tra_browser = TRABookingBrowser()
