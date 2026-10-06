#!/usr/bin/env bash
# lawbench macOS (Apple silicon) build, T28. The counterpart of packaging/build.ps1 (same payload, same steps), run on
# a Mac (GitHub Actions macos-15 arm64, or any Apple silicon Mac). No keys, passwords, user names or case files are read
# or written; no secrets are needed (ad-hoc signature, no notarization, no update feed).
#
# Usage (repository root):
#   bash packaging/mac/build.sh                 # all steps
#   bash packaging/mac/build.sh python tools    # only these steps, in this order
#   bash packaging/mac/build.sh --list
# Environment:
#   LAWBENCH_TOKENIZER=<tokenizer.json>   the 6000D tokenizer (not public; versions.lock [client] sha256). Without it the
#   LAWBENCH_ALLOW_NO_TOKENIZER=1         build stops, unless this is set: the service then estimates token counts
#                                         (smoke builds only, recorded in build-mac.txt).
#   LAWBENCH_SIGN_IDENTITY=<identity>     reserved for a Developer ID build (owner N74); not implemented in phase 1.
# Network: downloads the pinned payloads ([mac] in packaging/versions.lock, checked against their sha256), Python wheels
# from PyPI (macOS arm64 builds of the [client.pip] pins) and npm packages through pnpm. The packaged app never connects
# anywhere but the configured servers and 127.0.0.1.
set -euo pipefail
export LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HERE="$ROOT/packaging/mac"
DSH="$ROOT/dsh"
STAGE="${STAGE:-$HERE/stage}"
CACHE="${CACHE:-$HERE/cache}"
OUT="${OUT:-$HERE/out}"
WORK="$HERE/work"
LOCK="$ROOT/packaging/versions.lock"
PNPM=(corepack pnpm@11.7.0)
APP_ID="cn.lianyue.lawbench"
REPORT="$OUT/build-mac.txt"
mkdir -p "$STAGE" "$CACHE" "$OUT" "$WORK"

say() { echo "[build-mac] $*"; echo "$*" >> "$REPORT"; }
die() { echo "[build-mac] ERROR: $*" >&2; exit 1; }
reset_dir() { rm -rf "$1"; mkdir -p "$1"; }
sha256() { shasum -a 256 "$1" | awk '{print $1}'; }

