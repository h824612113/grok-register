#!/usr/bin/env python3
"""
快速 Grok 注册脚本 - 最简化流程
"""
import sys, time, os, json, re, imaplib, urllib.request
from pathlib import Path
from datetime import datetime

LOG = "/tmp/grok_quick.log"
Path(LOG).write_text("")
def log(msg):
    with open(LOG, "a", buffering=1) as f:
        f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    print(msg, flush=True)

# ── 配置 ──
_conf = json.loads((Path(__file__).parent / "config.json").read_text())
EMAIL_DOMAIN = _conf.get("cf_email_domain", "dadukou168.ac.cn")
IMAP_SERVER = _conf.get("imap_server", "imap.qq.com")
IMAP_PORT = int(_conf.get("imap_port", 993))
IMAP_USER = _conf.get("imap_user", "824612113@qq.com")
IMAP_PASSWORD = _conf.get("imap_password", "")
GROK2API_URL = _conf.get("grok2api_url", "http://127.0.0.1:8000")
GROK2API_KEY = _conf.get("grok2api_app_key", "9a7b283337e5a9c800b6b5a9ae81b7ac")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
SSO_DIR = Path(__file__).parent / "sso"
SSO_DIR.mkdir(exist_ok=True)
COUNTER = Path(__file__).parent / ".cf_email_counter"

def next_email():
    n = 1
    if COUNTER.exists():
        try: n = int(COUNTER.read_text().strip()) + 1
        except: pass
    COUNTER.write_text(str(n))
    return f"grok{n:03d}@{EMAIL_DOMAIN}"

def imap_connect():
    c = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    c.login(IMAP_USER, IMAP_PASSWORD)
    return c

def get_code(target_email, timeout=120):
    """等待验证码"""
    start = time.time()
    seen = set()
    local = target_email.split("@")[0]
    log(f"等待验证码 ({target_email})...")
    while time.time() - start < timeout:
        try:
            c = imap_connect()
            c.select("INBOX")
            st, d = c.search(None, '(FROM "noreply@x.ai")')
            if st != "OK" or not d[0]:
                c.logout(); time.sleep(5); continue
            for uid in d[0].split()[-5:]:
                uid_s = uid.decode()
                if uid_s in seen: continue
                seen.add(uid_s)
                st2, h = c.fetch(uid, '(BODY[HEADER.FIELDS (TO)])')
                if st2 != "OK": continue
                hdr = h[0][1].decode(errors="ignore")
                if local not in hdr: continue
                st3, b = c.fetch(uid, "(BODY[TEXT])")
                if st3 != "OK": continue
                body = b[0][1].decode(errors="ignore")
                m = re.search(r'([A-Z0-9]{3}-[A-Z0-9]{3})', body)
                if m:
                    code = m.group(1).replace("-", "")
                    log(f"验证码: {code}")
                    c.logout(); return code
            c.logout()
        except Exception as e:
            log(f"IMAP error: {e}")
        time.sleep(5)
    return None

def find_page(browser):
    """找到 x.ai 标签页"""
    for tid in browser.tab_ids:
        try:
            t = browser.get_tab(tid)
            if "x.ai" in t.url: return t
        except: pass
    return browser.latest_tab

def js_click(page, text):
    """用 JS 点击包含指定文本的按钮"""
    return page.run_js(f"""
const btns = document.querySelectorAll('button');
for (const b of btns) {{
    if (b.innerText && b.innerText.includes('{text}') && b.offsetParent !== null) {{
        b.click(); return 'clicked';
    }}
}}
return 'not-found';
    """)

def js_input(page, selector, value):
    """用 JS 设置 input 值"""
    return page.run_js(f"""
const inp = document.querySelector('{selector}');
if (inp) {{
    inp.focus();
    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
    if (setter) setter.call(inp, '{value}');
    else inp.value = '{value}';
    inp.dispatchEvent(new Event('input', {{bubbles:true}}));
    inp.dispatchEvent(new Event('change', {{bubbles:true}}));
    return 'set';
}}
return 'not-found';
    """)

