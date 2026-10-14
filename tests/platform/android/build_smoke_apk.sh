#!/usr/bin/env bash
# Build the current tree as a SEPARATE Android package for the BlueStacks
# smoke test (BLD-01..03): org.omnipet.omnipetsmoketest, "Omnipet Smoke Test".
# The player's own org.omnipet.omnipet is never built, replaced or touched.
#
#   wsl -d Ubuntu -- bash /mnt/e/Omnipet/tests/platform/android/build_smoke_apk.sh [MODULE ...]
#
# Stages like build/build_android.ps1 (src, assets, android_src, the
# manifest, main_android.py as main.py, an empty save/) in its own WSL folder
# (~/omnipet_smoke_build), reusing a copy of the release build's .buildozer
# cache. Unlike a release it ships a few modules (default: the test party's
# DMC PENC IC VB), so the app can get past the module check without the shop.
# The APK lands in /mnt/e/Omnipet/tmp/platform/android/. Then:
#
#   python -B tests/platform/android/android_smoke.py \
#       --install-test-apk tmp/platform/android/<apk> --test-package org.omnipet.omnipetsmoketest
set -euo pipefail

SRC=/mnt/e/Omnipet
D=~/omnipet_smoke_build
OUT=$SRC/tmp/platform/android
MODULES=("$@")
[ ${#MODULES[@]} -gt 0 ] || MODULES=(DMC PENC IC VB)

mkdir -p "$D" "$OUT"
if [ ! -d "$D/.buildozer" ]; then
    echo "[smoke-apk] copying the .buildozer cache (once)"
    cp -a ~/omnipet_build/.buildozer "$D/"
fi
echo "[smoke-apk] staging the current tree"
rsync -a --delete --exclude='__pycache__' --exclude='*.pyc' "$SRC/src/" "$D/src/"
rsync -a --delete "$SRC/assets/" "$D/assets/"
rsync -a --delete "$SRC/android_src/" "$D/android_src/"
python3 "$SRC/build/prepare_android_manifest.py" "$D/android_src"
cp "$SRC/main_android.py" "$D/main.py"
rm -rf "$D/save" "$D/modules"
mkdir -p "$D/save" "$D/modules"
for m in "${MODULES[@]}"; do
    if [ -d "$SRC/modules/$m" ]; then
        rsync -a --exclude='documentation' "$SRC/modules/$m/" "$D/modules/$m/"
        echo "[smoke-apk] module $m"
    else
        echo "[smoke-apk] no module $m"
    fi
done
sed -e 's/^package.name = .*/package.name = omnipetsmoketest/' \
    -e 's/^title = .*/title = Omnipet Smoke Test/' \
    -e 's#^source.include_patterns = \(.*\)$#source.include_patterns = \1, modules/**#' \
    "$SRC/buildozer.spec" > "$D/buildozer.spec"
grep -q '^package.name = omnipetsmoketest$' "$D/buildozer.spec" || { echo "package name not set"; exit 1; }
find "$D" -path "$D/.buildozer" -prune -o -name '*.pyc' -type f -print0 | xargs -0 rm -f
rm -f "$D"/bin/*.apk
cd "$D"
echo "[smoke-apk] buildozer android debug (long: about 10-30 min)"
buildozer android debug
cp bin/*.apk "$OUT/"
ls -la "$OUT"/*.apk
