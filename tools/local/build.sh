#!/bin/bash
# Metal Gear Rising: Revengeance PS5 build in WSL (Ubuntu 24.04), keeping what it can between builds:
#
#   wsl -d Ubuntu-24.04 -u root -- bash /mnt/c/.../mgr-ps5/tools/local/build.sh [repo] [out app folder]
#
# - tools/local/toolchain.sh builds the PS5 toolchain once ($W/tri).
# - The framework is cloned and set up once ($W/fw-pristine); each build patches
#   a fresh copy and syncs it into $W/ws/fw by content, so ninja and ccache only
#   rebuild what changed.
# - Codegen runs again only when its inputs change (cached in $W/gen/<hash>).
# - The game's code comes from your own files: MGR_XEX=<the disc's default.xex> and
#   MGR_XEXP=<Title Update 4's default.xexp> (checked by their SHA-1s; on this PC,
#   Extras/game/ and Extras/TU4/ beside the repo by default). Nothing leaves the PC.
set -eo pipefail

repo=$(realpath "${1:-$(dirname "$0")/../..}")
app_out=${2:-}
W=${MGR_WORK:-/root/mgrbuild}
TITLE_ID=${TITLE_ID:-PPSA48080}
GTA4_PS5_REPO=https://github.com/elripalda/gta4-ps5
CD_PC_REPO=https://github.com/saulob/crackdown-xbox360-recompiled
CD_PC_COMMIT=33ab1b632e38cb5c1c39a3d56c479537b9e0d185
# the disc's default.xex and Title Update 4's default.xexp
XEX_SHA1=TBD
XEXP_SHA1=4320595b58c28eb801e457361a4659ea1e1b2586
MGR_XEX=${MGR_XEX:-$repo/../Extras/game/default.xex}
MGR_XEXP=${MGR_XEXP:-$repo/../Extras/TU4/default.xexp}
[ -f "$MGR_XEX" ] && [ -f "$MGR_XEXP" ] || { echo "set MGR_XEX and MGR_XEXP to your own game files" >&2; exit 2; }
if [ "$XEX_SHA1" != TBD ]; then
  echo "$XEX_SHA1  $MGR_XEX" | sha1sum -c --quiet || { echo "$MGR_XEX isn't the disc's default.xex" >&2; exit 2; }
fi
echo "$XEXP_SHA1  $MGR_XEXP" | sha1sum -c --quiet || { echo "$MGR_XEXP isn't Title Update 4's default.xexp" >&2; exit 2; }
[ "$XEX_SHA1" != TBD ] || XEX_SHA1=$(sha1sum "$MGR_XEX" | cut -c1-40)
export CCACHE_DIR=$W/ccache
step() { echo "==> $(date +%T) $*"; }

[ -d "$W/tri/.deps/native/ps5-payload-sdk" ] || { echo "run tools/local/toolchain.sh first" >&2; exit 2; }
mkdir -p "$W/ws" "$W/gen" "$CCACHE_DIR"
ccache -M 30G > /dev/null

# ---- the workspace: the repo's files (not .git), with tri, fw and out kept ----
step "workspace"
rsync -a --delete --exclude .git --exclude /tri --exclude /fw --exclude /out --exclude /cd \
  --exclude /build-rexglue --exclude /private "$repo/" "$W/ws/"
cd "$W/ws"
ln -sfn "$W/tri" tri

# ---- framework: pristine once, then patched into fw-new, synced into fw ----
if [ ! -f "$W/fw-pristine/.setup-done" ]; then
  step "framework clone and setup (once)"
  rm -rf "$W/fw-pristine"
  git clone --depth 1 "$GTA4_PS5_REPO" "$W/fw-pristine"
  (cd "$W/fw-pristine" && bash ./setup.sh)
  touch "$W/fw-pristine/.setup-done"
