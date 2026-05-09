#!/usr/bin/env python3
"""
快速注册 - 带 Turnstile 扩展 + 稳健页面追踪
"""
import sys, time, os, json, re, imaplib, urllib.request
from pathlib import Path
from datetime import datetime

LOG = "/tmp/grok_fast.log"
Path(LOG).write_text("")
def log(msg):
    with open(LOG, "a", buffering=1) as f:
        f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    print(msg, flush=True)

_conf = json.loads((Path(__file__).parent / "config.json").read_text())
EMAIL_DOMAIN = _conf.get("cf_email_domain", "dadukou168.ac.cn")
IMAP_SERVER = _conf.get("imap_server", "imap.qq.com")
IMAP_PORT = int(_conf.get("imap_port", 993))
IMAP_USER = _conf.get("imap_user", "824612113@qq.com")
IMAP_PASSWORD = _conf.get("imap_password", "")
GROK2API_URL = _conf.get("grok2api_url", "http://127.0.0.1:8000")
GROK2API_KEY = _conf.get("grok2api_app_key", "9a7b283337e5a9c800b6b5a9ae81b7ac")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PLUGIN = str(Path(__file__).parent / "turnstilePatch")
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

def find_xai_page(browser):
    """找到 x.ai 标签页，优先返回不是 new-tab-page 的"""
    best = None
    for tid in browser.tab_ids:
        try:
            t = browser.get_tab(tid)
            url = t.url
            if "accounts.x.ai" in url:
                return t
            if "x.ai" in url:
                best = t
        except: pass
    return best or browser.latest_tab

def js_click(page, text):
    return page.run_js(f"""
const btns = document.querySelectorAll('button');
for (const b of btns) {{
    const t = (b.innerText||'').trim();
    if (t.includes('{text}') && b.offsetParent !== null) {{
        b.click(); return t;
    }}
}}
return 'not-found';
    """)

def js_set(page, selector, value):
    escaped = value.replace("'", "\\'")
    return page.run_js(f"""
const inp = document.querySelector('{selector}');
if (!inp) return 'not-found';
inp.focus();
const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value')?.set;
if (setter) setter.call(inp,'{escaped}');
else inp.value='{escaped}';
inp.dispatchEvent(new Event('input',{{bubbles:true}}));
inp.dispatchEvent(new Event('change',{{bubbles:true}}));
return 'set';
    """)

def import_sso(sso, email):
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
    co.set_argument("--disable-extensions-except", PLUGIN)
    co.set_argument("--load-extension", PLUGIN)
    co.set_argument("--headless=new")

    log("启动 Chrome...")
    browser = Chromium(co)
    page = browser.latest_tab

    # 1) 注册页
    log("打开注册页...")
    page.get("https://accounts.x.ai/sign-up")
    time.sleep(10)
    log(f"URL: {page.url}")

    # 2) Continue with Email
    log("点击 Continue with Email...")
    time.sleep(3)
    r = js_click(page, "Continue with Email")
    log(f"按钮: {r}")
    time.sleep(5)
    page = find_xai_page(browser)
    log(f"URL: {page.url}")

    # 3) 输入邮箱
    log(f"输入邮箱: {email}")
    r = js_set(page, 'input[name="email"],input[type="email"]', email)
    log(f"邮箱输入: {r}")
    time.sleep(1)

    # 4) 提交
    log("提交...")
    js_click(page, "Continue")
    time.sleep(10)  # 等待 Turnstile 处理
    page = find_xai_page(browser)
    log(f"提交后 URL: {page.url}")
    page.get_screenshot("/tmp/grok_fast_after_submit.png")

    # 列出所有标签页
    for tid in browser.tab_ids:
        try:
            t = browser.get_tab(tid)
            log(f"  tab: {t.url}")
        except: pass

    # 5) 等验证码
    code = get_code(email)
    if not code:
        log("未收到验证码")
        return False

    # 6) 定位页面
    page = find_xai_page(browser)
    log(f"验证码页: {page.url}")

    # 7) 输入验证码
    log(f"输入: {code}")
    r = js_set(page, 'input[name="code"],input[autocomplete="one-time-code"],input[maxlength="7"]', code)
    log(f"输入结果: {r}")
    time.sleep(2)

    # 8) 确认
    log("确认...")
    js_click(page, "Confirm")
    js_click(page, "Verify")
    js_click(page, "Continue")
    time.sleep(8)
    page = find_xai_page(browser)
    log(f"确认后: {page.url}")

    # 9) 注册信息
    log("填写注册信息...")
    time.sleep(5)
    page = find_xai_page(browser)
    log(f"URL: {page.url}")

    js_set(page, 'input[name="given_name"]', "Test")
    js_set(page, 'input[name="family_name"]', "User")
    js_set(page, 'input[name="password"]', "Test@123456")
    time.sleep(1)

    # 10) 完成
    log("完成注册...")
    js_click(page, "Sign up")
    js_click(page, "Create Account")
    js_click(page, "完成注册")
    time.sleep(15)
    page = find_xai_page(browser)
    log(f"完成: {page.url}")

    # 11) SSO
    log("获取 SSO...")
    sso = None
    for _ in range(60):
        try:
            cookies = page.cookies(all_domains=True, all_info=True)
            for c in cookies:
                name = c.get("name","") if isinstance(c,dict) else getattr(c,"name","")
                val = c.get("value","") if isinstance(c,dict) else getattr(c,"value","")
                if name in ("sso","sso_session","_sso"):
                    sso = val; log(f"SSO: {name}"); break
            if sso: break
        except: pass
        time.sleep(1)

    if not sso:
        log("未找到 SSO")
        page.get_screenshot("/tmp/grok_fast_no_sso.png")
        return False

    sf = SSO_DIR / f"sso_{datetime.now():%Y%m%d_%H%M%S}.txt"
    sf.write_text(sso)
    log(f"SSO: {sf}")

    if import_sso(sso, email):
        log("✅ 完成!")
    else:
        log("⚠️ 导入失败")
    return True

if __name__ == "__main__":
    main()
