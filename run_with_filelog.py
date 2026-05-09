#!/usr/bin/env python3
"""用文件日志方式运行 DrissionPage_example.py，解决 stdout 被吞问题"""
import subprocess, sys, os, time
from pathlib import Path

LOG_FILE = "/tmp/grok_run.log"
SCRIPT = str(Path(__file__).parent / "DrissionPage_example.py")

# 清空日志
Path(LOG_FILE).write_text("")

env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

proc = subprocess.Popen(
    [sys.executable, SCRIPT, "--count", "1"],
    cwd=str(Path(__file__).parent),
    stdout=open(LOG_FILE, "w", buffering=1),
    stderr=subprocess.STDOUT,
    env=env,
)

print(f"PID: {proc.pid}")
print(f"Log: {LOG_FILE}")
print("Running... (poll with 'cat /tmp/grok_run.log')")
