# app/services/browser_pool.py

import asyncio
import os

from pyppeteer import launch

# ✅ Prefer the system Chromium installed by the Dockerfile.
# Pyppeteer's bundled download lacks the shared libraries on slim images.
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
                        "--single-process",
                    ],
                }

                # ✅ FIXED: Use system Chromium when present — fixes
                # "Browser closed unexpectedly" on Render's slim image.
                executable = _find_system_chromium()
                if executable:
                    print(f"✅ Using system Chromium at {executable}")
                    launch_kwargs["executablePath"] = executable

                self.browser = await launch(**launch_kwargs)
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
