#!/usr/bin/env bash
# Run the voicebox server in the background, without the Tauri app.
#
#   scripts/server.sh start|stop|restart|status|logs
#   scripts/server.sh agent-install|agent-uninstall   (macOS launchd: start at login, restart on crash)
#
# Env: VOICEBOX_PORT (17493), VOICEBOX_HOST (127.0.0.1)

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${VOICEBOX_PORT:-17493}"
HOST="${VOICEBOX_HOST:-127.0.0.1}"
UVICORN="$ROOT/backend/venv/bin/uvicorn"
LOG="$ROOT/voicebox-server.log"
PID_FILE="$ROOT/data/voicebox-server.pid"
LABEL="com.glass.voicebox"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

health() { curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; }
port_pid() { lsof -t -iTCP:"$PORT" -sTCP:LISTEN 2>/dev/null | head -1 || true; }
agent_loaded() { [ "$(uname)" = "Darwin" ] && launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1; }

require_venv() {
  if [ ! -x "$UVICORN" ]; then
    echo "No venv at backend/venv. Run 'just setup' first." >&2
    exit 1
  fi
}

start() {
  if agent_loaded; then
    echo "Managed by launchd ($LABEL). Use: launchctl kickstart -k gui/$(id -u)/$LABEL"
    return
  fi
  if [ -n "$(port_pid)" ]; then
    echo "Already running on :$PORT (pid $(port_pid))"
    return
  fi
  require_venv
  mkdir -p "$ROOT/data"
  cd "$ROOT"
  nohup "$UVICORN" backend.main:app --host "$HOST" --port "$PORT" >>"$LOG" 2>&1 &
  echo $! >"$PID_FILE"
  echo -n "Starting voicebox on http://$HOST:$PORT (pid $!) "
  for _ in $(seq 1 60); do
    if health; then echo "ready"; return; fi
    if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
      echo "failed, see $LOG" >&2
      tail -20 "$LOG" >&2
      exit 1
    fi
    echo -n "."
    sleep 1
  done
  echo " still starting, check: $0 status"
}

stop() {
  if agent_loaded; then
    echo "Server is managed by launchd. Use: $0 agent-uninstall" >&2
    exit 1
  fi
  local pid=""
  [ -f "$PID_FILE" ] && pid="$(cat "$PID_FILE")"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then pid="$(port_pid)"; fi
  if [ -z "$pid" ]; then
    echo "Not running"
    rm -f "$PID_FILE"
    return
  fi
  kill "$pid"
  for _ in $(seq 1 15); do
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  kill -0 "$pid" 2>/dev/null && kill -9 "$pid"
  rm -f "$PID_FILE"
  echo "Stopped (pid $pid)"
}

status() {
  local pid
  pid="$(port_pid)"
  if [ -z "$pid" ]; then
    echo "Not running"
    exit 1
  fi
  local via="nohup"
  agent_loaded && via="launchd"
  if health; then
    echo "Running on http://$HOST:$PORT (pid $pid, $via): $(curl -s "http://127.0.0.1:$PORT/health")"
  else
    echo "Process $pid holds :$PORT but /health does not answer yet ($via)"
  fi
}

agent_install() {
  if [ "$(uname)" != "Darwin" ]; then
    echo "launchd agent is macOS only" >&2
    exit 1
  fi
  require_venv
  if ! agent_loaded && [ -n "$(port_pid)" ]; then stop; fi
  mkdir -p "$(dirname "$PLIST")"
  cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>ProgramArguments</key>
  <array>
    <string>$UVICORN</string>
    <string>backend.main:app</string>
    <string>--host</string><string>$HOST</string>
    <string>--port</string><string>$PORT</string>
  </array>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
  agent_loaded && launchctl bootout "gui/$(id -u)/$LABEL" || true
  launchctl bootstrap "gui/$(id -u)" "$PLIST"
  echo "Installed $PLIST; voicebox now starts at login on :$PORT"
}

agent_uninstall() {
  if agent_loaded; then launchctl bootout "gui/$(id -u)/$LABEL"; fi
  rm -f "$PLIST"
  echo "Removed launchd agent $LABEL"
}

case "${1:-}" in
  start) start ;;
  stop) stop ;;
  restart)
    if agent_loaded; then launchctl kickstart -k "gui/$(id -u)/$LABEL" && echo "Restarted $LABEL"; else stop; start; fi
    ;;
  status) status ;;
  logs) tail -n 100 -f "$LOG" ;;
  agent-install) agent_install ;;
  agent-uninstall) agent_uninstall ;;
  *)
    echo "Usage: $0 {start|stop|restart|status|logs|agent-install|agent-uninstall}" >&2
    exit 1
    ;;
esac
