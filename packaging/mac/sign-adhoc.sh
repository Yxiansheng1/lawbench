#!/usr/bin/env bash
# lawbench T28: ad-hoc signature for the packaged macOS app (order 1424 ruling 3).
# Called by electron-builder's afterPack (dsh-patches P-22, LAWBENCH_MAC_SIGN_SCRIPT) with the .app path.
# Inside out, no --deep: every Mach-O file, then every nested bundle, then the app itself. LibreOffice.app keeps
# The Document Foundation's own signature (it is sealed by the outer signature like any other resource).
# Resources/app.asar.unpacked is left byte-for-byte as DSH prepared it (eighth run): DSH's own check (verifyRuntimeArchive)
# compares every unpacked file's sha256 and the exact file list with its sealed inventory, so re-signing in place or a
# bundle's new _CodeSignature/ would fail it. Those Mach-O files already carry signatures; they are only verified here.
# Usage: sign-adhoc.sh <path to .app>
set -euo pipefail
APP="${1:?usage: sign-adhoc.sh <app>}"
echo "sign-adhoc: app = $APP"
[ -d "$APP/Contents" ] || { echo "sign-adhoc: not an app bundle: $APP" >&2; ls -la "$(dirname "$APP")" >&2 || true; exit 2; }
# a dangling symlink makes the final verify fail with "<app>: No such file or directory" (sixth run): say which first
dangling="$(find "$APP" -type l ! -exec test -e {} \; -print)"
if [ -n "$dangling" ]; then echo "$dangling" | sed 's/^/sign-adhoc: dangling link: /' >&2; echo "sign-adhoc: remove the dangling links above (codesign --verify --strict rejects them)" >&2; exit 3; fi
LO_REL="Contents/Resources/tools/LibreOffice.app"
LO="$APP/$LO_REL"
UNPACKED="$APP/Contents/Resources/app.asar.unpacked"
sign() { codesign --force --sign - --timestamp=none "$1"; }

n=0
# 1. Mach-O files (libraries, extension modules, executables) outside LibreOffice.app and app.asar.unpacked
while IFS= read -r -d '' f; do
  if file -b "$f" | grep -q 'Mach-O'; then sign "$f"; n=$((n + 1)); fi
done < <(find "$APP/Contents" -type f \( -name '*.dylib' -o -name '*.so' -o -name '*.node' -o -perm -u+x \) \
           -not -path "$LO/*" -not -path "$UNPACKED/*" -print0)
# 2. nested bundles, deepest first (Electron helpers and frameworks, the small parts DSH ships)
b=0
while IFS= read -r -d '' d; do
  sign "$d"; b=$((b + 1))
done < <(find "$APP/Contents" -depth -type d \( -name '*.app' -o -name '*.framework' -o -name '*.xpc' \) \
           -not -path "$LO" -not -path "$LO/*" -not -path "$UNPACKED/*" -print0)
# 1b. app.asar.unpacked: verify, never modify; a bundle there would need its own signature files, so none is allowed
u=0; bad=""
if [ -d "$UNPACKED" ]; then
  nested="$(find "$UNPACKED" -type d \( -name '*.app' -o -name '*.framework' -o -name '*.xpc' \) -print)"
  if [ -n "$nested" ]; then
    echo "$nested" | sed 's/^/sign-adhoc: bundle inside app.asar.unpacked: /' >&2
    echo "sign-adhoc: a bundle there cannot be signed without adding files DSH's runtime check rejects" >&2; exit 5
  fi
  while IFS= read -r -d '' f; do
    if file -b "$f" | grep -q 'Mach-O'; then
      u=$((u + 1))
      codesign --verify --strict "$f" 2>/dev/null || bad="$bad$f"$'\n'
    fi
  done < <(find "$UNPACKED" -type f \( -name '*.dylib' -o -name '*.so' -o -name '*.node' -o -perm -u+x \) -print0)
  if [ -n "$bad" ]; then printf '%s' "$bad" | sed 's/^/sign-adhoc: unsigned or invalid in app.asar.unpacked: /' >&2; exit 6; fi
fi
# 3. the app
sign "$APP"
echo "sign-adhoc: $n Mach-O files, $b nested bundles, app signed ad-hoc; $u Mach-O files in app.asar.unpacked verified, left untouched"
codesign --verify --strict --verbose=2 "$APP" || {
  echo "sign-adhoc: verify failed; details:" >&2
  codesign --verify --strict --deep --verbose=4 "$APP" 2>&1 | tail -n 40 >&2 || true
  exit 4
}
if [ -d "$LO" ]; then
  # LibreOffice keeps its Developer ID signature (TeamIdentifier present, not "adhoc")
  codesign -dv "$LO" 2>&1 | grep -E '^(Authority|TeamIdentifier|Signature)=' | head -n 3 || true
  codesign --verify --strict "$LO" && echo "sign-adhoc: LibreOffice.app signature intact"
fi
