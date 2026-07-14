#!/usr/bin/env bash
set -Eeuo pipefail

# 批量注册 + 结束后严格同步到 grok2api
# 用法：scripts/batch_register_and_push.sh --count 10

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="python3.11"
COUNT=""
REBUILD_VENV=1
SYNC_MODE="append"   # append | no-append
SKIP_SYNC=0
SKIP_CLIPROXY=0
EXTRACT_NUMBERS=0
IDLE_TIMEOUT=600
CLIPROXY_ENDPOINT="https://cliproxy.cyberhz.com/v0/management/auth-files"
CLIPROXY_CONCURRENCY=16
CLIPROXY_UPLOAD_BATCH_SIZE=50
RUN_LABEL=""

usage() {
  cat <<'USAGE'
Usage:
  scripts/batch_register_and_push.sh --count N [options]

Options:
  -c, --count N        注册数量。必须是正整数；0 表示无限循环，不适合“结束后推送”，本脚本会拒绝。
  --python PATH        创建 venv 使用的 Python，默认 python3.11。
  --no-rebuild-venv    不重建 venv，直接使用已有 venv/bin/python。
  --append             同步 grok2api 时合并远端已有 token（默认）。
  --no-append          同步 grok2api 时用本地 sso/*.txt 覆盖远端 basic 池。
  --skip-sync          跳过结束后的严格同步；不推荐。主脚本仍会尝试推送本次 token。
  --skip-cliproxy      跳过 SSO-Bridge 转 xai 文件并上传 cliproxy。
  --cliproxy-endpoint URL
                       cliproxy Management auth-files 地址。
  --cliproxy-concurrency N
                       SSO 转 xai 并发数，默认 16。
  --cliproxy-upload-batch-size N
                       上传 multipart 批大小，默认 50。
  --run-label LABEL    附加到本次输出文件名，供并行 worker 避免同秒冲突。
  --extract-numbers    传递给 DrissionPage_example.py 的调试参数。
  --idle-timeout SEC   无新 SSO 产出的熔断秒数，默认 600；0 表示关闭。
  -h, --help           显示帮助。

Examples:
  scripts/batch_register_and_push.sh --count 10
  scripts/batch_register_and_push.sh --count 50 --no-rebuild-venv
  scripts/batch_register_and_push.sh --count 20 --no-append
USAGE
}

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

fail() {
  printf '[ERROR] %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--count)
      [[ $# -ge 2 ]] || fail "--count 缺少参数"
      COUNT="$2"
      shift 2
      ;;
    --python)
      [[ $# -ge 2 ]] || fail "--python 缺少参数"
      PYTHON_BIN="$2"
      shift 2
      ;;
    --no-rebuild-venv)
      REBUILD_VENV=0
      shift
      ;;
    --append)
      SYNC_MODE="append"
      shift
      ;;
    --no-append)
      SYNC_MODE="no-append"
      shift
      ;;
    --skip-sync)
      SKIP_SYNC=1
      shift
      ;;
    --skip-cliproxy)
      SKIP_CLIPROXY=1
      shift
      ;;
    --cliproxy-endpoint)
      [[ $# -ge 2 ]] || fail "--cliproxy-endpoint 缺少参数"
      CLIPROXY_ENDPOINT="$2"
      shift 2
      ;;
    --cliproxy-concurrency)
      [[ $# -ge 2 ]] || fail "--cliproxy-concurrency 缺少参数"
      CLIPROXY_CONCURRENCY="$2"
      shift 2
      ;;
    --cliproxy-upload-batch-size)
      [[ $# -ge 2 ]] || fail "--cliproxy-upload-batch-size 缺少参数"
      CLIPROXY_UPLOAD_BATCH_SIZE="$2"
      shift 2
      ;;
    --run-label)
      [[ $# -ge 2 ]] || fail "--run-label 缺少参数"
      RUN_LABEL="$2"
      shift 2
      ;;
    --extract-numbers)
      EXTRACT_NUMBERS=1
      shift
      ;;
    --idle-timeout)
      [[ $# -ge 2 ]] || fail "--idle-timeout 缺少参数"
      IDLE_TIMEOUT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "未知参数: $1"
      ;;
  esac
done

[[ -n "$COUNT" ]] || fail "必须指定 --count N"
[[ "$COUNT" =~ ^[0-9]+$ ]] || fail "--count 必须是数字"
[[ "$COUNT" -gt 0 ]] || fail "--count 不能为 0；无限循环无法触发结束后推送，请设置正整数"
[[ "$IDLE_TIMEOUT" =~ ^[0-9]+$ ]] || fail "--idle-timeout 必须是数字"
[[ "$CLIPROXY_CONCURRENCY" =~ ^[0-9]+$ && "$CLIPROXY_CONCURRENCY" -gt 0 ]] || fail "--cliproxy-concurrency 必须是正整数"
[[ "$CLIPROXY_UPLOAD_BATCH_SIZE" =~ ^[0-9]+$ && "$CLIPROXY_UPLOAD_BATCH_SIZE" -gt 0 ]] || fail "--cliproxy-upload-batch-size 必须是正整数"

cd "$ROOT_DIR"
mkdir -p logs sso

TS="$(date '+%Y%m%d_%H%M%S')"
if [[ -n "$RUN_LABEL" ]]; then
  SAFE_RUN_LABEL="$(printf '%s' "$RUN_LABEL" | tr -c 'A-Za-z0-9_.-' '_')"
  TS="${TS}_${SAFE_RUN_LABEL}"
fi
OUT_FILE="sso/batch_${TS}_count${COUNT}.txt"
RUN_STDOUT_LOG="logs/batch_${TS}_count${COUNT}.stdout.log"
SUMMARY_FILE="logs/batch_${TS}_count${COUNT}.summary.json"

log "项目目录: $ROOT_DIR"
log "注册数量: $COUNT"
log "SSO 输出: $OUT_FILE"
log "运行输出日志: $RUN_STDOUT_LOG"

if [[ "$REBUILD_VENV" -eq 1 ]]; then
  log "重建 Python venv: $PYTHON_BIN"
  rm -rf venv
  "$PYTHON_BIN" -m venv venv
  venv/bin/pip install -r requirements.txt
else
  [[ -x venv/bin/python ]] || fail "venv/bin/python 不存在；请去掉 --no-rebuild-venv 或先创建 venv"
fi

log "执行主注册脚本"
CMD=(venv/bin/python DrissionPage_example.py --count "$COUNT" --output "$OUT_FILE")
if [[ "$EXTRACT_NUMBERS" -eq 1 ]]; then
  CMD+=(--extract-numbers)
fi

RUN_EXIT=""
set +e
PYTHONUNBUFFERED=1 "${CMD[@]}" > >(tee "$RUN_STDOUT_LOG") 2>&1 &
RUN_PID=$!
LAST_TOKEN_COUNT=0
LAST_PROGRESS_TS=$(date +%s)
if [[ -f "$OUT_FILE" ]]; then
  LAST_TOKEN_COUNT="$(grep -cve '^[[:space:]]*$' "$OUT_FILE" || true)"
fi

while kill -0 "$RUN_PID" 2>/dev/null; do
  sleep 15
  CURRENT_TOKEN_COUNT=0
  if [[ -f "$OUT_FILE" ]]; then
    CURRENT_TOKEN_COUNT="$(grep -cve '^[[:space:]]*$' "$OUT_FILE" || true)"
  fi
  if [[ "$CURRENT_TOKEN_COUNT" -gt "$LAST_TOKEN_COUNT" ]]; then
    LAST_TOKEN_COUNT="$CURRENT_TOKEN_COUNT"
    LAST_PROGRESS_TS=$(date +%s)
  fi
  if [[ "$IDLE_TIMEOUT" -gt 0 ]]; then
    NOW_TS=$(date +%s)
    IDLE=$((NOW_TS - LAST_PROGRESS_TS))
    if [[ "$IDLE" -ge "$IDLE_TIMEOUT" ]]; then
      log "熔断：${IDLE_TIMEOUT}s 内没有新的 SSO 产出，终止主注册进程 PID=$RUN_PID"
      kill "$RUN_PID" 2>/dev/null || true
      sleep 3
      kill -9 "$RUN_PID" 2>/dev/null || true
      wait "$RUN_PID" 2>/dev/null
      RUN_EXIT=124
      break
    fi
  fi
done

if [[ -z "${RUN_EXIT:-}" ]]; then
  wait "$RUN_PID"
  RUN_EXIT=$?
fi
set -e

# 在 Ctrl+C 或 wait 被信号打断等边界情况下，确保 set -u 下仍有明确退出码。
if [[ -z "${RUN_EXIT:-}" ]]; then
  RUN_EXIT=130
fi

if [[ "$RUN_EXIT" -ne 0 ]]; then
  fail "主注册脚本退出码异常: ${RUN_EXIT:-unknown}；详见 $RUN_STDOUT_LOG"
fi

[[ -f "$OUT_FILE" ]] || fail "未生成 SSO 输出文件: $OUT_FILE"
TOKEN_COUNT="$(grep -cve '^[[:space:]]*$' "$OUT_FILE" || true)"
SHORT_TOKEN_COUNT="$(awk 'length($0)>0 && length($0)<100 {c++} END {print c+0}' "$OUT_FILE")"
SUCCESS_COUNT="$(grep -c '注册成功' "$RUN_STDOUT_LOG" || true)"

if [[ "$TOKEN_COUNT" -le 0 ]]; then
  fail "本次输出 SSO 数为 0，触发熔断；详见 $RUN_STDOUT_LOG"
fi

if [[ "$SUCCESS_COUNT" -gt 0 && "$TOKEN_COUNT" -ne "$SUCCESS_COUNT" ]]; then
  fail "成功日志数($SUCCESS_COUNT) 与 SSO 行数($TOKEN_COUNT) 不一致，触发熔断"
fi

if [[ "$SHORT_TOKEN_COUNT" -gt 0 ]]; then
  fail "发现 $SHORT_TOKEN_COUNT 个疑似异常短 token，触发熔断；输出文件: $OUT_FILE"
fi

SYNC_EXIT=0
SYNC_OUTPUT=""
if [[ "$SKIP_SYNC" -eq 0 ]]; then
  log "结束后严格同步到 grok2api: sync_sso_to_grok2api.py --$SYNC_MODE"
  set +e
  SYNC_OUTPUT="$(venv/bin/python sync_sso_to_grok2api.py --"$SYNC_MODE" 2>&1)"
  SYNC_EXIT=$?
  set -e
  printf '%s\n' "$SYNC_OUTPUT" | tee -a "$RUN_STDOUT_LOG"
  if [[ "$SYNC_EXIT" -ne 0 ]]; then
    fail "grok2api 严格同步失败；详见 $RUN_STDOUT_LOG"
  fi
else
  log "已按参数跳过严格同步；注意主脚本仍会尝试推送本次 token。"
fi

CLIPROXY_EXIT=0
CLIPROXY_OUTPUT=""
CLIPROXY_OUT_DIR="exports/cliproxy-from-sso-bridge/batch_${TS}_count${COUNT}"
CLIPROXY_UPLOADED=0
CLIPROXY_SUCCESS=0
CLIPROXY_FAILED=0
if [[ "$SKIP_CLIPROXY" -eq 0 ]]; then
  CLIPROXY_KEY="${CLIPROXY_MANAGEMENT_KEY:-}"
  if [[ -z "$CLIPROXY_KEY" && -f config.json ]]; then
    CLIPROXY_KEY="$(venv/bin/python - <<'PY'
import json
from pathlib import Path

path = Path("config.json")
try:
    data = json.loads(path.read_text(encoding="utf-8"))
except Exception:
    data = {}
cliproxy = data.get("cliproxy") if isinstance(data.get("cliproxy"), dict) else {}
print(str(cliproxy.get("management_key") or data.get("cliproxy_management_key") or "").strip())
PY
)"
  fi
  [[ -n "$CLIPROXY_KEY" ]] || fail "缺少 cliproxy management key：请设置 CLIPROXY_MANAGEMENT_KEY 或 config.json cliproxy.management_key"

  log "SSO-Bridge 转 xai 并上传 cliproxy: $CLIPROXY_OUT_DIR"
  set +e
  CLIPROXY_OUTPUT="$(CLIPROXY_MANAGEMENT_KEY="$CLIPROXY_KEY" venv/bin/python export_and_upload_sso_to_cliproxy.py \
    --input "$OUT_FILE" \
    --out "$CLIPROXY_OUT_DIR" \
    --endpoint "$CLIPROXY_ENDPOINT" \
    --concurrency "$CLIPROXY_CONCURRENCY" \
    --upload-batch-size "$CLIPROXY_UPLOAD_BATCH_SIZE" 2>&1)"
  CLIPROXY_EXIT=$?
  set -e
  printf '%s\n' "$CLIPROXY_OUTPUT" | tee -a "$RUN_STDOUT_LOG"
  if [[ "$CLIPROXY_EXIT" -ne 0 ]]; then
    fail "cliproxy xai 转换/上传失败；详见 $RUN_STDOUT_LOG"
  fi
  if [[ -f "$CLIPROXY_OUT_DIR/manifest.json" ]]; then
    CLIPROXY_SUCCESS="$(venv/bin/python - <<PY
import json
print(json.load(open("$CLIPROXY_OUT_DIR/manifest.json")).get("success", 0))
PY
)"
    CLIPROXY_FAILED="$(venv/bin/python - <<PY
import json
print(json.load(open("$CLIPROXY_OUT_DIR/manifest.json")).get("failed", 0))
PY
)"
    CLIPROXY_UPLOADED="$(venv/bin/python - <<PY
import json
print(json.load(open("$CLIPROXY_OUT_DIR/manifest.json")).get("uploaded", 0))
PY
)"
  fi
else
  log "已按参数跳过 cliproxy xai 转换/上传。"
fi

cat > "$SUMMARY_FILE" <<JSON
{
  "timestamp": "$TS",
  "count_requested": $COUNT,
  "sso_output": "$OUT_FILE",
  "stdout_log": "$RUN_STDOUT_LOG",
  "token_count": $TOKEN_COUNT,
  "success_count": $SUCCESS_COUNT,
  "short_token_count": $SHORT_TOKEN_COUNT,
  "strict_sync_skipped": $SKIP_SYNC,
  "strict_sync_mode": "$SYNC_MODE",
  "strict_sync_exit": $SYNC_EXIT,
  "cliproxy_skipped": $SKIP_CLIPROXY,
  "cliproxy_endpoint": "$CLIPROXY_ENDPOINT",
  "cliproxy_out_dir": "$CLIPROXY_OUT_DIR",
  "cliproxy_exit": $CLIPROXY_EXIT,
  "cliproxy_success": $CLIPROXY_SUCCESS,
  "cliproxy_failed": $CLIPROXY_FAILED,
  "cliproxy_uploaded": $CLIPROXY_UPLOADED,
  "idle_timeout": $IDLE_TIMEOUT
}
JSON

log "完成：本次生成 $TOKEN_COUNT 个 SSO，cliproxy 上传 $CLIPROXY_UPLOADED 个，摘要: $SUMMARY_FILE"
