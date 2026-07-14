#!/usr/bin/env python3
import json
from pathlib import Path
from typing import Iterable, Optional

import requests
import urllib3


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"


def load_api_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        conf = json.load(f)
    return conf.get("api", {})


def normalize_tokens(tokens: Iterable[str]) -> list[str]:
    seen = set()
    normalized = []
    for raw in tokens:
        token = str(raw or "").strip()
        if not token or token in seen:
            continue
        if len(token) < 80:
            continue
        seen.add(token)
        normalized.append(token)
    return normalized


def push_tokens(tokens: Iterable[str], *, note: Optional[str] = None) -> dict:
    api_conf = load_api_config()
    endpoint = str(api_conf.get("endpoint", "")).strip()
    api_token = str(api_conf.get("token", "")).strip()
    tokens_to_push = normalize_tokens(tokens)

    if not endpoint or not api_token:
        raise RuntimeError("config.json missing api.endpoint or api.token")
    if not tokens_to_push:
        raise RuntimeError("no valid SSO tokens to push")

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    is_add_endpoint = endpoint.rstrip("/").endswith("/tokens/add")

    if is_add_endpoint:
        tags = [note] if note else []
        resp = requests.post(
            endpoint,
            params={"app_key": api_token},
            json={"tokens": tokens_to_push, "pool": "basic", "tags": tags},
            headers={"Content-Type": "application/json"},
            timeout=60,
            verify=False,
        )
    else:
        resp = requests.post(
            endpoint,
            json={"basic": tokens_to_push},
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            timeout=60,
            verify=False,
        )

    if resp.status_code != 200:
        raise RuntimeError(f"push failed: HTTP {resp.status_code} {resp.text[:200]}")

    try:
        return resp.json()
    except ValueError:
        return {"status": "success", "text": resp.text}


def push_single_token(token: str, note: Optional[str] = None) -> dict:
    return push_tokens([token], note=note)