fi
if [ ! -d "$W/cd/patches" ]; then
  step "Crackdown PC recomp patches (once)"
  rm -rf "$W/cd" && git init -q "$W/cd" && git -C "$W/cd" remote add origin "$CD_PC_REPO"
  git -C "$W/cd" fetch -q --depth 1 origin "$CD_PC_COMMIT" && git -C "$W/cd" checkout -q FETCH_HEAD
fi
step "framework patches"
rm -rf "$W/fw-new"
mkdir -p "$W/fw-new"
cp -a "$W/fw-pristine/." "$W/fw-new/"  # (the contents: fw-pristine may be a link to a shared one)
python3 ci/pc_patches.py "$W/fw-new" "$W/cd" > "$W/pc_patches.txt"
python3 ci/fw_perf_fixes.py "$W/fw-new" "$W/cd" > "$W/fw_perf_fixes.txt"
python3 ci/patch_framework.py "$W/fw-new" > "$W/patch_framework.txt"
M=glue/rexglue-sdk-main/mgr-recomp
rm -rf "$W/fw-new/$M"
cp -r mgr-recomp "$W/fw-new/$M"

# ---- codegen, only when its inputs changed ----
# (patch_framework.py only touches the codegen to dump the image: not an input)
gen_key=$( (git -C "$W/fw-pristine" rev-parse HEAD; cat ci/pc_patches.py ci/fw_perf_fixes.py \
  ci/mark_share_registers.py mgr-recomp/mgr_config.toml mgr-recomp/mgr_manifest.toml; echo "$XEX_SHA1 $XEXP_SHA1") |
  sha256sum | cut -c1-16)
if [ ! -d "$W/gen/$gen_key/generated" ]; then
  step "rexglue CLI (host)"
  rsync -a --checksum --delete "$W/fw-new/" "$W/fw-host/"
  cmake -S "$W/fw-host/glue/rexglue-sdk-main" -B "$W/build-rexglue" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang-19 -DCMAKE_CXX_COMPILER=clang++-19 \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DCMAKE_C_FLAGS=-march=x86-64-v3 -DCMAKE_CXX_FLAGS=-march=x86-64-v3 \
    -DCMAKE_CXX_STANDARD=23 -DMGR_NO_GTA4_NATIVE=ON \
    -DREXGLUE_ENABLE_TRACY=OFF -DREXGLUE_BUILD_GTA4_RECOMP=OFF \
    -DREXGLUE_BUILD_TESTS=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 > "$W/rexglue-configure.txt"
  ninja -C "$W/build-rexglue" rexglue > "$W/rexglue-build.txt"
  REXGLUE=$(find "$W/build-rexglue" "$W/fw-host/glue/rexglue-sdk-main/out" -name rexglue -type f -perm -u+x 2>/dev/null | head -1)
  step "codegen"
  H=$W/fw-host/$M
  rm -rf "$H/generated" "$H/assets" && mkdir -p "$H/assets" "$W/private"
  cp "$MGR_XEX" "$H/assets/default.xex" && cp "$MGR_XEXP" "$H/assets/default.xexp"
  REX_DUMP_IMAGE=$W/private/image.bin "$REXGLUE" --log-level info -f codegen "$H/mgr_manifest.toml" > "$W/codegen.txt" 2>&1 ||
    { tail -80 "$W/codegen.txt"; exit 1; }
  RBW=$W/fw-host/glue/rexglue-sdk-main/gta4-recomp/tools/read_before_write.py
  sed 's/gta4_recomp\.\*\.cpp/mgr_recomp.*.cpp/' "$RBW" > "$W/read_before_write.py"
  python3 "$W/read_before_write.py" "$H/generated" > "$W/read_before_write.txt" 2> "$W/rbw-total.txt"
  python3 ci/mark_share_registers.py "$W/read_before_write.txt" "$H/mgr_config.toml" "$W/private/image.bin"
  rm -rf "$H/generated"
  "$REXGLUE" --log-level info -f codegen "$H/mgr_manifest.toml" > "$W/codegen-pass2.txt" 2>&1 ||
    { tail -80 "$W/codegen-pass2.txt"; exit 1; }
  rm -rf "$H/assets"
  mkdir -p "$W/gen/$gen_key"
  mv "$H/generated" "$W/gen/$gen_key/generated"
  cp "$H/mgr_config.toml" "$W/gen/$gen_key/mgr_config.toml"
  # (only the latest few)
  ls -1t "$W/gen" | tail -n +4 | while read -r old; do rm -rf "$W/gen/$old"; done
