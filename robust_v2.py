#!/usr/bin/env python3
"""
可靠的 Grok 自动注册 v2
- 正确追踪标签页，避免丢失
- Cloudflare 域名邮箱 + QQ邮箱 IMAP
- 自动导入 grok2api
"""
import sys, time, os, json, re, imaplib
from pathlib import Path
from datetime import datetime

# ── 文件日志 ──────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"
LOG_FILE.write_text("")

def log(msg):
    with open(LOG_FILE, "a", buffering=1) as f:
        f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    sys.stdout.write(f"{msg}\n")
    sys.stdout.flush()

log(f"Log file: {LOG_FILE}")

# ── 配置 ──────────────────────────────────────────────────
_config_path = Path(__file__).parent / "config.json"
_conf = {}
if _config_path.exists():
    with _config_path.open("r", encoding="utf-8") as f:
        _conf = json.load(f)

EMAIL_DOMAIN = _conf.get("cf_email_domain", "dadukou168.ac.cn")
EMAIL_PREFIX = _conf.get("cf_email_prefix", "grok")
IMAP_SERVER = _conf.get("imap_server", "imap.qq.com")
IMAP_PORT = int(_conf.get("imap_port", 993))
IMAP_USER = _conf.get("imap_user", "824612113@qq.com")
IMAP_PASSWORD = _conf.get("imap_password", "")
GROK2API_URL = _conf.get("grok2api_url", "http://127.0.0.1:8000")
GROK2API_KEY = _conf.get("grok2api_app_key", "9a7b283337e5a9c800b6b5a9ae81b7ac")

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PLUGIN_DIR = str(Path(__file__).parent / "turnstilePatch")
SIGNUP_URL = "https://accounts.x.ai/sign-up"
SSO_DIR = Path(__file__).parent / "sso"
SSO_DIR.mkdir(exist_ok=True)

# ── 邮箱计数 ──────────────────────────────────────────────
_counter_file = Path(__file__).parent / ".cf_email_counter"

def next_email():
    n = 1
    if _counter_file.exists():
        try:
            n = int(_counter_file.read_text().strip()) + 1
        except:
            n = 1
    _counter_file.write_text(str(n))
    return f"{EMAIL_PREFIX}{n:03d}@{EMAIL_DOMAIN}"

# ── IMAP 接收验证码 ──────────────────────────────────────
def imap_connect():
    conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
    conn.login(IMAP_USER, IMAP_PASSWORD)
    return conn

def extract_code(content):
    m = re.search(r'([A-Z0-9]{3}-[A-Z0-9]{3})', content)
    if m:
        return m.group(1)
    m = re.search(r'(?<![&#\d])(\d{6})(?![&#\d])', content)
    if m and m.group(1) != "177010":
        return m.group(1)
    return None

def wait_for_code(target_email, timeout=120):
    start = time.time()
    seen = set()
    local = target_email.split("@")[0]
    log(f"等待验证码邮件 ({target_email})...")

    while time.time() - start < timeout:
        try:
            conn = imap_connect()
            conn.select("INBOX")
            status, data = conn.search(None, '(FROM "noreply@x.ai")')
            if status != "OK" or not data[0]:
                conn.logout()
                time.sleep(5)
                continue

            for uid in data[0].split()[-5:]:
                uid_str = uid.decode()
                if uid_str in seen:
                    continue
                seen.add(uid_str)

                st, hd = conn.fetch(uid, '(BODY[HEADER.FIELDS (TO)])')
                if st == "OK" and hd[0]:
                    header = hd[0][1].decode(errors="ignore")
                    if local not in header:
                        continue

                st, bd = conn.fetch(uid, '(BODY[TEXT])')
                if st == "OK" and bd[0]:
                    body = bd[0][1].decode(errors="ignore")
                    code = extract_code(body)
                    if code:
                        log(f"收到验证码: {code}")
                        conn.logout()
                        return code
            conn.logout()
        except Exception as e:
            log(f"IMAP 错误: {e}")
        time.sleep(5)
    return None

# ── 导入 grok2api ────────────────────────────────────────
def import_to_grok2api(sso_token, email):
    import urllib.request
    url = f"{GROK2API_URL}/admin/api/tokens"
    payload = json.dumps({
        "app_key": GROK2API_KEY,
        "ssoid": sso_token,
        "note": email,
    }).encode()
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        log(f"grok2api 导入成功: {result}")
        return True
    except Exception as e:
        log(f"grok2api 导入失败: {e}")
        return False