# [mac] entry fields: component, version, url, sha256 (two or more spaces between fields)
lock_field() {  # lock_field <component> <n>
  awk -v c="$1" -v n="$2" '
    /^\[/ { sec = $0; next }
    sec ~ /^\[mac\]/ && $0 !~ /^#/ && NF { split($0, f, /  +/); if (f[1] == c) { print f[n]; exit } }' "$LOCK"
}
# Download once into the cache, check the pinned sha256 every time.
fetch() {  # fetch <component> -> prints the cached file path
  local url sha file
  url="$(lock_field "$1" 3)"; sha="$(lock_field "$1" 4)"
  [ -n "$url" ] && [ -n "$sha" ] || die "no [mac] entry for $1 in packaging/versions.lock"
  file="$CACHE/$sha-$(basename "${url%%\?*}")"
  if [ ! -f "$file" ]; then
    curl -fsSL --retry 3 -o "$file.part" "$url"
    mv "$file.part" "$file"
  fi
  [ "$(sha256 "$file")" = "$sha" ] || { rm -f "$file"; die "$1: sha256 mismatch for $url"; }
  echo "$file"
}

STEPS=(preflight dsh python tools smalltools skills engines lock scan package)

step_preflight() {
  [ "$(uname -s)" = Darwin ] || die "needs macOS"
  [ "$(uname -m)" = arm64 ] || die "needs Apple silicon (arm64)"
  node -v | grep -Eq '^v(2[2-9]|[3-9][0-9])\.' || die "Node 22+ required"
  command -v corepack >/dev/null || die "corepack missing"
  local ui svc
  ui="$(sed -nE "s/.*PRODUCT_VERSION = '([^']+)'.*/\1/p" "$ROOT/dsh-ext/shared/product.ts")"
  svc="$(sed -nE 's/^version = "([^"]+)"/\1/p' "$ROOT/service/pyproject.toml")"
  [ -n "$ui" ] && [ "$ui" = "$svc" ] || die "version mismatch: dsh-ext/shared/product.ts '$ui' vs service/pyproject.toml '$svc'"
  git -C "$ROOT" diff --quiet -- contracts || die "contracts must be committed"
  say "preflight: macOS $(sw_vers -productVersion) $(uname -m), node $(node -v), version $svc, commit $(git -C "$ROOT" rev-parse --short HEAD)"
}

step_dsh() {
  [ -f "$DSH/package.json" ] || die "dsh submodule not checked out (git submodule update --init dsh)"
  if [ -n "$(git -C "$DSH" status --porcelain)" ]; then
    say "dsh: working tree already modified, assuming the patches are applied"
  else
    # same order as dsh-patches/PATCHES.md (the lines 'git -C dsh apply ..\dsh-patches\<name>.patch')
    local p
    while IFS= read -r p; do
      git -C "$DSH" apply "$ROOT/dsh-patches/$p" || die "dsh: patch $p does not apply to the dsh checkout"
    done < <(sed -nE 's/^git -C dsh apply \.\.[\\]dsh-patches[\\]([^ ]+\.patch).*/\1/p' "$ROOT/dsh-patches/PATCHES.md" | tr -d '\r')
    say "dsh: patches applied ($(sed -nE 's/^git -C dsh apply .*[\\](P-[0-9]+)-.*/\1/p' "$ROOT/dsh-patches/PATCHES.md" | tr -d '\r' | tr '\n' ' '))"
  fi
  cp -R "$ROOT/packaging/brand/desktop/." "$DSH/apps/desktop/"
  (cd "$DSH" && CI=true "${PNPM[@]}" install --frozen-lockfile && CI=true "${PNPM[@]}" run build)
  (cd "$ROOT/dsh-ext" && CI=true "${PNPM[@]}" install --frozen-lockfile && node scripts/build.mjs)
}

# Client Python: python-build-standalone 3.12.14 aarch64 (the archive DSH pins for mac-arm64), our pinned packages in its
# own site-packages; the service runs as python/bin/python3 -I -m lawbench (dsh-ext/host/install-layout.ts).
pins_file() {
  awk '/^\[/ { sec = $0; next } sec ~ /^\[client\.pip\]/ && /^[A-Za-z0-9_.-]+==/ { print $1 }' "$LOCK" \
    | grep -viE '^pywin32(-ctypes)?==' > "$1"
  [ -s "$1" ] || die "no [client.pip] pins in packaging/versions.lock"
}
step_python() {
  local archive py req
  archive="$(fetch python)"
  rm -rf "$STAGE/python"
  tar -xzf "$archive" -C "$STAGE"
  py="$STAGE/python/bin/python3"
  "$py" -c 'import sys, platform; assert sys.version_info[:2] == (3, 12) and platform.machine() == "arm64"'
  req="$WORK/requirements-mac.txt"
  pins_file "$req"
  mkdir -p "$CACHE/wheels"
  "$py" -I -m pip download --disable-pip-version-check --only-binary=:all: -d "$CACHE/wheels" -r "$req"
  "$py" -I -m pip install --disable-pip-version-check --no-index --no-compile --no-warn-script-location \
    --find-links "$CACHE/wheels" -r "$req"
  (cd "$CACHE/wheels" && shasum -a 256 *.whl) > "$OUT/pip-mac-wheels.txt"
  # pip's console scripts embed the build machine's interpreter path: broken once installed
  find "$STAGE/python/bin" -type f ! -name 'python3*' -delete
  local site
  site="$("$py" -I -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
  cp "$ROOT/packaging/python/sitecustomize.py" "$site/"
  # service and contracts (REPO_ROOT = parents[2] of service/lawbench/config.py); keep a tokenizer placed earlier
  local keep=""
  if [ -f "$STAGE/service/lawbench/llm/tokenizer.json" ]; then keep="$WORK/tokenizer.keep"; mv "$STAGE/service/lawbench/llm/tokenizer.json" "$keep"; fi
  reset_dir "$STAGE/service"
  cp -R "$ROOT/service/lawbench" "$STAGE/service/lawbench"
  [ -n "$keep" ] && mv "$keep" "$STAGE/service/lawbench/llm/tokenizer.json"
  reset_dir "$STAGE/contracts"
  cp -R "$ROOT/contracts/." "$STAGE/contracts/"
  find "$STAGE/service" "$STAGE/contracts" "$STAGE/python" -name '__pycache__' -type d -prune -exec rm -rf {} +
  find "$STAGE/service" "$STAGE/contracts" "$STAGE/python" -name '*.py[co]' -delete
  # The service package on sys.path (second run: "No module named lawbench"): Windows does it with python312._pth
  # ("..\service"); macOS has no ._pth, and -I (implies -P) never adds the working directory. A .pth file in the
  # interpreter's own site-packages is still read under -I; its relative line resolves against site-packages, so the
  # path is computed from the real layout (stage/python/lib/python3.12/site-packages -> stage/service).
  local rel
  rel="$("$py" -I -B -c 'import os, sys; print(os.path.relpath(sys.argv[1], sys.argv[2]))' "$STAGE/service" "$site")"
  printf '%s\n' "$rel" > "$site/lawbench.pth"
  [ -f "$site/sitecustomize.py" ] || die "sitecustomize.py missing in $site"
  # Self-check with the runtime's own command line (install-layout.ts: python3 -I -B -m lawbench, cwd Resources/service)
  # and from an unrelated directory: lawbench must come from stage/service, nothing from the user's Library/Python.
  local where
  where="$(cd / && "$py" -I -B -c 'import lawbench, sys; print(lawbench.__file__); assert not any("Library/Python" in p for p in sys.path), sys.path')" \
    || die "python: 'import lawbench' failed with -I (lawbench.pth line: $rel)"
  case "$where" in "$STAGE/service/lawbench/"*) ;; *) die "python: lawbench imported from $where, not from stage/service" ;; esac
  (cd "$STAGE/service" && "$py" -I -B -m lawbench --help >/dev/null) || die "python: 'python3 -I -B -m lawbench --help' failed"
  say "python: lawbench.pth -> $rel; lawbench imports from stage/service; -m lawbench --help ok"
  say "python: $(lock_field python 2) aarch64, $(wc -l < "$req" | tr -d ' ') pinned packages (pywin32 left out), wheels: out/pip-mac-wheels.txt"
}

