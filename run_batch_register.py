#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parent
BATCH_SCRIPT = ROOT / "scripts" / "batch_register_and_push.sh"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run grok-register batch registration, then sync grok2api and cliproxy xai auth files."
    )
    parser.add_argument("--count", "-c", required=True, type=int, help="Number of accounts to register.")
    parser.add_argument("--rebuild-venv", action="store_true", help="Rebuild project venv before running.")
    parser.add_argument("--skip-sync", action="store_true", help="Skip grok2api strict sync.")
    parser.add_argument("--skip-cliproxy", action="store_true", help="Skip SSO-Bridge xai conversion/upload.")
    parser.add_argument("--cliproxy-concurrency", type=int, default=16)
    parser.add_argument("--cliproxy-upload-batch-size", type=int, default=50)
    parser.add_argument("--idle-timeout", type=int, default=600)
    parser.add_argument("--extract-numbers", action="store_true")
    args = parser.parse_args()

    cmd = [
        str(BATCH_SCRIPT),
        "--count",
        str(args.count),
        "--cliproxy-concurrency",
        str(args.cliproxy_concurrency),
        "--cliproxy-upload-batch-size",
        str(args.cliproxy_upload_batch_size),
        "--idle-timeout",
        str(args.idle_timeout),
    ]
    if not args.rebuild_venv:
        cmd.append("--no-rebuild-venv")
    if args.skip_sync:
        cmd.append("--skip-sync")
    if args.skip_cliproxy:
        cmd.append("--skip-cliproxy")
    if args.extract_numbers:
        cmd.append("--extract-numbers")

    return subprocess.run(cmd, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