def import_sso(sso, email):
    """导入 grok2api"""
    payload = json.dumps({"app_key": GROK2API_KEY, "ssoid": sso, "note": email}).encode()
    req = urllib.request.Request(f"{GROK2API_URL}/admin/api/tokens", data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        r = urllib.request.urlopen(req)
        log(f"grok2api: {json.loads(r.read())}")
        return True
    except Exception as e:
        log(f"grok2api error: {e}")
        return False

def main():
    from DrissionPage import ChromiumOptions, Chromium

    email = next_email()
    log(f"邮箱: {email}")

    co = ChromiumOptions()
    co.set_browser_path(CHROME)
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--headless=new")
    # 不加载 Turnstile 扩展，避免页面跳转问题
    # PLUGIN = str(Path(__file__).parent / "turnstilePatch")
    # co.set_argument("--load-extension", PLUGIN)

    log("启动 Chrome...")
    browser = Chromium(co)
    page = browser.latest_tab

    # 1) 打开注册页
    log("打开注册页...")
    page.get("https://accounts.x.ai/sign-up")
    time.sleep(10)
    log(f"URL: {page.url}")

    # 2) 点击 Continue with Email
    log("点击 Continue with Email...")
    js_click(page, "Continue with Email")
    time.sleep(3)
    page = find_page(browser)
    log(f"URL: {page.url}")

    # 3) 输入邮箱
    log("输入邮箱...")
    js_input(page, 'input[name="email"], input[type="email"]', email)
    time.sleep(1)

    # 4) 提交
    log("提交邮箱...")
    js_click(page, "Continue")
    time.sleep(8)
    page = find_page(browser)
    log(f"URL: {page.url}")

    # 截图看看
    page.get_screenshot("/tmp/grok_after_submit.png")
    log("截图: /tmp/grok_after_submit.png")

    # 5) 等验证码
    code = get_code(email)
    if not code:
        log("未收到验证码")
        return False

    # 6) 重新定位页面
    page = find_page(browser)
    log(f"验证码页 URL: {page.url}")

    # 7) 输入验证码
    log(f"输入验证码: {code}")
    # 尝试单个输入框
    r = js_input(page, 'input[name="code"], input[autocomplete="one-time-code"], input[maxlength="7"]', code)
    log(f"验证码输入: {r}")
    time.sleep(1)

    # 8) 点击确认
    log("点击确认...")
    js_click(page, "Confirm")
    js_click(page, "Verify")
    js_click(page, "Continue")
    time.sleep(5)
    page = find_page(browser)
    log(f"URL: {page.url}")

    # 9) 填写注册信息
    log("填写注册信息...")
    time.sleep(3)
    page = find_page(browser)
    log(f"URL: {page.url}")

    js_input(page, 'input[name="given_name"]', "Test")
    js_input(page, 'input[name="family_name"]', "User")
    js_input(page, 'input[name="password"]', "Test@123456")
    time.sleep(1)

    # 10) 完成注册
    log("完成注册...")
    js_click(page, "Sign up")
    js_click(page, "Create Account")
    js_click(page, "完成注册")
    time.sleep(10)
    page = find_page(browser)
    log(f"URL: {page.url}")

    # 11) 获取 SSO
    log("获取 SSO...")
    sso = None
    for _ in range(30):
        try:
            cookies = page.cookies(all_domains=True, all_info=True)
            for c in cookies:
                name = c.get("name", "") if isinstance(c, dict) else getattr(c, "name", "")
                val = c.get("value", "") if isinstance(c, dict) else getattr(c, "value", "")
                if name in ("sso", "sso_session", "_sso"):
                    sso = val
                    log(f"SSO: {name}")
                    break
            if sso: break
        except: pass
        time.sleep(1)

    if not sso:
        log("未找到 SSO")
        page.get_screenshot("/tmp/grok_no_sso.png")
        return False

    sf = SSO_DIR / f"sso_{datetime.now():%Y%m%d_%H%M%S}.txt"
    sf.write_text(sso)
    log(f"SSO saved: {sf}")

    # 12) 导入
    if import_sso(sso, email):
        log("✅ 完成!")
    else:
        log("⚠️ 注册成功，导入失败")

    return True

if __name__ == "__main__":
    main()
