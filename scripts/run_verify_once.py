#!/usr/bin/env python3
"""Double-fork daemonize a single registration verify run."""
import datetime
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)

ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
out = ROOT / "sso" / f"verify_fix_{ts}.txt"
log = ROOT / "logs" / f"verify_fix_{ts}.stdout.log"
log.parent.mkdir(exist_ok=True)
out.parent.mkdir(exist_ok=True)

Path("/tmp/grok_verify_out.txt").write_text(str(out), encoding="utf-8")
Path("/tmp/grok_verify_log.txt").write_text(str(log), encoding="utf-8")
Path("/tmp/grok_verify_ts.txt").write_text(ts, encoding="utf-8")

py = str(ROOT / "venv" / "bin" / "python")
script = str(ROOT / "DrissionPage_example.py")
cmd = [py, "-u", script, "--count", "1", "--output", str(out)]

pid = os.fork()
if pid > 0:
    # parent waits briefly for grandchild pid file
    for _ in range(50):
        p = Path("/tmp/grok_verify_pid.txt")
        if p.exists() and p.read_text(encoding="utf-8").strip().isdigit():
            print(f"START {ts} pid={p.read_text().strip()} out={out} log={log}", flush=True)
            break
        time.sleep(0.1)
    else:
        print(f"START {ts} pid=? out={out} log={log}", flush=True)
    sys.exit(0)

os.setsid()
pid2 = os.fork()
if pid2 > 0:
    os._exit(0)

# grandchild
with open(log, "w", encoding="utf-8") as lf:
    os.dup2(lf.fileno(), 1)
    os.dup2(lf.fileno(), 2)

Path("/tmp/grok_verify_pid.txt").write_text(str(os.getpid()), encoding="utf-8")
os.environ["PYTHONUNBUFFERED"] = "1"
os.chdir(ROOT)
os.execve(py, cmd, os.environ)