fi
cp -r "$W/gen/$gen_key/generated" "$W/fw-new/$M/generated"
cp "$W/gen/$gen_key/mgr_config.toml" "$W/fw-new/$M/mgr_config.toml"

# ---- the PS5 program ----
step "sync framework (by content)"
rsync -a --checksum --delete "$W/fw-new/" "$W/ws/fw/"
rm -rf "$W/fw-new"
SDK=$W/tri/.deps/native/ps5-payload-sdk
if [ ! -f out/ps5/build.ninja ]; then
  step "configure (PS5)"
  cmake -S fw/ps5 -B out/ps5 -G Ninja -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_TOOLCHAIN_FILE=$PWD/fw/ps5/cmake/ps5-toolchain.cmake -DPS5_PAYLOAD_SDK=$SDK \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DMGR_NO_GTA4_NATIVE=ON -DREXGLUE_ENABLE_FIDELITYFX=OFF \
    -DREXGLUE_ENABLE_TRACY=OFF -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DSDL_X11=OFF -DSDL_WAYLAND=OFF -DSDL_KMSDRM=OFF -DSDL_OPENGL=OFF -DSDL_OPENGLES=OFF \
    -DSDL_OSS=OFF -DSDL_ALSA=OFF -DSDL_PULSEAUDIO=OFF -DSDL_PIPEWIRE=OFF -DSDL_JACK=OFF \
    -DSDL_SNDIO=OFF -DSDL_HIDAPI=OFF -DSDL_DBUS=OFF -DSDL_IBUS=OFF -DSDL_LIBUDEV=OFF \
    -DSDL_VULKAN=OFF -DSDL_DUMMYVIDEO=ON -DSDL_DUMMYAUDIO=ON -DSDL_OFFSCREEN=OFF > "$W/configure.txt" 2>&1
fi
step "build (PS5)"
mkdir -p out
if ! ninja -C out/ps5 mgr > out/build.txt 2>&1; then
  grep -E "error:|FAILED" out/build.txt | head -40
  exit 1
fi
tail -1 out/build.txt
step "package"
bash ci/ps5_package_mgr.sh out/ps5 tri fw "$TITLE_ID" > out/package.txt 2>&1 || { tail -40 out/package.txt; exit 1; }
llvm-nm-19 -n -C --defined-only out/ps5/ps5-link/build/llvm-pie.elf | grep -i ' t ' | gzip -9 > out/symbols.txt.gz || true
app=out/ps5/ps5-app/$TITLE_ID
# The user's own art and music (kept out of git): Extras/app-assets/ next to the repo, laid out as the
# app folder (sce_sys/icon0.png, pic0.dds, pic1.dds, snd0.at9; hub/background.jpg, hub/music/).
assets=${MGR_APP_ASSETS:-$repo/../Extras/app-assets}
[ -d "$assets" ] || assets=$repo/package/app-assets
if [ -d "$assets" ]; then
  cp -r "$assets/." "$app/"
  step "app assets from $assets"
fi
ls -l "$app/eboot.bin"
if [ -n "$app_out" ]; then
  # the app's own files over the folder (a new one, or an installed one: its game, DLC, saves,
  # UserData and menu.ini are left as they are)
  mkdir -p "$app_out"
  cp -r "$app/." "$app_out/"
  cp out/symbols.txt.gz "$repo/../Extras/ps5-build-logs/symbols.txt.gz" 2>/dev/null || true
  step "app copied to $app_out"
fi
step "done"
