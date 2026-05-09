"""
Cloudflare 域名邮箱注册模块
替代 DuckMail，使用自有域名 + QQ邮箱 IMAP 接收验证码
"""

from __future__ import annotations

import imaplib
import json
import logging
import os
import random
import re
import string
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ============================================================
# 配置
# ============================================================

_config_path = Path(__file__).parent / "config.json"
_conf: Dict[str, Any] = {}
if _config_path.exists():
    with _config_path.open("r", encoding="utf-8") as _f:
        _conf = json.load(_f)

# 域名邮箱配置
EMAIL_DOMAIN = _conf.get("cf_email_domain", "dadukou168.ac.cn")
EMAIL_PREFIX = _conf.get("cf_email_prefix", "grok")

# QQ邮箱 IMAP 配置
IMAP_SERVER = _conf.get("imap_server", "imap.qq.com")
IMAP_PORT = int(_conf.get("imap_port", 993))
IMAP_USER = _conf.get("imap_user", "824612113@qq.com")
IMAP_PASSWORD = _conf.get("imap_password", "")

# ============================================================
# 适配层：为 DrissionPage_example.py 提供简单接口
# ============================================================

_email_counter_file = Path(__file__).parent / ".cf_email_counter"

_temp_email_cache: Dict[str, str] = {}


def _get_next_email() -> str:
    """生成下一个邮箱地址，格式: grok001@dadukou168.ac.cn"""
    counter = 1
    if _email_counter_file.exists():
        try:
            counter = int(_email_counter_file.read_text().strip()) + 1
        except (ValueError, OSError):
            counter = 1
    
    # 写回计数器
    try:
        _email_counter_file.write_text(str(counter))
    except OSError:
        pass
    
    email = f"{EMAIL_PREFIX}{counter:03d}@{EMAIL_DOMAIN}"
    return email


def get_email_and_token() -> Tuple[Optional[str], Optional[str]]:
    """
    创建域名邮箱并返回 (email, placeholder)。
    注意：这里返回的第二个参数是占位符，因为不需要 DuckMail 的 token。
    """
    email = _get_next_email()
    print(f"[*] 域名邮箱创建: {email}")
    _temp_email_cache[email] = "cf_email"  # 占位符
    return email, "cf_email"


def get_oai_code(dev_token: str, email: str, timeout: int = 120) -> Optional[str]:
    """
    通过 IMAP 轮询 QQ邮箱，等待来自 Grok 的验证码邮件。
    
    Args:
        dev_token: 占位符参数（未使用）
        email: 注册时使用的域名邮箱地址
        timeout: 超时时间（秒）
    
    Returns:
        验证码字符串（如 "MM0SF3"）或 None
    """
    if not IMAP_PASSWORD:
        print("[Error] imap_password 未设置，无法获取验证码")
        return None
    
    code = wait_for_verification_code(email, timeout=timeout)
    return code


# ============================================================
# IMAP 验证码获取
# ============================================================

def _connect_imap() -> Optional[imaplib.IMAP4_SSL]:
    """连接 QQ邮箱 IMAP"""
    try:
        conn = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        conn.login(IMAP_USER, IMAP_PASSWORD)
        return conn
    except Exception as e:
        print(f"[Error] IMAP 连接失败: {e}")
        return None


def _extract_verification_code(content: str) -> Optional[str]:
    """
    从邮件内容提取验证码。
    Grok/x.ai 格式：MM0-SF3（3位-3位字母数字混合）或 6 位纯数字。
    """
    if not content:
        return None

    # 模式 1: Grok 格式 XXX-XXX
    m = re.search(r"(?<![A-Z0-9-])([A-Z0-9]{3}-[A-Z0-9]{3})(?![A-Z0-9-])", content)
    if m:
        return m.group(1)

    # 模式 2: 带标签的验证码
    m = re.search(r"(?:verification code|验证码|your code|verification_code)[:\s]*[<>\s]*([A-Z0-9]{3}-[A-Z0-9]{3})\b", content, re.IGNORECASE)
    if m:
        return m.group(1)

    # 模式 3: HTML 样式包裹
    m = re.search(r"background-color:\s*#F3F3F3[^>]*>[\s\S]*?([A-Z0-9]{3}-[A-Z0-9]{3})[\s\S]*?</p>", content)
    if m:
        return m.group(1)

    # 模式 4: Subject 行 6 位数字
    m = re.search(r"Subject:.*?(\d{6})", content)
    if m and m.group(1) != "177010":
        return m.group(1)

    # 模式 5: HTML 标签内 6 位数字
    for code in re.findall(r">\s*(\d{6})\s*<", content):
        if code != "177010":
            return code

    # 模式 6: 独立 6 位数字
    for code in re.findall(r"(?<![&#\d])(\d{6})(?![&#\d])", content):
        if code != "177010":
            return code

    return None


