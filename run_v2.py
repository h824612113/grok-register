#!/usr/bin/env python3
"""
Grok 自动注册 v2 - 更稳健的页面跟踪
- 修复页面跳转后丢失的问题
- 自动重新定位正确的标签页
"""
import sys, time, os, json, re, imaplib, hashlib, secrets, random, string
from pathlib import Path
from datetime import datetime

# ── 文件日志 ──────────────────────────────────────────────
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / f"run_{datetime.now():%Y%m%d_%H%M%S}.log"

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
    """从邮件内容提取验证码 XXX-XXX 格式"""
    m = re.search(r'([A-Z0-9]{3}-[A-Z0-9]{3})', content)
    if m:
        return m.group(1)
    m = re.search(r'(?<![&#\d])(\d{6})(?![&#\d])', content)
    if m and m.group(1) != "177010":
        return m.group(1)
    return None

def wait_for_code(target_email, timeout=120):
    """轮询 QQ邮箱，等待发往 target_email 的验证码邮件"""
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
def find_grok_tab(browser):
    """找到包含 x.ai 的标签页"""
    for tab in browser.tab_ids:
        try:
            t = browser.get_tab(tab)
            url = t.url
            if "x.ai" in url or "accounts.x.ai" in url:
                return t
        except:
            pass
    return None

def get_active_page(browser):
    """获取活跃的 Grok 页面，如果丢失则重新定位"""
    page = find_grok_tab(browser)
    if page:
        return page
    # 如果找不到，返回最新标签页
    return browser.latest_tab

