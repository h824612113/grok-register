#!/usr/bin/env python3
import argparse
import base64
import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SSO_DIR = ROOT / "sso"
DEFAULT_OUT = ROOT / "exports" / "cpa-from-sso"


def b64url_json(value):
    raw = json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def build_synthetic_id_token(account_id, name, expires_unix):
    header = {"alg": "none", "typ": "JWT", "cpa_synthetic": True}
    payload = {
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": expires_unix,
        "https://api.openai.com/auth": {
            "chatgpt_account_id": account_id,
            "chatgpt_plan_type": "free",
        },
        "name": name,
    }
    return f"{b64url_json(header)}.{b64url_json(payload)}."


def load_sso_tokens(input_paths=None):
    tokens = []
    seen = set()
    paths = [Path(item) for item in input_paths] if input_paths else sorted(SSO_DIR.glob("*.txt"))
    for path in paths:
        if not path.is_absolute():
            path = ROOT / path
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            token = line.strip()
            if len(token) < 80 or token in seen:
                continue
            seen.add(token)
            tokens.append({"token": token, "source_file": str(path.relative_to(ROOT))})
    return tokens


def make_account(row, index, exported_at, expires_unix):
    digest = hashlib.sha256(row["token"].encode("utf-8")).hexdigest()
    account_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"grok-sso:{digest}"))
    name = f"grok-sso-{index:03d}"
    return {
        "type": "codex",
        "account_id": account_id,
        "chatgpt_account_id": account_id,
        "name": name,
        "plan_type": "free",
        "chatgpt_plan_type": "free",
        "id_token": build_synthetic_id_token(account_id, name, expires_unix),
        "id_token_synthetic": True,
        "access_token": row["token"],
        "refresh_token": "",
        "last_refresh": exported_at,
    }


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Export local SSO tokens to CPA-shaped account JSON.")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output directory")
    parser.add_argument("--input", action="append", help="Specific SSO txt file to export; repeatable")
    args = parser.parse_args()

    exported_at = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    expires_unix = int(datetime.now(timezone.utc).timestamp()) + 90 * 24 * 60 * 60
    out_dir = Path(args.out).resolve()
    accounts_dir = out_dir / "cpa" / "accounts"

    rows = load_sso_tokens(args.input)
    if not rows:
        raise SystemExit("no valid SSO tokens found under sso/*.txt")

    accounts = [make_account(row, index + 1, exported_at, expires_unix) for index, row in enumerate(rows)]

    for account in accounts:
        write_json(accounts_dir / f"{account['name']}.cpa.json", account)

    combined = out_dir / "cpa" / "cpa-accounts.json"
    write_json(combined, accounts)
    write_json(out_dir / "manifest.json", {
        "exported_at": exported_at,
        "output_dir": str(out_dir),
        "targets": [{
            "target": "cpa",
            "output_dir": str(out_dir / "cpa"),
            "combined_file": str(combined),
            "individual_dir": str(accounts_dir),
            "new_accounts": len(accounts),
            "total_accounts": len(accounts),
        }],
        "input_dir": str(SSO_DIR),
        "input_files": sorted({row["source_file"] for row in rows}),
        "token_kind": "grok_sso_cookie_mapped_to_cpa_access_token",
        "notes": [
            "Generated from local grok-register SSO cookie files.",
            "CPA id_token values are synthetic because SSO files do not contain OpenAI OAuth id_token metadata.",
        ],
    })

    print(json.dumps({
        "out_dir": str(out_dir),
        "accounts": len(accounts),
        "combined_file": str(combined),
        "accounts_dir": str(accounts_dir),
    }, indent=2))


if __name__ == "__main__":
    main()
