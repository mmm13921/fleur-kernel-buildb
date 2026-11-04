#!/usr/bin/env bash
set -Eeuo pipefail

WORKSPACE="${GITHUB_WORKSPACE:-$PWD}"
SRC_DIR="$WORKSPACE/kernel-src"
OUT_DIR="$WORKSPACE/out"
ARTIFACT_DIR="$WORKSPACE/artifacts"
SOURCE_URL="https://github.com/xiaomi-mt6781-fleur-dev/android_kernel_mt6781.git"
SOURCE_REF="fleur-r-oss"
SOURCE_COMMIT="29295d3eeaa5290732b52b5800a360e86c04301e"
TOOLCHAIN_DIR="${TOOLCHAIN_DIR:-}"

if [[ -z "$TOOLCHAIN_DIR" || ! -x "$TOOLCHAIN_DIR/bin/clang" ]]; then
  echo "TOOLCHAIN_DIR must point to the extracted Android Clang toolchain." >&2
  exit 2
fi

if [[ -e "$SRC_DIR" ]]; then
  echo "Source directory already exists: $SRC_DIR" >&2
  exit 2
fi

mkdir -p "$ARTIFACT_DIR"
echo "Cloning Fleur Android-R source: $SOURCE_REF"
git clone --depth=1 --branch "$SOURCE_REF" "$SOURCE_URL" "$SRC_DIR"
ACTUAL_COMMIT="$(git -C "$SRC_DIR" rev-parse HEAD)"
if [[ "$ACTUAL_COMMIT" != "$SOURCE_COMMIT" ]]; then
  echo "Source moved: expected $SOURCE_COMMIT, got $ACTUAL_COMMIT" >&2
  exit 3
fi

python3 "$WORKSPACE/scripts/patch_android11_alucard.py" "$SRC_DIR"
git -C "$SRC_DIR" diff --check

export PATH="$TOOLCHAIN_DIR/bin:$PATH"
export ARCH=arm64
export SUBARCH=arm64
export KBUILD_BUILD_USER="fleur-alucard-builder"
export KBUILD_BUILD_HOST="github-actions"
export KBUILD_BUILD_TIMESTAMP="2026-11-04 00:00:00"

mkdir -p "$OUT_DIR"
make -C "$SRC_DIR" O="$OUT_DIR" ARCH=arm64 fleur_defconfig \
  CC=clang LD=ld.lld LLVM=1 LLVM_IAS=1

if ! grep -qx 'CONFIG_CPU_FREQ_GOV_ALUCARD=y' "$OUT_DIR/.config"; then
  echo "Alucard was not enabled in the resolved kernel config." >&2
  grep 'CPU_FREQ_GOV_' "$OUT_DIR/.config" || true
  exit 4
fi

echo "Enabled CPUFreq governors:"
grep -E '^CONFIG_CPU_FREQ_(DEFAULT_GOV|GOV)_[A-Z0-9_]+=y$' "$OUT_DIR/.config" || true

make -C "$SRC_DIR" -j"$(nproc)" O="$OUT_DIR" \
  ARCH=arm64 CC=clang LD=ld.lld AR=llvm-ar AS=llvm-as \
  NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump STRIP=llvm-strip \
  CROSS_COMPILE=aarch64-linux-gnu- \
  CROSS_COMPILE_ARM32=arm-linux-gnueabi- \
  CLANG_TRIPLE=aarch64-linux-gnu- LLVM=1 LLVM_IAS=1 Image.gz-dtb

IMAGE="$OUT_DIR/arch/arm64/boot/Image.gz-dtb"
if [[ ! -s "$IMAGE" ]]; then
  echo "Expected kernel image is missing: $IMAGE" >&2
  find "$OUT_DIR/arch/arm64/boot" -maxdepth 2 -type f -printf '%p\n' || true
  exit 5
fi

cp "$IMAGE" "$ARTIFACT_DIR/Image.gz-dtb"
cp "$OUT_DIR/.config" "$ARTIFACT_DIR/kernel.config"
git -C "$SRC_DIR" diff --binary > "$ARTIFACT_DIR/alucard-source.patch"

cat > "$ARTIFACT_DIR/build-manifest.txt" <<EOF
device=fleur
android_vendor_branch=R (Android 11 vendor)
kernel_version=4.14.343-openela
source_url=$SOURCE_URL
source_ref=$SOURCE_REF
source_commit=$ACTUAL_COMMIT
governor_added=alucard
governors_preexisting=performance,powersave,userspace,ondemand,interactive,schedutil
config=CONFIG_CPU_FREQ_GOV_ALUCARD=y
toolchain=Android LLVM clang-r563880c
compiler=$(clang --version | head -n 1)
image=Image.gz-dtb
flashability=experimental; exact device kernel 4.14.186 source not used
EOF

AK_DIR="$RUNNER_TEMP/AnyKernel3"
git clone --depth=1 https://github.com/osm0sis/AnyKernel3.git "$AK_DIR"
rm -rf "$AK_DIR/.git" "$AK_DIR/.github"
cp "$ARTIFACT_DIR/Image.gz-dtb" "$AK_DIR/Image.gz-dtb"
cat > "$AK_DIR/anykernel.sh" <<'AK3'
#!/sbin/sh
# Experimental Fleur Android-R kernel with Alucard CPUFreq governor.
properties() { '
kernel.string=Fleur Android 11 Alucard Governor (4.14.343)
do.devicecheck=1
do.modules=0
do.systemless=1
do.cleanup=1
do.cleanuponabort=0
device.name1=fleur
device.name2=miel
device.name3=missi
'; }
BLOCK=auto;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;
. tools/ak3-core.sh;
ui_print " ";
ui_print "Fleur Android-R Alucard CPUFreq build";
ui_print "Kernel base: 4.14.343 (R vendor source)";
ui_print "Added governor: Alucard";
ui_print "Device check enabled: fleur / miel / missi";
ui_print "Experimental build; exact 4.14.186 source was not available";
ui_print " ";
dump_boot;
write_boot;
AK3

(
  cd "$AK_DIR"
  zip -r9 "$ARTIFACT_DIR/Fleur-Android11-Alucard-4.14.343-AnyKernel3.zip" \
    META-INF tools LICENSE anykernel.sh Image.gz-dtb
)

unzip -t "$ARTIFACT_DIR/Fleur-Android11-Alucard-4.14.343-AnyKernel3.zip"
sha256sum "$ARTIFACT_DIR/Image.gz-dtb" \
  "$ARTIFACT_DIR/Fleur-Android11-Alucard-4.14.343-AnyKernel3.zip" \
  "$ARTIFACT_DIR/kernel.config" "$ARTIFACT_DIR/alucard-source.patch" \
  | tee "$ARTIFACT_DIR/SHA256SUMS.txt"

echo "Android-R Alucard build completed."
