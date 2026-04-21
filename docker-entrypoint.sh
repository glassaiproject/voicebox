#!/bin/sh
set -e
if [ "$(id -u)" = "0" ]; then
  HF_CACHE="/home/voicebox/.cache/huggingface"
  DATA_DIR="/app/data"
  mkdir -p "$HF_CACHE" "$DATA_DIR"
  if ! chown -R voicebox:voicebox "$HF_CACHE" "$DATA_DIR"; then
    echo "docker-entrypoint: ERROR: chown failed for $HF_CACHE and $DATA_DIR" >&2
    exit 1
  fi
  echo "docker-entrypoint: ownership ok — $HF_CACHE $(ls -ldn "$HF_CACHE" | awk '{print $3 ":" $4}')"
  exec gosu voicebox "$@"
fi
exec "$@"