def wait_for_verification_code(target_email: str, timeout: int = 120) -> Optional[str]:
    """
    轮询 QQ邮箱，等待发往 target_email 的验证码邮件。
    
    Email Routing 会将 xxx@dadukou168.ac.cn 的邮件转发到 IMAP_USER 邮箱。
    我们搜索来自 xAI (noreply@x.ai) 的邮件，然后匹配收件人。
    """
    start = time.time()
    seen_uids = set()
    poll_interval = 5
    
    # 提取邮箱前缀，用于搜索
    email_local = target_email.split("@")[0] if "@" in target_email else target_email
    
    print(f"[*] 等待验证码邮件（发往 {target_email}）...")
    
    while time.time() - start < timeout:
        conn = _connect_imap()
        if not conn:
            time.sleep(poll_interval)
            continue
        
        try:
            conn.select("INBOX")
            
            # 搜索来自 xAI 的邮件（更可靠的方式）
            status, data = conn.search(None, '(FROM "noreply@x.ai")')
            
            if status != "OK" or not data[0]:
                conn.logout()
                time.sleep(poll_interval)
                continue
            
            uids = data[0].split()
            
            # 只检查最新的几封邮件
            for uid in uids[-5:]:
                uid_str = uid.decode()
                if uid_str in seen_uids:
                    continue
                seen_uids.add(uid_str)
                
                try:
                    # 先检查 To 头是否匹配
                    status, header_data = conn.fetch(uid, '(BODY[HEADER.FIELDS (TO)])')
                    if status != "OK":
                        continue
                    
                    to_header = header_data[0][1].decode("utf-8", errors="replace")
                    
                    # 检查是否发往目标邮箱
                    if target_email.lower() not in to_header.lower() and email_local.lower() not in to_header.lower():
                        continue
                    
                    # 获取邮件正文
                    status, msg_data = conn.fetch(uid, "(BODY[TEXT])")
                    if status != "OK":
                        continue
                    
                    body = msg_data[0][1].decode("utf-8", errors="replace")
                    
                    code = _extract_verification_code(body)
                    if code:
                        clean_code = code.replace("-", "")
                        print(f"[*] 提取到验证码: {code} -> {clean_code}")
                        conn.logout()
                        return clean_code
                        
                except Exception as e:
                    print(f"[Warn] 读取邮件异常: {e}")
                    continue
            
        except Exception as e:
            print(f"[Warn] IMAP 操作异常: {e}")
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        
        elapsed = int(time.time() - start)
        if elapsed % 15 == 0 and elapsed > 0:
            print(f"[*] 等待验证码中... ({elapsed}s / {timeout}s)")
        
        time.sleep(poll_interval)
    
    print(f"[Error] 超时 {timeout}s，未收到验证码邮件")
    return None


# ============================================================
# 清理功能
# ============================================================

def reset_counter():
    """重置邮箱计数器"""
    if _email_counter_file.exists():
        _email_counter_file.unlink()
    print("[*] 邮箱计数器已重置")


def get_current_counter() -> int:
    """获取当前邮箱计数器值"""
    if _email_counter_file.exists():
        try:
            return int(_email_counter_file.read_text().strip())
        except (ValueError, OSError):
            pass
    return 0


# ============================================================
# 测试
# ============================================================

if __name__ == "__main__":
    print("=== Cloudflare 域名邮箱注册模块测试 ===")
    print(f"域名: {EMAIL_DOMAIN}")
    print(f"邮箱前缀: {EMAIL_PREFIX}")
    print(f"IMAP 用户: {IMAP_USER}")
    print(f"当前计数器: {get_current_counter()}")
    print()
    
    # 测试生成邮箱
    email, token = get_email_and_token()
    print(f"生成邮箱: {email}")
    print(f"Token: {token}")
    print()
    
    # 测试 IMAP 连接
    conn = _connect_imap()
    if conn:
        print("IMAP 连接: OK")
        conn.logout()
    else:
        print("IMAP 连接: 失败")
