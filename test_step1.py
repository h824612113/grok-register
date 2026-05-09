#!/usr/bin/env python3
"""极简测试：打开 Grok 注册页，点击 Continue with Email"""
import sys, time, os
from pathlib import Path

# 写日志
LOG = "/tmp/grok_test.log"
def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== TEST START ===")
log(f"cwd={os.getcwd()}")

# 导入
try:
    from DrissionPage import ChromiumOptions, Chromium
    log("DrissionPage imported OK")
except Exception as e:
    log(f"DrissionPage import FAILED: {e}")
    sys.exit(1)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PLUGIN_DIR = str(Path(__file__).parent / "turnstilePatch")
SIGNUP_URL = "https://accounts.x.ai/sign-up"

# 1) Chrome 配置
log("Configuring Chrome...")
co = ChromiumOptions()
co.set_browser_path(CHROME)
co.set_argument("--no-first-run")
co.set_argument("--no-default-browser-check")
co.set_argument("--disable-extensions-except", PLUGIN_DIR)
co.set_argument("--load-extension", PLUGIN_DIR)
co.set_argument("--remote-debugging-port=9222")
co.set_argument("--headless=new")
co.set_argument("--disable-gpu")

# 2) 启动浏览器
log("Launching Chrome...")
try:
    browser = Chromium(co)
    log("Chrome launched OK")
except Exception as e:
    log(f"Chrome launch FAILED: {e}")
    sys.exit(1)

# 3) 打开注册页
log(f"Navigating to {SIGNUP_URL}...")
try:
    page = browser.latest_tab
    page.get(SIGNUP_URL)
    log("page.get() called, waiting...")
    time.sleep(8)
    log(f"Current URL: {page.url}")
except Exception as e:
    log(f"Navigation FAILED: {e}")
    sys.exit(1)

# 4) 截图
try:
    path = "/tmp/grok_step1.png"
    page.get_screenshot(path)
    log(f"Screenshot saved: {path}")
except Exception as e:
    log(f"Screenshot FAILED: {e}")

# 5) 找 "Continue with Email" 按钮
log("Looking for email button...")
try:
    time.sleep(3)
    page.wait.eles_loaded("tag:button", timeout=15)
    log("Buttons loaded")
except Exception as e:
    log(f"wait.eles_loaded FAILED: {e}")

# 尝试多种方式找按钮
for sel in [
    "Continue with Email",
    "@@tag()button@@text()Continue with Email",
    "xpath://button[contains(text(),'Continue with Email')]",
    "xpath://button[contains(.,'Continue with Email')]",
]:
    try:
        btn = page(sel)
        if btn and btn.states.is_displayed:
            log(f"Found button via: {sel}")
            break
    except:
        pass
else:
    btn = None
    log("Button NOT found by any selector")

if btn:
    log("Clicking email button...")
    try:
        btn.click()
        time.sleep(3)
        log(f"After click, URL: {page.url}")
        page.get_screenshot("/tmp/grok_step2.png")
        log("Step2 screenshot saved")
    except Exception as e:
        log(f"Click FAILED: {e}")
else:
    log("Cannot click - button not found")
    # 列出所有按钮
    try:
        all_btns = page.eles("tag:button")
        for i, b in enumerate(all_btns):
            log(f"  button[{i}]: text='{b.text}' visible={b.states.is_displayed}")
    except Exception as e:
        log(f"List buttons FAILED: {e}")

log("=== TEST DONE ===")
