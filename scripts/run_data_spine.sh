#!/usr/bin/env bash
# SR data spine nightly runner (§4.5.5) — cron on this box, after Fin-Lambda
# 20:00 ET load. ingest → rebuild → status; non-zero rc alerts ops watchdog.
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "== SR data spine $(date -u +%FT%TZ) =="
python -m sr_agent.ops.schedules ingest
python -m sr_agent.ops.schedules rebuild
python -m sr_agent.ops.schedules status
echo "== spine ok =="
