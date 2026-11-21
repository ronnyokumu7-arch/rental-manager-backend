import asyncio
import os
import logging

from pyppeteer import launch

logger = logging.getLogger(__name__)

# ✅ Prefer the system Chromium installed by the Dockerfile.
SYSTEM_CHROMIUM_PATHS = [
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
]

def _find_system_chromium():
    for path in SYSTEM_CHROMIUM_PATHS:
        if os.path.exists(path):
            return path
    return None

class BrowserPool:
    def __init__(self):
        self.browser = None
        self.lock = asyncio.Lock()

    async def get_browser(self, force_restart: bool = False):
        async with self.lock:
            # 1. Check if existing browser is actually connected
            if self.browser is not None and not force_restart:
                # Pyppeteer stores connection state in _connection._connected
                is_connected = getattr(
                    getattr(self.browser, '_connection', None), 
                    '_connected', 
                    False
                )
                if not is_connected:
                    logger.warning("⚠️ Browser CDP connection lost, restarting...")
                    await self._close_browser()

            # 2. Launch fresh browser if needed
            if self.browser is None or force_restart:
                logger.info("🚀 Launching Headless Chrome (Singleton)...")

                launch_kwargs = {
                    "headless": True,
                    "args": [
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-accelerated-2d-canvas",
                        "--no-first-run",
                        "--no-zygote",
                        "--disable-gpu",
                        # ❌ REMOVED: "--single-process" (causes CDP drops on Render)
                    ],
                }

                executable = _find_system_chromium()
                if executable:
                    logger.info(f"✅ Using system Chromium at {executable}")
                    launch_kwargs["executablePath"] = executable

                try:
                    self.browser = await launch(**launch_kwargs)
                except Exception as e:
                    logger.error(f"❌ Failed to launch browser: {e}")
                    self.browser = None
                    raise

            return self.browser

    async def _close_browser(self):
        if self.browser:
            try:
                await self.browser.close()
            except Exception:
                pass
            self.browser = None

    async def close(self):
        await self._close_browser()
        logger.info("✅ Headless Chrome closed gracefully.")

# Global instance
browser_pool = BrowserPool()
