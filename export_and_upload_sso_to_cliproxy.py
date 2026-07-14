#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SSO_BRIDGE = Path("/Users/hanhao/Documents/freecodex/SSO-Bridge")
DEFAULT_OUT = ROOT / "exports" / "cliproxy-from-sso-bridge" / "all"
DEFAULT_ENDPOINT = "https://cliproxy.cyberhz.com/v0/management/auth-files"

sys.path.insert(0, str(SSO_BRIDGE))
from app.converter import load_sso_list, serialize_json, token_to_cliproxy_entry  # noqa: E402
from app.oauth import RateLimitedError, backoff_sec, sso_to_token  # noqa: E402


def load_all_accounts(input_paths: list[str] | None) -> list[tuple[str, str, str]]:
    paths = [Path(item) for item in input_paths] if input_paths else sorted((ROOT / "sso").glob("*.txt"))
    rows: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for path in paths:
        if not path.is_absolute():
            path = ROOT / path
        for cookie, email in load_sso_list(path.read_text(encoding="utf-8", errors="ignore")):
            if cookie in seen:
                continue
            seen.add(cookie)
            rows.append((cookie, email, str(path.relative_to(ROOT))))
    return rows


def read_manifest(path: Path) -> dict:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {
        "total": 0,
        "success": 0,
        "failed": 0,
        "uploaded": 0,
        "files": [],
        "failures": [],
        "upload_failures": [],
    }


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def convert_one(index: int, total: int, cookie: str, email: str, source_file: str, out_dir: Path, args) -> dict:
    logs: list[str] = []
    label = email or f"account-{index}"
    for attempt in range(1, args.account_retries + 1):
        try:
            token = sso_to_token(
                cookie,
                max_retries=args.retries,
                base_delay=args.delay,
                log=lambda message: logs.append(message),
            )
            if not token:
                return {
                    "ok": False,
                    "index": index,
                    "label": label,
                    "source_file": source_file,
                    "error": "SSO conversion failed",
                    "logs": logs[-8:],
                }
            filename, entry = token_to_cliproxy_entry(token, email=email)
            target = out_dir / filename
            if target.exists():
                target = out_dir / f"{target.stem}-{index}{target.suffix}"
            target.write_bytes(serialize_json(entry, compact=False))
            return {
                "ok": True,
                "index": index,
                "label": entry.get("email") or label,
                "source_file": source_file,
                "file": str(target),
                "filename": target.name,
                "access_len": len(entry.get("access_token", "")),
                "refresh_len": len(entry.get("refresh_token", "")),
                "id_len": len(entry.get("id_token", "")),
            }
        except RateLimitedError as exc:
            if attempt >= args.account_retries:
                return {
                    "ok": False,
                    "index": index,
                    "label": label,
                    "source_file": source_file,
                    "error": str(exc),
                    "logs": logs[-8:],
                }
            time.sleep(backoff_sec(args.delay, attempt, args.max_delay))
        except Exception as exc:
            return {
                "ok": False,
                "index": index,
                "label": label,
                "source_file": source_file,
                "error": str(exc),
                "logs": logs[-8:],
            }
    return {"ok": False, "index": index, "label": label, "source_file": source_file, "error": "unknown failure"}


def upload_batch(files: list[str], endpoint: str, management_key: str) -> dict:
    cmd = ["curl", "-sS", "-X", "POST", "-H", f"X-Management-Key: {management_key}"]
    for file_path in files:
        cmd.extend(["-F", f"file=@{file_path}"])
    cmd.append(endpoint)
    result = subprocess.run(cmd, check=False, text=True, capture_output=True, timeout=180)
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        payload = {"raw": result.stdout[:500]}
    return {"returncode": result.returncode, "response": payload, "stderr": result.stderr[-500:]}


def upload_pending(manifest: dict, endpoint: str, management_key: str, batch_size: int) -> None:
    uploaded = {item["file"] for item in manifest.get("uploaded_files", []) if isinstance(item, dict) and item.get("file")}
    pending = [item["file"] for item in manifest.get("files", []) if item.get("file") and item["file"] not in uploaded]
    manifest.setdefault("uploaded_files", [])
    for start in range(0, len(pending), batch_size):
        batch = pending[start:start + batch_size]
        result = upload_batch(batch, endpoint, management_key)
        if result["returncode"] == 0 and int(result["response"].get("uploaded", 0) or 0) >= 1:
            for file_path in batch:
                manifest["uploaded_files"].append({"file": file_path})
            manifest["uploaded"] = len(manifest["uploaded_files"])
        else:
            manifest.setdefault("upload_failures", []).append({"files": batch, **result})


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert local x.ai SSO cookies to cliproxyapi xai files and upload them.")
    parser.add_argument("--input", action="append", help="Specific SSO txt file; repeatable. Defaults to all sso/*.txt")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--management-key", default=os.environ.get("CLIPROXY_MANAGEMENT_KEY", ""))
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=10)
    parser.add_argument("--max-delay", type=float, default=180)
    parser.add_argument("--retries", type=int, default=4)
    parser.add_argument("--account-retries", type=int, default=2)
    parser.add_argument("--upload-batch-size", type=int, default=25)
    parser.add_argument("--no-upload", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = read_manifest(manifest_path)

    accounts = load_all_accounts(args.input)
    if args.limit > 0:
        accounts = accounts[:args.limit]
    manifest["total"] = len(accounts)
    manifest["output_dir"] = str(out_dir)
    manifest["endpoint"] = args.endpoint
    write_manifest(manifest_path, manifest)

    done_indices = {item["index"] for item in manifest.get("files", []) if isinstance(item, dict)}
    failed_indices = {item["index"] for item in manifest.get("failures", []) if isinstance(item, dict)}
    pending_rows = [
        (index, cookie, email, source_file)
        for index, (cookie, email, source_file) in enumerate(accounts, start=1)
        if index not in done_indices and index not in failed_indices
    ]

    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as executor:
        futures = {
            executor.submit(convert_one, index, len(accounts), cookie, email, source_file, out_dir, args)
            for index, cookie, email, source_file in pending_rows
        }
        pending = set(futures)
        while pending:
            done, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            for future in done:
                result = future.result()
                if result.pop("ok", False):
                    manifest.setdefault("files", []).append(result)
                    manifest["success"] = len(manifest["files"])
                else:
                    manifest.setdefault("failures", []).append(result)
                    manifest["failed"] = len(manifest["failures"])
                write_manifest(manifest_path, manifest)
                print(json.dumps({
                    "success": manifest["success"],
                    "failed": manifest["failed"],
                    "remaining": len(pending),
                    "last": result.get("label"),
                }, ensure_ascii=False), flush=True)

    if not args.no_upload:
        if not args.management_key:
            raise SystemExit("missing --management-key or CLIPROXY_MANAGEMENT_KEY")
        upload_pending(manifest, args.endpoint, args.management_key, args.upload_batch_size)
        write_manifest(manifest_path, manifest)

    print(json.dumps({
        "output_dir": str(out_dir),
        "total": manifest.get("total", 0),
        "success": manifest.get("success", 0),
        "failed": manifest.get("failed", 0),
        "uploaded": manifest.get("uploaded", 0),
        "upload_failures": len(manifest.get("upload_failures", [])),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
