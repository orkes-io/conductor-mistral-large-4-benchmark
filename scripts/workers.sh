#!/bin/bash
# Start/stop the benchmark workers as one process group (the SDK forks one process per worker,
# so killing only the parent leaves orphans that keep polling).
cd "$(dirname "$0")/.."
# TARGET=de (default: the Orkes server in CONDUCTOR_* env vars or CONDUCTOR_ENV_FILE) or TARGET=oss (local OSS, no auth)
TARGET=${TARGET:-de}
if [ "$TARGET" = "oss" ]; then
  PGFILE=logs/workers-oss.pgid; LOG=logs/workers-oss.log
  export CONDUCTOR_ENV_FILE=/dev/null CONDUCTOR_SERVER_URL=${OSS_URL:-http://localhost:8080/api}
else
  PGFILE=logs/workers.pgid; LOG=logs/workers.log
fi
# HTTP/1.1: the server ends HTTP/2 connections every ~2000 streams and a task update in flight can be lost
export CONDUCTOR_HTTP2_ENABLED=false
mkdir -p logs
case "$1" in
  start)
    if [ -f $PGFILE ] && kill -0 -- -"$(cat $PGFILE)" 2>/dev/null; then echo "already running (pgid $(cat $PGFILE))"; exit 0; fi
    # set -m gives the background job its own process group (pgid == pid)
    set -m
    nohup .venv/bin/python workers/main.py >> "$LOG" 2>&1 &
    echo $! > $PGFILE
    echo "started pgid $(cat $PGFILE)" ;;
  stop)
    [ -f $PGFILE ] || { echo "not running"; exit 0; }
    PG=$(cat $PGFILE)
    kill -TERM -- -"$PG" 2>/dev/null; sleep 3; kill -KILL -- -"$PG" 2>/dev/null
    rm -f $PGFILE; echo "stopped pgid $PG" ;;
  status)
    [ -f $PGFILE ] && ps -eo pid,pgid,command | awk -v pg="$(cat $PGFILE)" '$2==pg' | wc -l | xargs echo "processes:" || echo "not running" ;;
esac
