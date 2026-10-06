#!/usr/bin/env bash
# lawbench T28: smoke test of the macOS dmg on a clean Mac (GitHub Actions macos-15): mount, copy to /Applications,
# clear quarantine, start with both servers pointing at dead 127.0.0.1 ports (no real server is ever contacted), wait for
# the window, take a screenshot of the first-run page, collect the start-up self-check from the metadata-only logs,
# record every network connection the app's processes hold, quit.
# Usage: smoke.sh <dmg> <out dir>
set -euo pipefail
DMG="${1:?usage: smoke.sh <dmg> <out>}"
OUT="${2:?usage: smoke.sh <dmg> <out>}"
mkdir -p "$OUT"
LOG="$OUT/smoke.txt"
say() { echo "[smoke] $*" | tee -a "$LOG"; }
NAME="连越律师工作台"
APP="/Applications/$NAME.app"
APPDATA="$HOME/Library/Application Support/lawbench"
MNT="$(mktemp -d)/dmg"

say "dmg: $(basename "$DMG") $(shasum -a 256 "$DMG" | awk '{print $1}')"
hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$MNT" "$DMG" >/dev/null
say "dmg contents: $(ls "$MNT" | tr '\n' '|')"
for a in "$MNT"/*.app; do ditto "$a" "/Applications/$(basename "$a")"; done
hdiutil detach "$MNT" >/dev/null
for a in "$APP" "/Applications/长截图切分.app" "/Applications/格式互转.app"; do
  [ -d "$a" ] || { say "MISSING: $a"; exit 1; }
  xattr -dr com.apple.quarantine "$a" || true
  codesign --verify --strict "$a" && say "codesign ok: $(basename "$a")"
done
codesign -dv "$APP" 2>&1 | grep -E '^(Signature|TeamIdentifier)=' | sed 's/^/[smoke]   /' | tee -a "$LOG" || true
spctl -a -vv "$APP" 2>&1 | sed 's/^/[smoke]   gatekeeper: /' | tee -a "$LOG" || true   # expected: rejected (not notarized)

# Settings before first start: both servers (in and out of office) on 127.0.0.1 ports nobody listens on (18831-18834).
RES="$APP/Contents/Resources"
mkdir -p "$APPDATA"
"$RES/python/bin/python3" -I -c '
import copy, json, sys
sys.path.insert(0, sys.argv[1])
from lawbench.settings import DEFAULTS
s = copy.deepcopy(DEFAULTS)
s["servers"] = {"llm_base_url": "http://127.0.0.1:18831/v1", "prep_base_url": "http://127.0.0.1:18832",
                "llm_alt_base_url": "http://127.0.0.1:18833/v1", "prep_alt_base_url": "http://127.0.0.1:18834"}
open(sys.argv[2], "w", encoding="utf-8").write(json.dumps(s, ensure_ascii=False, indent=2))
' "$RES/service" "$APPDATA/settings.json"
say "settings: servers -> 127.0.0.1:18831-18834 (dead ports)"

"$APP/Contents/MacOS/$NAME" > "$OUT/app-stdout.log" 2>&1 &
PID=$!
say "started pid $PID"
# Connections of every process of the app, sampled each second from start to exit (review P3-4)
( while kill -0 "$PID" 2>/dev/null; do
    # the subshell inherits set -e: pgrep / lsof exit 1 when there is nothing to report (review P2-B)
    p="$(pgrep -f "/Applications/$NAME.app" | paste -sd, -)" || true
    if [ -n "$p" ]; then lsof -nP -a -p "$p" -i 2>/dev/null | awk 'NR > 1' || true; fi
    sleep 1
  done ) > "$OUT/connections-raw.txt" &
SAMPLER=$!

# Window of our process (owner name only; window titles would need screen-recording permission)
cat > "$OUT/windows.swift" <<'SWIFT'
import CoreGraphics
let list = CGWindowListCopyWindowInfo([.optionOnScreenOnly], kCGNullWindowID) as? [[String: Any]] ?? []
let mine = list.filter { ($0[kCGWindowOwnerName as String] as? String) == CommandLine.arguments[1] && (($0[kCGWindowLayer as String] as? Int) ?? 1) == 0 }
print(mine.count)
SWIFT
n=0
for _ in $(seq 1 60); do
  n="$(swift "$OUT/windows.swift" "$NAME" 2>/dev/null || echo 0)"
  [ "${n:-0}" -ge 1 ] && break
  kill -0 "$PID" 2>/dev/null || { say "app exited early"; tail -n 50 "$OUT/app-stdout.log" | sed 's/^/[smoke]   /'; exit 1; }
  sleep 3
done
say "windows of $NAME: $n"
[ "${n:-0}" -ge 1 ] || { say "FAIL: no window of $NAME within 3 minutes"; exit 1; }
sleep 15   # let the first-run page and the service settle
screencapture -x "$OUT/smoke-first-run.png" && [ -s "$OUT/smoke-first-run.png" ] || { say "FAIL: screencapture"; exit 1; }

# Start-up self-check and service state from the metadata-only plugin logs (no material names by design, Spec 4.5)
if ls "$APPDATA/logs"/plugins-*.log >/dev/null 2>&1; then
  cp "$APPDATA/logs"/plugins-*.log "$OUT/"
  grep -hE '"event": ?"(selfcheck|service|config)[^"]*"' "$APPDATA/logs"/plugins-*.log | tail -n 40 | sed 's/^/[smoke]   /' | tee -a "$LOG" || true
else
  say "no plugin logs under $APPDATA/logs"
fi

# The app's processes must be found, otherwise the connection record means nothing (review P3-4)
PIDS="$(pgrep -f "/Applications/$NAME.app" | paste -sd, -)" || true
[ -n "$PIDS" ] || { say "FAIL: no process of $NAME found"; exit 1; }
say "processes: $PIDS"

osascript -e "tell application \"$NAME\" to quit" >/dev/null 2>&1 || true
sleep 5
pkill -f "/Applications/$NAME.app" || true
wait "$SAMPLER" 2>/dev/null || true

# Every connection seen during the run: only 127.0.0.1 is allowed (Spec 14.3)
sort -u "$OUT/connections-raw.txt" > "$OUT/connections.txt"
say "connections: $(grep -c . "$OUT/connections.txt" || true) distinct lines over the run (connections.txt)"
# an empty record proves nothing: the Host's own web server must show up listening on 127.0.0.1 (review P2-B)
grep -qE '127\.0\.0\.1:[0-9]+ \(LISTEN\)' "$OUT/connections.txt" || { say "FAIL: connection record empty or without the 127.0.0.1 listener"; exit 1; }
# NAME column: "local" for listeners, "local->remote" for connections; judge the remote side when there is one
if awk '{ n = $9; i = index(n, "->"); if (i) n = substr(n, i + 2); print n }' "$OUT/connections.txt" \
     | grep -vE '^(127\.0\.0\.1|\[::1\]|localhost|\*)[:.]' | grep -E . ; then
  say "FAIL: a connection to something other than 127.0.0.1"; exit 1
fi
say "connections: 127.0.0.1 only"
say "done"
