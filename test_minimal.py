#!/usr/bin/env python3
"""最小测试 - 检查 DrissionPage 是否能打开 Grok 注册页"""
import sys, time, os
from pathlib import Path

# 文件日志
LOG = "/tmp/grok_minimal.log"
def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")

log("=== START ===")

# 导入
try:
    from DrissionPage import ChromiumOptions, Chromium
    log("OK: DrissionPage imported")
except Exception as e:
    log(f"FAIL: import {e}")
    sys.exit(1)

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PLUGIN_DIR = str(Path(__file__).parent / "turnstilePatch")

# Chrome 配置
co = ChromiumOptions()
co.set_browser_path(CHROME)
co.set_argument("--no-first-run")
co.set_argument("--no-default-browser-check")
co.set_argument("--disable-extensions-except", PLUGIN_DIR)
co.set_argument("--load-extension", PLUGIN_DIR)
co.set_argument("--headless=new")

log("Launching Chrome...")
try:
    browser = Chromium(co)
    log("OK: Chrome launched")
except Exception as e:
    log(f"FAIL: launch {e}")
    sys.exit(1)

# 打开注册页
log("Opening signup page...")
try:
    page = browser.latest_tab
    page.get("https://accounts.x.ai/sign-up")
    time.sleep(10)
    log(f"URL: {page.url}")
    log(f"title: {page.title}")
except Exception as e:
    log(f"FAIL: navigate {e}")
    sys.exit(1)

# 截图
page.get_screenshot("/tmp/grok_minimal.png")
log("Screenshot: /tmp/grok_minimal.png")

# 列出按钮
try:
    buttons = page.eles("tag:button")
    for b in buttons:
        if b.states.is_displayed:
            log(f"button: '{b.text}'")
except Exception as e:
    log(f"FAIL: buttons {e}")

log("=== DONE ===")
