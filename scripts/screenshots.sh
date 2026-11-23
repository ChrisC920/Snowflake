#!/bin/sh
# Capture every UI preview state in light and dark mode, for reviewing UI changes.
#
#   scripts/screenshots.sh [state ...]     (default: all states)
#
# Output: build/screenshots/<state>-<appearance>.png
#   - <name>.png         real on-screen capture via `screencapture` (faithful Liquid Glass).
#                        Needs Screen Recording permission for the app running this script
#                        (System Settings › Privacy & Security › Screen & System Audio Recording).
#   - <name>.render.png  in-process render (no permission needed; drops glass surfaces such as the sidebar).
#
# Requires a Debug build: `make build` (or run via `make screenshots`).
set -eu
cd "$(dirname "$0")/.."

APP=build/DerivedData/Build/Products/Debug/Snowflake.app
BIN="$APP/Contents/MacOS/Snowflake"
OUT=build/screenshots
ALL="panel panel-expanded panel-empty settings-general settings-modules settings-appearance settings-keep-awake settings-about"
STATES=${*:-$ALL}

[ -x "$BIN" ] || { echo "No Debug build at $APP. Run: make build" >&2; exit 1; }
rm -rf "$OUT"
mkdir -p "$OUT"

captured=0
rendered=0
denied=0
for state in $STATES; do
  for appearance in dark light; do
    name="$state-$appearance"
    ready="$OUT/.$name.ready"
    rm -f "$ready"
    # Launch through LaunchServices so the app is activated (an inactive window renders dimmed).
    open -n "$APP" --args -ui-preview "$state" -ui-appearance "$appearance" \
      -ui-ready-file "$PWD/$ready" -ui-snapshot "$PWD/$OUT/$name.render.png"

    tries=0
    while [ ! -s "$ready" ] && [ $tries -lt 150 ]; do
      sleep 0.1
      tries=$((tries + 1))
    done

    if [ ! -s "$ready" ]; then
      echo "✗ $name: preview did not start" >&2
      pkill -f "Snowflake.app/Contents/MacOS/Snowflake -ui-preview $state " 2>/dev/null || true
      continue
    fi
    read -r window pid <"$ready"
    [ -f "$OUT/$name.render.png" ] && rendered=$((rendered + 1))
    if screencapture -x -o -l "$window" "$OUT/$name.png" 2>/dev/null && [ -s "$OUT/$name.png" ]; then
      captured=$((captured + 1))
      echo "✓ $name"
    else
      rm -f "$OUT/$name.png"
      denied=$((denied + 1))
      echo "• $name (render only)"
    fi
    kill "$pid" 2>/dev/null || true
    while kill -0 "$pid" 2>/dev/null; do sleep 0.1; done
    rm -f "$ready"
  done
done

echo
echo "Screenshots: $captured captured, $rendered rendered → $OUT/"
if [ $denied -gt 0 ]; then
  echo "On-screen capture was unavailable for $denied. Grant Screen Recording to the app running this"
  echo "script for faithful captures; the .render.png files show content layout but not glass."
fi
