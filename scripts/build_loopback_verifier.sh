#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SDK_ROOT="${ANDROID_SDK_ROOT:-${HOME}/Library/Android/sdk}"
JAVA_HOME="${JAVA_HOME:-/opt/homebrew/opt/openjdk@17/libexec/openjdk.jdk/Contents/Home}"
export JAVA_HOME
export PATH="${JAVA_HOME}/bin:${PATH}"
BUILD_TOOLS="${SDK_ROOT}/build-tools/36.1.0"
PLATFORM="${SDK_ROOT}/platforms/android-36/android.jar"
PROJECT="${ROOT_DIR}/tools/loopback-verifier"
BUILD="${PROJECT}/build"
KEYSTORE="${PROJECT}/debug.keystore"

rm -rf "${BUILD}"
mkdir -p "${BUILD}/classes" "${BUILD}/dex"
"${JAVA_HOME}/bin/javac" -source 8 -target 8 -bootclasspath "${PLATFORM}" -d "${BUILD}/classes" \
  "${PROJECT}/src/io/ushareiplay/loopback/MainActivity.java"
find "${BUILD}/classes" -name '*.class' -exec "${BUILD_TOOLS}/d8" --lib "${PLATFORM}" --output "${BUILD}/dex" {} +
"${BUILD_TOOLS}/aapt" package -f -M "${PROJECT}/AndroidManifest.xml" -I "${PLATFORM}" -F "${BUILD}/unsigned.apk"
(cd "${BUILD}/dex" && "${BUILD_TOOLS}/aapt" add "${BUILD}/unsigned.apk" classes.dex)
if [[ ! -f "${KEYSTORE}" ]]; then
  "${JAVA_HOME}/bin/keytool" -genkeypair -keystore "${KEYSTORE}" -storepass android -keypass android -alias androiddebugkey \
    -keyalg RSA -keysize 2048 -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null
fi
"${BUILD_TOOLS}/apksigner" sign --ks "${KEYSTORE}" --ks-pass pass:android --key-pass pass:android --out "${BUILD}/loopback-verifier.apk" "${BUILD}/unsigned.apk"
echo "${BUILD}/loopback-verifier.apk"
