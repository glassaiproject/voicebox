#!/bin/sh
set -e
if [ "$(id -u)" = "0" ]; then
  chown -R voicebox:voicebox /home/voicebox/.cache/huggingface /app/data 2>/dev/null || true
  exec gosu voicebox "$@"
fi
exec "$@"
