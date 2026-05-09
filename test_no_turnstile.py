#!/usr/bin/env python3
"""不带 Turnstile 扩展的最小测试"""
import sys, time, json
from pathlib import Path
from datetime import datetime

# 文件日志
LOG = "/tmp/grok_test_no_ts.log"
def log(msg):
    with open(LOG, "a") as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    sys.stdout.write(f"{msg}\n")
    sys.stdout.flush()

Path(LOG).write_text("")
log("=== START ===")

from DrissionPage import ChromiumOptions, Chromium

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

# 配置 Chrome - 不加载 Turnstile 扩展
co = ChromiumOptions()
co.set_browser_path(CHROME)
co.set_argument("--no-first-run")
co.set_argument("--no-default-browser-check")
co.set_argument("--headless=new")

log("启动 Chrome (无 Turnstile 扩展)...")
browser = Chromium(co)
log("Chrome 已启动")

# 打开注册页
SIGNUP_URL = "https://accounts.x.ai/sign-up"
log(f"打开: {SIGNUP_URL}")
page = browser.latest_tab
page.get(SIGNUP_URL)
time.sleep(10)
log(f"URL: {page.url}")

# 列出按钮
log("按钮列表:")
buttons = page.eles("tag:button")
for b in buttons:
    try:
        if b.states.is_displayed:
            log(f"  [{b.text}]")
    except:
        pass

# 截图
page.get_screenshot("/tmp/grok_test_no_ts.png")
log("截图: /tmp/grok_test_no_ts.png")

log("=== DONE ===")