# ── 主注册流程 ────────────────────────────────────────────
def main():
    from DrissionPage import ChromiumOptions, Chromium

    email = next_email()
    log(f"注册邮箱: {email}")

    # Chrome 配置
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

    # 打开注册页
    log(f"打开注册页: {SIGNUP_URL}")
    page = browser.latest_tab
    page.get(SIGNUP_URL)
    time.sleep(10)
    log(f"当前 URL: {page.url}")

    # 点击 "Continue with Email"
    log("查找 Continue with Email 按钮...")
    time.sleep(3)
    btn = None
    for sel in [
        "@@tag()button@@text()Continue with Email",
        "xpath://button[contains(text(),'Continue with Email')]",
        "xpath://button[contains(.,'Continue with Email')]",
    ]:
        try:
            btn = page(sel)
            if btn and btn.states.is_displayed:
                log(f"找到按钮: {sel}")
                break
        except:
            btn = None

    if not btn:
        log("按钮未找到，尝试 JS 方式...")
        try:
            result = page.run_js("""
const buttons = document.querySelectorAll('button');
for (const b of buttons) {
    if (b.innerText && b.innerText.includes('Continue with Email')) {
        b.click();
        return 'clicked';
    }
}
return 'not-found';
            """)
            log(f"JS 点击结果: {result}")
        except Exception as e:
            log(f"JS 点击失败: {e}")
    else:
        log("点击 Continue with Email...")
        btn.click()

    time.sleep(3)
    page = get_active_page(browser)  # 重新定位页面
    log(f"点击后 URL: {page.url}")

    # 输入邮箱
    log("查找邮箱输入框...")
    email_input = None
    for sel in [
        "@name=email",
        "@type=email",
        "@placeholder=Email",
        "@autocomplete=email",
    ]:
        try:
            email_input = page(sel)
            if email_input:
                log(f"找到邮箱输入框: {sel}")
                break
        except:
            pass

    if not email_input:
        log("邮箱输入框未找到，尝试 JS...")
        try:
            result = page.run_js("""
const inputs = document.querySelectorAll('input');
for (const inp of inputs) {
    if (inp.type === 'email' || inp.name === 'email' || 
        inp.placeholder?.toLowerCase().includes('email') ||
        inp.autocomplete === 'email') {
        inp.focus();
        return { found: true, type: inp.type, name: inp.name };
    }
}
return { found: false, allInputs: Array.from(inputs).map(i => ({type:i.type, name:i.name})) };
            """)
            log(f"JS 查找结果: {result}")
            if result and result.get('found'):
                email_input = page("@name=email") or page("@type=email")
        except Exception as e:
            log(f"JS 查找失败: {e}")
    else:
        log(f"输入邮箱: {email}")
        email_input.clear()
        email_input.input(email)
        time.sleep(1)

        # 点击提交按钮
        log("查找提交按钮...")
        submit = None
        for sel in [
            "@@tag()button@@text()Continue",
            "@@tag()button@@text()Submit",
            "@@tag()button@@text()Next",
            "xpath://button[@type='submit']",
        ]:
            try:
                submit = page(sel)
                if submit and submit.states.is_displayed:
                    log(f"找到提交按钮: {sel}")
                    break
            except:
                submit = None

        if not submit:
            log("提交按钮未找到，尝试 JS...")
            try:
                page.run_js("""
const btn = document.querySelector('button[type="submit"]') || 
            Array.from(document.querySelectorAll('button')).find(b => 
                ['Continue','Submit','Next','Send'].some(t => b.innerText?.includes(t)));
if (btn) btn.click();
                """)
                log("JS 提交成功")
            except Exception as e:
                log(f"JS 提交失败: {e}")
        else:
            log("点击提交...")
            submit.click()

    # 处理 Turnstile
    log("检查 Turnstile...")
    time.sleep(5)
    page = get_active_page(browser)  # 重新定位页面
    try:
        turnstile = page.ele("@name=cf-turnstile-response")
        if turnstile and not turnstile.value:
            log("检测到 Turnstile，等待解决...")
            time.sleep(10)
    except:
        pass

    # 等待验证码
    code = wait_for_code(email, timeout=120)
    if not code:
        log("未收到验证码，注册失败")
        page.get_screenshot("/tmp/grok_no_code.png")
        return False

    log(f"收到验证码: {code}")

    # 重新定位页面（关键！）
    page = get_active_page(browser)
    log(f"验证码页 URL: {page.url}")

    # 如果页面不在 x.ai，尝试找回
    if "x.ai" not in page.url:
        log("页面丢失，尝试找回...")
        for tab_id in browser.tab_ids:
            try:
                t = browser.get_tab(tab_id)
                if "x.ai" in t.url:
                    page = t
                    log(f"找到页面: {page.url}")
                    break
            except:
                pass

    log(f"当前页面: {page.url}")

    # 输入验证码
    log("输入验证码...")
    code_input = None
    for sel in [
        "@name=code",
        "@type=text",
        "@autocomplete=one-time-code",
        "@placeholder=Verification code",
        "xpath://input[@maxlength='7']",
        "xpath://input[contains(@placeholder,'code')]",
    ]:
        try:
            code_input = page(sel)
            if code_input:
                log(f"找到验证码输入框: {sel}")
                break
        except:
            pass

    if not code_input:
        log("验证码输入框未找到，尝试 JS...")
        try:
            result = page.run_js(f"""
const inputs = document.querySelectorAll('input');
let found = null;
for (const inp of inputs) {{
    if (inp.type === 'text' || inp.type === 'number' || inp.type === 'tel') {{
        if (!found || inp.maxLength === 7) {{
            found = inp;
        }}
    }}
}}
if (found) {{
    found.value = '{code}';
    found.dispatchEvent(new Event('input', {{bubbles: true}}));
    return 'set';
}} else {{
    return 'not-found';
}}
            """)
            log(f"JS 输入结果: {result}")
        except Exception as e:
            log(f"JS 输入失败: {e}")
    else:
        code_input.clear()
        code_input.input(code)
        time.sleep(1)

    # 确认邮箱
    log("查找确认邮箱按钮...")
    confirm = None
    for sel in [
        "@@tag()button@@text()Confirm Email",
        "@@tag()button@@text()Verify",
        "@@tag()button@@text()Continue",
        "xpath://button[@type='submit']",
    ]:
        try:
            confirm = page(sel)
            if confirm and confirm.states.is_displayed:
                log(f"找到确认按钮: {sel}")
                break
        except:
            pass

    if not confirm:
        log("确认按钮未找到，尝试 JS...")
        try:
            result = page.run_js("""
const btn = document.querySelector('button[type="submit"]') ||
            Array.from(document.querySelectorAll('button')).find(b =>
                ['Confirm','Verify','Continue'].some(t => b.innerText?.includes(t)));
if (btn) {
    btn.click();
    return 'clicked';
} else {
    return 'not-found';
}
            """)
            log(f"JS 点击结果: {result}")
        except Exception as e:
            log(f"JS 点击失败: {e}")
    else:
        log("点击确认...")
        confirm.click()

    # 处理 Turnstile (最终注册页)
    log("检查最终注册页 Turnstile...")
    time.sleep(5)
    page = get_active_page(browser)
    try:
        turnstile = page.ele("@name=cf-turnstile-response")
        if turnstile and not turnstile.value:
            log("检测到 Turnstile，等待解决...")
            time.sleep(10)
    except:
        pass

    # 等待注册完成
    log("等待注册完成...")
    time.sleep(30)
    page = get_active_page(browser)
    log(f"注册后 URL: {page.url}")

    # 获取 SSO token
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

    # 保存 SSO
    sso_file = SSO_DIR / f"sso_{datetime.now():%Y%m%d_%H%M%S}.txt"
    sso_file.write_text(sso_token)
    log(f"SSO 已保存: {sso_file}")

    # 导入 grok2api
    log("导入 grok2api...")
    if import_to_grok2api(sso_token, email):
        log("✅ 注册成功并已导入 grok2api!")
    else:
        log("⚠️ 注册成功但导入失败")

    log("=== 注册完成 ===")
    return True

if __name__ == "__main__":
    main()
