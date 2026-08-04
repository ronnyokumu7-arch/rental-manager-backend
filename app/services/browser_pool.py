# app/services/browser_pool.py

import asyncio
from pyppeteer import launch

class BrowserPool:
    def __init__(self):
        self.browser = None
        self.lock = asyncio.Lock()

    async def get_browser(self):
        async with self.lock:
            # If browser exists, test if it's still alive
            if self.browser is not None:
                try:
                    # This is a safe way to check if the CDP connection is still active
                    await self.browser.pages()
                except Exception:
                    print("⚠️ Browser connection lost, restarting...")
                    self.browser = None

            # If it's None (or just died), launch a fresh one
            if self.browser is None:
                print("🚀 Launching Headless Chrome (Singleton)...")
                self.browser = await launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--no-zygote',
                        '--disable-gpu',
                        '--single-process'
                    ]
                )
            return self.browser

    async def close(self):
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None
            print("✅ Headless Chrome closed gracefully.")

# Global instance
browser_pool = BrowserPool()