step_tools() {
  local dmg mnt zip tmp
  dmg="$(fetch libreoffice)"
  mnt="$WORK/lo-mnt"; mkdir -p "$mnt"
  hdiutil attach -nobrowse -readonly -noautoopen -mountpoint "$mnt" "$dmg" >/dev/null || die "tools: hdiutil could not mount the LibreOffice dmg"
  rm -rf "$STAGE/tools/LibreOffice.app"; mkdir -p "$STAGE/tools"
  ditto "$mnt/LibreOffice.app" "$STAGE/tools/LibreOffice.app" || { hdiutil detach "$mnt" >/dev/null || true; die "tools: LibreOffice.app not found in the dmg or copy failed"; }
  hdiutil detach "$mnt" >/dev/null
  codesign --verify --strict "$STAGE/tools/LibreOffice.app" || die "LibreOffice.app signature broken after copy"
  zip="$(fetch pandoc)"
  tmp="$WORK/pandoc"; reset_dir "$tmp"
  ditto -x -k "$zip" "$tmp"
  reset_dir "$STAGE/tools/pandoc/bin"
  local pbin; pbin="$(find "$tmp" -type f -path '*/bin/pandoc' | head -n 1)"
  [ -n "$pbin" ] || die "tools: no bin/pandoc inside the pandoc zip"
  cp "$pbin" "$STAGE/tools/pandoc/bin/pandoc"
  chmod +x "$STAGE/tools/pandoc/bin/pandoc"
  # GPL: ship pandoc's license files next to it (same rule as build.ps1, T20 review P2-1)
  cp "$(fetch pandoc-copying)" "$STAGE/tools/pandoc/COPYING.md"
  cp "$(fetch pandoc-copyright)" "$STAGE/tools/pandoc/COPYRIGHT"
  "$STAGE/tools/pandoc/bin/pandoc" --version | head -n 1 | grep -q "pandoc $(lock_field pandoc 2)" || die "pandoc version"
  if [ -n "${LAWBENCH_TOKENIZER:-}" ] && [ -f "$LAWBENCH_TOKENIZER" ]; then
    mkdir -p "$STAGE/service/lawbench/llm"
    cp "$LAWBENCH_TOKENIZER" "$STAGE/service/lawbench/llm/tokenizer.json"
    say "tokenizer: sha256 $(sha256 "$LAWBENCH_TOKENIZER")"
  elif [ "${LAWBENCH_ALLOW_NO_TOKENIZER:-}" = 1 ]; then
    say "tokenizer: NOT INCLUDED (LAWBENCH_ALLOW_NO_TOKENIZER=1; token counts are estimated; smoke build only)"
  else
    die "tokenizer.json not given (LAWBENCH_TOKENIZER=<file>, or LAWBENCH_ALLOW_NO_TOKENIZER=1 for a smoke build)"
  fi
  say "tools: LibreOffice $(lock_field libreoffice 2) (signature kept), pandoc $(lock_field pandoc 2)"
}

