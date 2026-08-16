'''
Playwright 瀏覽器與 OCR 資源集中管理。
提供單一 Chromium 實例與記憶體優化設定，供台鐵與高鐵模組共用。
'''
import asyncio
from typing import Optional
from playwright.async_api import Browser, async_playwright


class BrowserManager:
    '''管理共用 Playwright 實例與全域 OCR 模型。'''

    OPTIMIZED_ARGS = [
        '--disable-blink-features=AutomationControlled',
        '--disable-gpu',
        '--disable-dev-shm-usage',
        '--no-zygote',
        '--disable-software-rasterizer',
    ]
    HEADLESS_CHANNEL = 'chromium'

    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.user_agent: Optional[str] = None
        self._ocr = None
        self._lock = asyncio.Lock()

    async def start(self, headless: bool = True) -> Browser:
        '''啟動或取得共用 Chromium 瀏覽器實例。'''
        async with self._lock:
            if self.browser:
                return self.browser
            if not self.playwright:
                self.playwright = await async_playwright().start()

            launch_options = {
                'headless': headless,
                'args': self.OPTIMIZED_ARGS,
            }
            if headless:
                launch_options['channel'] = self.HEADLESS_CHANNEL

            self.browser = await self.playwright.chromium.launch(**launch_options)

            probe_context = await self.browser.new_context()
            probe_page = await probe_context.new_page()
            try:
                raw_ua = await probe_page.evaluate('navigator.userAgent')
                self.user_agent = self.normalize_user_agent(raw_ua)
            finally:
                await probe_context.close()

            return self.browser

    async def stop(self):
        '''關閉共用瀏覽器與 Playwright runtime。'''
        async with self._lock:
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass
                finally:
                    self.browser = None
            if self.playwright:
                try:
                    await self.playwright.stop()
                except Exception:
                    pass
                finally:
                    self.playwright = None
                    self.user_agent = None

    @staticmethod
    def normalize_user_agent(user_agent: str) -> str:
        '''將 HeadlessChrome 轉為正規 Chrome User-Agent。'''
        return user_agent.replace('HeadlessChrome/', 'Chrome/')

    def get_ocr(self):
        '''取得單例 ddddocr 實例。'''
        if self._ocr is None:
            import ddddocr

            self._ocr = ddddocr.DdddOcr(show_ad=False)
        return self._ocr


browser_manager = BrowserManager()
