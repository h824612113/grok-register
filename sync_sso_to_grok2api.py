#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import requests
import urllib3


ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "config.json"
SSO_DIR = ROOT / "sso"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_local_tokens():
    tokens = []
    seen = set()

    for path in sorted(SSO_DIR.glob("*.txt")):
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            token = raw_line.strip()
            if not token or token in seen:
                continue
            if len(token) < 80:
                continue
            seen.add(token)
            tokens.append(token)

    return tokens


def extract_existing_tokens(data):
    if isinstance(data, dict) and isinstance(data.get("tokens"), list):
        return [
            item.get("token")
            for item in data["tokens"]
            if isinstance(item, dict) and item.get("pool", "basic") in ("basic", "ssoBasic")
        ]

    if isinstance(data, dict) and isinstance(data.get("tokens"), dict):
        return data["tokens"].get("basic", []) or data["tokens"].get("ssoBasic", [])

    if isinstance(data, dict):
        return data.get("basic", []) or data.get("ssoBasic", [])

    return []


def normalize_tokens(items):
    tokens = []
    seen = set()

    for item in items:
        token = item.get("token") if isinstance(item, dict) else str(item or "").strip()
        if not token or token in seen:
            continue
        seen.add(token)
        tokens.append(token)

    return tokens


def main():
    parser = argparse.ArgumentParser(description="Sync local SSO tokens to grok2api")
    parser.add_argument("--append", dest="append_mode", action="store_true", help="Merge with remote tokens before pushing")
    parser.add_argument("--no-append", dest="append_mode", action="store_false", help="Overwrite remote basic token pool")
    parser.set_defaults(append_mode=None)
    args = parser.parse_args()

    conf = load_config()
    api_conf = conf.get("api", {})
    endpoint = str(api_conf.get("endpoint", "")).strip()
    api_token = str(api_conf.get("token", "")).strip()
    append_mode = api_conf.get("append", True) if args.append_mode is None else args.append_mode

    if not endpoint or not api_token:
        raise SystemExit("config.json missing api.endpoint or api.token")

    local_tokens = load_local_tokens()
    if not local_tokens:
        raise SystemExit("no local SSO tokens found under sso/*.txt")

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }
    is_add_endpoint = endpoint.rstrip("/").endswith("/tokens/add")

    tokens_to_push = list(local_tokens)
    remote_count = 0

    if is_add_endpoint:
        resp = requests.post(
            endpoint,
            params={"app_key": api_token},
            json={"tokens": tokens_to_push, "pool": "basic", "tags": []},
            headers={"Content-Type": "application/json"},
            timeout=120,
            verify=False,
        )
        if resp.status_code != 200:
            raise SystemExit(f"push failed: HTTP {resp.status_code} {resp.text[:200]}")

        result = resp.json()
        print(
            json.dumps(
                {
                    "local_files": len(list(SSO_DIR.glob("*.txt"))),
                    "local_tokens": len(local_tokens),
                    "remote_tokens_before_merge": None,
                    "append_mode": "add_endpoint",
                    "pushed_tokens": len(tokens_to_push),
                    "endpoint": endpoint,
                    "api_result": result,
                },
                ensure_ascii=True,
            )
        )
        return

    if append_mode:
        resp = requests.get(endpoint, headers=headers, timeout=15, verify=False)
        if resp.status_code != 200:
            raise SystemExit(f"failed to fetch remote tokens: HTTP {resp.status_code} {resp.text[:200]}")

        remote_tokens = normalize_tokens(extract_existing_tokens(resp.json()))
        remote_count = len(remote_tokens)
        tokens_to_push = normalize_tokens(remote_tokens + local_tokens)

    resp = requests.post(
        endpoint,
        json={"basic": tokens_to_push},
        headers=headers,
        timeout=60,
        verify=False,
    )
    if resp.status_code != 200:
        raise SystemExit(f"push failed: HTTP {resp.status_code} {resp.text[:200]}")

    print(
        json.dumps(
            {
                "local_files": len(list(SSO_DIR.glob("*.txt"))),
                "local_tokens": len(local_tokens),
                "remote_tokens_before_merge": remote_count,
                "append_mode": append_mode,
                "pushed_tokens": len(tokens_to_push),
                "endpoint": endpoint,
            },
            ensure_ascii=True,
        )
    )


if __name__ == "__main__":
    main()