# The two small tools as windowed PyInstaller apps beside the main app in the disk image (order 1424 ruling 4), names as
# on Windows. Built with a separate copy of the same Python (not shipped).
step_smalltools() {
  local bt bpy want pins t name
  bt="$WORK/buildpy"; reset_dir "$bt"
  tar -xzf "$(fetch python)" -C "$bt"
  bpy="$bt/python/bin/python3"
  want='pillow|numpy|pypdfium2|pypdf|python-docx|openpyxl|lxml|typing-extensions|typing_extensions|et-xmlfile|et_xmlfile'
  pins="$(awk '/^\[/ { sec = $0; next } sec ~ /^\[client\.pip\]/ && /==/ { print $1 }' "$LOCK" | grep -iE "^($want)==" | sort -u)"
  # PyInstaller from PyPI, newest at build time (build tool, not shipped); its version goes into build-mac.txt
  # shellcheck disable=SC2086
  "$bpy" -I -m pip install --disable-pip-version-check --no-warn-script-location pyinstaller $pins
  say "small tools: $("$bpy" -I -m PyInstaller --version | sed 's/^/PyInstaller /')"
  reset_dir "$OUT/dmg-apps"
  for t in splitter convert; do
    case "$t" in splitter) name="长截图切分" ;; convert) name="格式互转" ;; esac
    printf 'from %s.app import main\nmain()\n' "$t" > "$WORK/$t-main.py"
    "$bpy" -I -m PyInstaller --noconfirm --clean --windowed --onedir --name "$name" \
      --osx-bundle-identifier "$APP_ID.$t" \
      --distpath "$WORK/dist-$t" --workpath "$WORK/build-$t" --specpath "$WORK" \
      --paths "$ROOT/tools" --paths "$ROOT/tools/$t" \
      --hidden-import pypdfium2 --collect-all pypdfium2 --collect-all pypdfium2_raw \
      "$WORK/$t-main.py" > "$OUT/pyinstaller-$t.txt" 2>&1 || { tail -n 30 "$OUT/pyinstaller-$t.txt"; die "small tools: PyInstaller failed for $t (out/pyinstaller-$t.txt)"; }
    [ -d "$WORK/dist-$t/$name.app" ] || die "small tool not built: $t"
    bash "$HERE/sign-adhoc.sh" "$WORK/dist-$t/$name.app" > "$OUT/sign-$t.txt" 2>&1 || { tail -n 20 "$OUT/sign-$t.txt"; die "small tools: ad-hoc signing failed for $name.app (out/sign-$t.txt)"; }
    ditto "$WORK/dist-$t/$name.app" "$OUT/dmg-apps/$name.app"
  done
  say "small tools: 长截图切分.app, 格式互转.app (ad-hoc signed, beside the app in the dmg)"
}

