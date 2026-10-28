#!/usr/bin/env bash
# 每天备份：SQLite 热备份 + 题库 JSON 打包；保留 14 天。
# 用法：scripts/backup.sh；cron: 0 3 * * * /opt/youxuejing/scripts/backup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p backups
TS=$(date +%Y%m%d-%H%M%S)

python3 - "$TS" <<'PY'
import sqlite3
import sys
from pathlib import Path

ts = sys.argv[1]
src = Path("data/yj.db")
if src.exists():
    dst = Path("backups") / f"yj-{ts}.db"
    with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
        s.backup(d)
    print(f"sqlite -> {dst}")
PY

tar --exclude='data/yj.db*' --exclude='data/prewarm' \
    -czf "backups/yj-data-${TS}.tgz" data
echo "data -> backups/yj-data-${TS}.tgz"

find backups -type f -mtime +14 -delete