# ── 页面辅助函数 ─────────────────────────────────────────
def get_grok_page(browser):
    """找到包含 x.ai 的标签页"""
    for tab_id in browser.tab_ids:
        try:
            t = browser.get_tab(tab_id)
            if "x.ai" in t.url:
                return t
        except:
            pass
    return browser.latest_tab

# ── 主注册流程 ────────────────────────────────────────────
def main():
    from DrissionPage import ChromiumOptions, Chromium

    email = next_email()
    log(f"注册邮箱: {email}")

    co = ChromiumOptions()
    co.set_browser_path(CHROME)
    co.set_argument("--no-first-run")
    co.set_argument("--no-default-browser-check")
    co.set_argument("--disable-extensions-except", PLUGIN_DIR)
    co.set_argument("--load-extension", PLUGIN_DIR)
    co.set_argument("--headless=new")

    log("启动 Chrome...")
    browser = Chromium(co)
    log("Chrome 已启动")

    log(f"打开注册页: {SIGNUP_URL}")
    page = browser.latest_tab
    page.get(SIGNUP_URL)
    time.sleep(10)
    log(f"当前 URL: {page.url}")

    # ── 步骤 1: 点击 Continue with Email ──
    log("查找 Continue with Email 按钮...")
    time.sleep(3)
    btn = None
    for sel in ["@@tag()button@@text()Continue with Email", "xpath://button[contains(.,'Continue with Email')]"]:
        try:
            btn = page(sel)
            if btn and btn.states.is_displayed:
                log(f"找到按钮: {sel}")
                break
        except:
            btn = None

    if btn:
        log("点击 Continue with Email...")
        btn.click()
    else:
        log("按钮未找到，尝试 JS...")
        page.run_js("document.querySelectorAll('button').forEach(b => { if(b.innerText?.includes('Continue with Email')) b.click(); })")

    time.sleep(3)
    page = get_grok_page(browser)  # 重新获取页面
    log(f"点击后 URL: {page.url}")

    # ── 步骤 2: 输入邮箱 ──
    log("输入邮箱...")
    email_input = page("@name=email") or page("@type=email")
    if email_input:
        email_input.clear()
        email_input.input(email)
        time.sleep(1)
    else:
        log("邮箱输入框未找到，尝试 JS...")
        page.run_js(f"document.querySelector('input[name=email],input[type=email]').value='{email}'")

    # ── 步骤 3: 提交邮箱 ──
    log("查找提交按钮...")
    submit = None
    for sel in ["@@tag()button@@text()Continue", "@@tag()button@@text()Submit", "xpath://button[@type='submit']"]:
        try:
            submit = page(sel)
            if submit and submit.states.is_displayed:
                log(f"找到提交按钮: {sel}")
                break
        except:
            submit = None

    if submit:
        log("点击提交...")
        submit.click()
    else:
        log("提交按钮未找到，尝试 JS...")
        page.run_js("document.querySelector('button[type=submit]')?.click()")

    time.sleep(5)
    page = get_grok_page(browser)  # 关键：重新获取页面
    log(f"提交后 URL: {page.url}")

    # ── 步骤 4: 处理 Turnstile ──
    log("检查 Turnstile...")
    try:
        turnstile = page.ele("@name=cf-turnstile-response")
        if turnstile and not turnstile.value:
            log("检测到 Turnstile，等待解决...")
            time.sleep(10)
    except:
        pass

    page = get_grok_page(browser)  # 再次确认页面
    log(f"Turnstile 后 URL: {page.url}")

    # ── 步骤 5: 等待验证码 ──
    code = wait_for_code(email, timeout=120)
    if not code:
        log("未收到验证码，注册失败")
        return False

    log(f"收到验证码: {code}")

    # 关键：重新定位页面
    page = get_grok_page(browser)
    log(f"验证码页 URL: {page.url}")

    # ── 步骤 6: 输入验证码 ──
    log("输入验证码...")
    code_input = page("@name=code") or page("@autocomplete=one-time-code")
    if code_input:
        code_input.clear()
        code_input.input(code)
        time.sleep(1)
    else:
        log("验证码输入框未找到，尝试 JS...")
        page.run_js(f"document.querySelector('input[name=code],input[autocomplete=one-time-code]')?.value='{code}'")

    # ── 步骤 7: 确认邮箱 ──
    log("查找确认邮箱按钮...")
    confirm = None
    for sel in ["@@tag()button@@text()Confirm Email", "@@tag()button@@text()Verify", "xpath://button[@type='submit']"]:
        try:
            confirm = page(sel)
            if confirm and confirm.states.is_displayed:
                log(f"找到确认按钮: {sel}")
                break
        except:
            pass

    if confirm:
        log("点击确认...")
        confirm.click()
    else:
        log("确认按钮未找到，尝试 JS...")
        page.run_js("document.querySelector('button[type=submit]')?.click()")

    time.sleep(5)
    page = get_grok_page(browser)
    log(f"确认后 URL: {page.url}")

    # ── 步骤 8: 处理最终注册页 Turnstile ──
    log("检查最终注册页 Turnstile...")
    try:
        turnstile = page.ele("@name=cf-turnstile-response")
        if turnstile and not turnstile.value:
            log("检测到 Turnstile，等待解决...")
            time.sleep(10)
    except:
        pass

    # ── 步骤 9: 填写最终注册信息 ──
    log("填写最终注册信息...")
    page = get_grok_page(browser)
    log(f"最终注册页 URL: {page.url}")

    given = "Test"
    family = "User"
    password = "Test@123456"

    # 填写名字
    given_input = page("@name=given_name") or page("@name=firstName")
    if given_input:
        given_input.clear()
        given_input.input(given)
    else:
        log("名字输入框未找到，尝试 JS...")
        page.run_js(f"document.querySelector('input[name=given_name],input[name=firstName]')?.value='{given}'")

    family_input = page("@name=family_name") or page("@name=lastName")
    if family_input:
        family_input.clear()
        family_input.input(family)
    else:
        log("姓氏输入框未找到，尝试 JS...")
        page.run_js(f"document.querySelector('input[name=family_name],input[name=lastName]')?.value='{family}'")

    pwd_input = page("@name=password") or page("@type=password")
    if pwd_input:
        pwd_input.clear()
        pwd_input.input(password)
    else:
        log("密码输入框未找到，尝试 JS...")
        page.run_js(f"document.querySelector('input[name=password],input[type=password]')?.value='{password}'")

    time.sleep(1)

    # ── 步骤 10: 完成注册 ──
    log("查找完成注册按钮...")
    finish = None
    for sel in ["@@tag()button@@text()完成注册", "@@tag()button@@text()Create Account", "@@tag()button@@text()Sign up", "xpath://button[@type='submit']"]:
        try:
            finish = page(sel)
            if finish and finish.states.is_displayed:
                log(f"找到完成按钮: {sel}")
                break
        except:
            pass

    if finish:
        log("点击完成注册...")
        finish.click()
    else:
        log("完成按钮未找到，尝试 JS...")
        page.run_js("document.querySelector('button[type=submit]')?.click()")

    # ── 步骤 11: 等待注册完成 ──
    log("等待注册完成...")
    time.sleep(30)
    page = get_grok_page(browser)
    log(f"注册后 URL: {page.url}")

    # ── 步骤 12: 获取 SSO token ──
    log("获取 SSO token...")
    sso_token = None
    for i in range(60):
        try:
            cookies = page.cookies(all_domains=True, all_info=True)
            for c in cookies:
                if isinstance(c, dict):
                    name = c.get("name", "")
                    value = c.get("value", "")
                else:
                    name = getattr(c, "name", "")
                    value = getattr(c, "value", "")
                if name in ("sso", "sso_session", "_sso"):
                    sso_token = value
                    log(f"找到 SSO cookie: {name}")
                    break
            if sso_token:
                break
        except:
            pass
        time.sleep(1)

    if not sso_token:
        log("未找到 SSO token")
        page.get_screenshot("/tmp/grok_no_sso.png")
        return False

    # ── 步骤 13: 保存并导入 ──
    sso_file = SSO_DIR / f"sso_{datetime.now():%Y%m%d_%H%M%S}.txt"
    sso_file.write_text(sso_token)
    log(f"SSO 已保存: {sso_file}")

    log("导入 grok2api...")
    if import_to_grok2api(sso_token, email):
        log("✅ 注册成功并已导入 grok2api!")
    else:
        log("⚠️ 注册成功但导入失败")

    log("=== 注册完成 ===")
    return True

if __name__ == "__main__":
    main()