step_skills() {
  reset_dir "$STAGE/skills"
  # -E -s rather than -I: install.py imports its sibling modules from the script folder (-I would drop it from sys.path)
  "$STAGE/python/bin/python3" -E -s -B "$ROOT/skills/_scripts/install.py" --out "$STAGE/skills" || die "skills: install.py failed"
}

step_engines() {
  reset_dir "$STAGE/engines"
  cp -R "$ROOT/engines/." "$STAGE/engines/"
  # the Windows-only invoice runtime is not used on macOS (order 1424 ruling 1: invoice sorting unavailable on Mac)
  rm -f "$STAGE/engines/invoice-ledger/vendor/env-win_amd64.zip"
}

step_lock() {
  cp "$ROOT/packaging/THIRD-PARTY-LICENSES.md" "$STAGE/THIRD-PARTY-LICENSES.md"
  {
    echo "macOS payload ($(date -u +%FT%TZ), commit $(git -C "$ROOT" rev-parse HEAD))"
    for c in python libreoffice pandoc pandoc-copying pandoc-copyright; do
      printf '%-18s %-18s %s\n' "$c" "$(lock_field "$c" 2)" "$(lock_field "$c" 4)"
    done
  } > "$OUT/payload-mac.txt"
}

# Keys and user names must not be in the package (T28 acceptance): scan every text file in stage (LibreOffice.app is the
# vendor's signed release, left out) for Key-like strings, the .env.local variable names, and the build machine's home
# path (/Users/<name>: a build path baked into a file would carry the user name).
scan_dir() {  # scan_dir <dir> <label> [home-path hits only warn: 1]
  local hits="$WORK/scan-hits.txt" home="$OUT/scan-$2-home-paths.txt"
  : > "$hits"
  grep -rlaE 'sk-[A-Za-z0-9]{20,}|LAWFIRM_TEST_KEY_[AB]=|PREP395_BASE=|LAWFIRM_LLM_BASE=|BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY' \
    "$1" --exclude-dir=LibreOffice.app >> "$hits" || true
  if [ -s "$hits" ]; then sed 's/^/  hit: /' "$hits"; die "scan ($2): key-like strings found (see the hit lines above)"; fi
  grep -rlaF -- "$HOME/" "$1" --exclude-dir=LibreOffice.app > "$home" || true
  if [ -s "$home" ]; then
    sed 's/^/  home path in: /' "$home"
    # on GitHub's runner the home is /Users/runner (no person's name): recorded for the next round, not fatal there
    [ "${3:-0}" = 1 ] && [ "${GITHUB_ACTIONS:-}" = true ] || die "scan ($2): the build home path $HOME is baked into files (see above, out/$(basename "$home"))"
    say "scan ($2): WARNING $(wc -l < "$home" | tr -d ' ') files carry the runner's home path (out/$(basename "$home"))"
  else rm -f "$home"; fi
  say "scan ($2): no key-like strings ($(find "$1" -type f | wc -l | tr -d ' ') files, LibreOffice.app excluded)"
}
step_scan() { scan_dir "$STAGE" stage; }

