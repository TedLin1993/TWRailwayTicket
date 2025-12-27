"""
台鐵訂票系統 - Playwright 瀏覽器自動化
"""
import asyncio
from playwright.async_api import async_playwright, Page, Browser
from typing import Optional
import re

from .models import OrderType


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
        order_type: OrderType = OrderType.BY_TRAIN,
        train_no: str = None,
        start_time: str = "00:00",
        end_time: str = "23:59",
        qty: int = 1,
        train_types: list = None
    ) -> dict:
        """
        執行訂票
        
        Args:
            order_type: "BY_TRAIN" (依車次) 或 "BY_TIME" (依時段)
            train_no: 車次號碼 (依車次訂票時必填)
        
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
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            
            # 終站
            await page.click('input[name="endStation"]')
            await page.fill('input[name="endStation"]', end_station)
            await asyncio.sleep(0.5)
            await page.keyboard.press("ArrowDown")
            await page.keyboard.press("Enter")
            
            # 選擇訂票方式
            if order_type == OrderType.BY_TRAIN:
                # 點擊「依車次」
                train_btn = page.locator('label:has-text("依車次"), input[value="BY_TRAIN"]')
                await train_btn.click()
                await asyncio.sleep(0.3)
                
                # 填寫車次號碼
                if train_no:
                    train_input = page.locator('input[name="ticketOrderParamList[0].trainNoList[0]"]').first
                    await train_input.fill(train_no)
            else:
                # 依時段 - 點擊「依時段」
                time_btn = page.locator('label:has-text("依時段"), input[value="BY_TIME"]')
                await time_btn.click()
                await asyncio.sleep(0.3)
            
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
            await asyncio.sleep(2)
            
            submit_btn = page.locator('label.btn-submit, button:has-text("訂票"), input[type="submit"]').first
            await submit_btn.click()
            
            # 等待頁面跳轉
            await page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)
            
            # Step 4: 檢查是否在班次選擇頁面
            page_content = await page.content()
            
            # 定義 CAPTCHA 處理函式
            async def handle_captcha():
                """處理圖形驗證碼"""
                print("開始處理驗證碼...")
                try:
                    import ddddocr
                    ocr = ddddocr.DdddOcr(show_ad=False)
                except Exception as e:
                    print(f"ddddocr 初始化失敗: {e}")
                    return False
                
                max_retries = 3
                for i in range(max_retries):
                    try:
                        print(f"嘗試辨識驗證碼 (第 {i+1} 次)...")
                        await asyncio.sleep(1) # 等待圖片載入
                        
                        # 檢查是否有驗證碼圖片
                        # 使用 subagent 確認的選擇器
                        captcha_img = page.locator('#codeimg').first
                        if await captcha_img.count() == 0:
                            # 備用選擇器
                            captcha_img = page.locator('img[src*="captcha"], img[alt*="驗證碼"]').first
                        
                        if await captcha_img.count() == 0:
                            print("找不到驗證碼圖片元素")
                            await page.screenshot(path="debug_captcha_missing.png")
                            return False
                            
                        # 截取驗證碼圖片
                        await captcha_img.screenshot(path="captcha.png")
                        print("已截取驗證碼圖片")
                        
                        # 識別驗證碼
                        with open("captcha.png", 'rb') as f:
                            img_bytes = f.read()
                        res = ocr.classification(img_bytes)
                        print(f"驗證碼識別結果: {res}")
                        
                        if not res or len(res) < 3: # 有些驗證碼可能只有4碼，放寬一點
                            print("驗證碼識別內容過短，重試...")
                            refresh_btn = page.locator('#changeVoice').first
                            if await refresh_btn.count() > 0:
                                await refresh_btn.click()
                                await asyncio.sleep(1)
                            continue
                            
                        # 填入驗證碼
                        # 使用 subagent 確認的選擇器 #verifyCode
                        captcha_input = page.locator('#verifyCode').first
                        if await captcha_input.count() > 0:
                            await captcha_input.click()
                            await captcha_input.clear()
                            await captcha_input.fill(res)
                            print(f"已填入驗證碼: {res}")
                        else:
                            print("找不到驗證碼輸入框 (#verifyCode)")
                            # 嘗試備用
                            captcha_input = page.locator('input[name="g-recaptcha-response"], input.verifyCode').first
                            if await captcha_input.count() > 0:
                                await captcha_input.fill(res)
                            else:
                                continue
                        
                        # 點擊確認/送出
                        submit_btn = page.locator('button#btn-confirm, button.btn-confirm, button:has-text("確認"), input[value="送出"]').first
                        if await submit_btn.count() == 0:
                             # 有時候確認按鈕可能就是原本的訂票按鈕？不，驗證碼區塊通常有自己的按鈕
                             # 根據截圖或經驗，有時候是直接 enter，或者有一個"送出"
                             submit_btn = page.locator('input[type="submit"], button.btn').last 
                        
                        if await submit_btn.count() > 0:
                            await submit_btn.click()
                            print("已點擊確認按鈕")
                            
                            # 等待結果
                            try:
                                await page.wait_for_load_state("networkidle", timeout=10000)
                                await asyncio.sleep(2)
                                
                                # 檢查是否進入了資料確認頁 (modify)
                                if "booking/modify" in page.url:
                                    print("進入資料確認頁面，嘗試確認...")
                                    # 截圖以供參考
                                    await page.screenshot(path="booking_modify.png")
                                    
                                    # 嘗試更多按鈕選擇器
                                    confirm_modify_btn = page.locator('button:has-text("直接"), button:has-text("下一步"), button:has-text("確認"), input[value="確認"], button.btn-3d, input[type="submit"]').last
                                    if await confirm_modify_btn.count() > 0:
                                        print(f"找到確認按鈕: {await confirm_modify_btn.inner_text() if await confirm_modify_btn.count() == 1 else 'multiple'}")
                                        await confirm_modify_btn.click()
                                        await page.wait_for_load_state("networkidle", timeout=10000)
                                        await asyncio.sleep(2)
                                    else:
                                        print("在確認頁面找不到確認按鈕")
                                
                                # 檢查是否還有錯誤訊息
                                content = await page.content()
                                if "驗證碼錯誤" not in content and "請輸入驗證碼" not in content and "驗證未通過" not in content:
                                    print("驗證碼似乎通過！")
                                    return True
                                else:
                                    print("頁面仍顯示驗證碼錯誤，重試...")
                            except Exception as e:
                                print(f"等待回應時發生例外: {e}")
                                pass
                    except Exception as e:
                        print(f"處理驗證碼時發生錯誤: {e}")
                
                print("驗證碼處理超過最大重試次數")
                return False

            # 如果頁面有班次選擇，自動選擇第一個班次
            if "請選擇欲訂購車次" in page_content or "ticketSelectList" in page_content:
                # 截圖 - 班次選擇頁
                await page.screenshot(path="train_selection.png")
                
                # 嘗試選擇第一個可用班次的 checkbox
                train_checkbox = page.locator('input[type="checkbox"][name*="ticketSelectList"]').first
                if await train_checkbox.count() > 0:
                    await train_checkbox.click()
                    await asyncio.sleep(0.5)
                else:
                    # 嘗試 radio button
                    train_radio = page.locator('input[type="radio"]').first
                    if await train_radio.count() > 0:
                        await train_radio.click()
                        await asyncio.sleep(0.5)
                
                # 點擊確認訂票按鈕
                confirm_btn = page.locator('label.btn-confirm, button.btn-confirm, label:has-text("確認訂票"), button:has-text("確認"), input[type="submit"]').first
                if await confirm_btn.count() > 0:
                    await confirm_btn.click()
                    await page.wait_for_load_state("networkidle", timeout=30000)
                    await asyncio.sleep(2)
                    
                    # 檢查是否有驗證碼
                    page_content = await page.content()
                    if "請輸入驗證碼" in page_content or "驗證未通過" in page_content:
                        print("偵測到驗證碼要求 (在班次選擇後)")
                        await handle_captcha()
                        page_content = await page.content()
            
            # 如果直接出現驗證碼 (非班次選擇頁)
            elif "請輸入驗證碼" in page_content or "驗證未通過" in page_content:
                print("偵測到驗證碼要求 (直接出現)")
                await handle_captcha()
                page_content = await page.content()
            
            # Step 5: 解析結果
            print(f"目前頁面 URL: {page.url}")
            # 獲取純文字內容，這對於提取 "訂票代碼: 123456" 這種被 HTML 標籤隔開的格式非常有用
            page_text = await page.inner_text("body")
            result = self._parse_booking_result(page_content, page_text)
            
            # 截圖保存
            await page.screenshot(path="booking_result.png")
            
            return result
            
        except Exception as e:
            print(f"訂票過程發生例外: {e}")
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
    
    def _parse_booking_result(self, html: str, text: str = "") -> dict:
        """解析訂票結果頁面"""
        
        # 優先檢查失敗訊息 (同時檢查 HTML 和渲染後的 Text)
        # 增加更多可能的失敗關鍵字
        error_keywords = ["請輸入驗證碼", "驗證未通過", "驗證碼錯誤", "檢核碼錯誤", "機器人驗證"]
        for keyword in error_keywords:
            if keyword in html or keyword in text:
                return {
                    "success": False,
                    "message": f"系統偵測到驗證失敗: {keyword}",
                    "booking_code": None,
                    "train_no": None,
                    "seat_info": None,
                    "price": None
                }
        
        def extract_field(patterns, content):
            if not content: return None
            for pattern in patterns:
                match = re.search(pattern, content)
                if match:
                    return match.group(1).strip()
            return None
        
        # 優先從純文字中提取訂票代碼
        # 修正：支援 6 到 8 位數字 (使用者回報有 7 位數代碼)
        # 嚴格模式：必須要有前綴
        booking_code = extract_field([
            r'訂票代碼\D*(\d{6,8})', 
            r'訂位代號\D*(\d{6,8})',
            r'代號\D*(\d{6,8})',
            r'電腦代碼\D*(\d{6,8})',
            r'code\D*(\d{6,8})',
        ], text)
        
        # 如果嚴格模式沒找到，不要再嘗試寬鬆模式，以免誤判 (例如抓到 footer 的電話與分機)
        # 只要頁面有 "訂票代碼" 關鍵字，上面的 regex 應該就能抓到
        
        # 車次
        train_no = extract_field([
            r'(\d+)\s*車次',
            r'車次\D*(\d+)',
        ], text)
        if not train_no:
            train_no = extract_field([r'(\d+)\s*車次'], html)
        
        # 車種
        train_type = extract_field([
            r'(自強|莒光|區間快?|普悠瑪|太魯閣)',
        ], text)
        
        # 座位
        seat_info = extract_field([
            r'(\d+車\d+號)',
            r'座位\D*(\d+車\d+號)',
            r'座位[：:]\s*(\S+)', # 保留這個但放在後面
        ], text)
        
        # 票價
        price_str = extract_field([
            r'(\d+)\s*元',
            r'票價\D*(\d+)',
        ], text)
        price = int(price_str) if price_str else None
        
        if booking_code:
            message_parts = ["訂票成功！"]
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

        elif "無符合條件" in html or "剩餘座位不足" in html:
            error_match = re.search(r'class="error[^"]*"[^>]*>([^<]+)', html)
            msg = error_match.group(1).strip() if error_match else "無符合條件或座位不足"
            return {
                "success": False,
                "message": msg,
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
        elif "請選擇欲訂購車次" in html:
            return {
                "success": False,
                "message": "請手動選擇班次，系統已到達班次選擇頁面",
                "booking_code": None,
                "train_no": None,
                "seat_info": None,
                "price": None
            }
        else:
            print("訂票結果未知，HTML 標題:")
            match_title = re.search(r'<title>(.*?)</title>', html)
            if match_title:
                print(match_title.group(1))
            
            # 嘗試尋找 body 內容 (忽略大小寫)
            body_start = html.lower().find("<body")
            if body_start != -1:
                print("HTML Body 摘要:")
                # 印出 body 開始後的 2000 字元，並過濾掉 script
                body_content = html[body_start:body_start+4000]
                # 簡單移除 script 標籤內容以減少垃圾訊息
                body_content = re.sub(r'<script.*?>.*?</script>', '', body_content, flags=re.DOTALL)
                print(body_content[:3000])
            else:
                print("HTML 內容摘要 (前 2000 字元):")
                print(html[:2000])
            
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
