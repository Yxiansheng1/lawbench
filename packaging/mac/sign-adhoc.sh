#!/usr/bin/env bash
# lawbench T28: ad-hoc signature for the packaged macOS app (order 1424 ruling 3).
# Called by electron-builder's afterPack (dsh-patches P-22, LAWBENCH_MAC_SIGN_SCRIPT) with the .app path.
# Inside out, no --deep: every Mach-O file, then every nested bundle, then the app itself. LibreOffice.app keeps
# The Document Foundation's own signature (it is sealed by the outer signature like any other resource).
# Usage: sign-adhoc.sh <path to .app>
set -euo pipefail
APP="${1:?usage: sign-adhoc.sh <app>}"
[ -d "$APP/Contents" ] || { echo "sign-adhoc: not an app bundle: $APP" >&2; exit 2; }
LO_REL="Contents/Resources/tools/LibreOffice.app"
LO="$APP/$LO_REL"
sign() { codesign --force --sign - --timestamp=none "$1"; }

n=0
# 1. Mach-O files (libraries, extension modules, executables) outside LibreOffice.app
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q 'Mach-O'; then sign "$f"; n=$((n + 1)); fi
done < <(find "$APP/Contents" -type f \( -name '*.dylib' -o -name '*.so' -o -name '*.node' -o -perm -u+x \) \
           -not -path "$LO/*" -print0)
# 2. nested bundles, deepest first (Electron helpers and frameworks, the small parts DSH ships)
b=0
while IFS= read -r -d '' d; do
  sign "$d"; b=$((b + 1))
done < <(find "$APP/Contents" -depth -type d \( -name '*.app' -o -name '*.framework' -o -name '*.xpc' \) \
           -not -path "$LO" -not -path "$LO/*" -print0)
# 3. the app
sign "$APP"
echo "sign-adhoc: $n Mach-O files, $b nested bundles, app signed ad-hoc"
codesign --verify --strict --verbose=2 "$APP"
if [ -d "$LO" ]; then
  # LibreOffice keeps its Developer ID signature (TeamIdentifier present, not "adhoc")
  codesign -dv "$LO" 2>&1 | grep -E '^(Authority|TeamIdentifier|Signature)=' | head -n 3 || true
  codesign --verify --strict "$LO" && echo "sign-adhoc: LibreOffice.app signature intact"
fi