step_package() {
  local need missing=()
  for need in python/bin/python3 service/lawbench/__main__.py contracts/VERSION skills engines \
              tools/LibreOffice.app/Contents/MacOS/soffice tools/pandoc/bin/pandoc tools/pandoc/COPYING.md THIRD-PARTY-LICENSES.md; do
    [ -e "$STAGE/$need" ] || missing+=("$need")
  done
  [ ${#missing[@]} -eq 0 ] || die "payload incomplete: ${missing[*]}"
  if [ -n "${LAWBENCH_SIGN_IDENTITY:-}" ]; then die "LAWBENCH_SIGN_IDENTITY: Developer ID signing is reserved for a later phase (owner N74)"; fi
  # DSH's packager reads its settings from apps/desktop/.env.macos only (git-ignored). No secrets: ad-hoc build,
  # no update feed; the mandatory-update origin is only validated, never shipped (P-4), so it is the .invalid domain.
  printf '%s\n' '# Written by packaging/mac/build.sh (lawbench T28). No secrets. Ad-hoc build without update feed.' \
    "DSH_DESKTOP_APP_ID=$APP_ID" 'DSH_DESKTOP_AUTO_UPDATE_ENV=production' \
    'DSH_DESKTOP_MANDATORY_UPDATE_PROD_ORIGIN=https://update.invalid' 'DSH_DESKTOP_MACOS_PACK_CONCURRENCY=4' \
    > "$DSH/apps/desktop/.env.macos"
  local apps=""
  if [ -d "$OUT/dmg-apps" ]; then apps="$(find "$OUT/dmg-apps" -maxdepth 1 -name '*.app' | sort | paste -sd: -)"; fi
  # third-party npm versions of the bundled runtime pinned by packaging/runtime-lock/pnpm-lock.yaml (same as build.ps1)
  local pinned="$ROOT/packaging/runtime-lock/pnpm-lock.yaml" resolved="$OUT/runtime-pnpm-lock.yaml"
  rm -f "$resolved"
  (cd "$DSH/apps/desktop" && CI=true LAWBENCH_MAC_ADHOC=1 LAWBENCH_STAGE_DIR="$STAGE" \
     LAWBENCH_MAC_SIGN_SCRIPT="$HERE/sign-adhoc.sh" LAWBENCH_MAC_DMG_APPS="$apps" \
     LAWBENCH_RUNTIME_LOCK="$([ -f "$pinned" ] && echo "$pinned")" LAWBENCH_RUNTIME_LOCK_OUT="$resolved" \
     "${PNPM[@]}" run package:mac:arm64) \
    || die "package: DSH packaging failed; its step journal is dsh/apps/desktop/.desktop-build/packaging-runs/*/events.jsonl (in the build logs artifact); a signing error there comes from sign-adhoc.sh (afterPack)"
  if [ -f "$pinned" ] && [ -f "$resolved" ]; then
    # recorded, not fatal on the first Mac builds: macOS may resolve platform-only packages the Windows lock lacks
    if node "$ROOT/packaging/runtime-lock-compare.mjs" "$pinned" "$resolved" >> "$REPORT" 2>&1; then say "runtime lock: same versions as packaging/runtime-lock"
    else say "runtime lock: DIFFERS from packaging/runtime-lock (see above; out/runtime-pnpm-lock.yaml)"; fi
  fi
  local dmg
  dmg="$(find "$DSH/apps/desktop/.desktop-build/targets" -name '*.dmg' -type f -exec stat -f '%m %N' {} + | sort -rn | head -n 1 | cut -d' ' -f2-)"
  [ -n "$dmg" ] || die "dmg not found under dsh/apps/desktop/.desktop-build/targets"
  # order 1526 P3-5: a package without the tokenizer says so in its file name
  local name; name="$(basename "$dmg")"
  [ -f "$STAGE/service/lawbench/llm/tokenizer.json" ] || name="${name%.dmg}-smoke-no-tokenizer.dmg"
  cp "$dmg" "$OUT/$name"
  dmg="$OUT/$name"
  (cd "$OUT" && shasum -a 256 "$(basename "$dmg")" > "$(basename "$dmg").sha256")
  local app
  app="$(find "$DSH/apps/desktop/.desktop-build/targets" -maxdepth 4 -type d -path '*mac-arm64/*.app' | head -n 1)"
  [ -n "$app" ] || die "package: no mac-arm64/*.app under dsh/apps/desktop/.desktop-build/targets"
  scan_dir "$app/Contents" app 1
  say "dmg: $(basename "$dmg")  $(( $(stat -f%z "$dmg") / 1048576 )) MB  sha256 $(sha256 "$dmg")"
}

if [ "${1:-}" = --list ]; then printf '%s\n' "${STEPS[@]}"; exit 0; fi
todo=("$@"); [ ${#todo[@]} -gt 0 ] || todo=("${STEPS[@]}")
for s in "${todo[@]}"; do
  declare -F "step_$s" >/dev/null || die "unknown step: $s (use --list)"
  echo "[build-mac] == $s ($(date +%H:%M:%S))"
  t0=$SECONDS
  "step_$s"
  echo "[build-mac] == $s done in $((SECONDS - t0)) s"
done
say "done"
