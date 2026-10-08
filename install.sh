#!/usr/bin/env bash
# UShareIPlay Cross-Platform Installer (Ubuntu Linux & macOS)
# Idempotent setup for Linux (Waydroid/PipeWire/Appium) & macOS (Host tools/Appium/Python environment).
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { printf "${BLUE}[INFO]${NC} %s\n" "$*"; }
log_succ() { printf "${GREEN}[OK]${NC} %s\n" "$*"; }
log_warn() { printf "${YELLOW}[WARN]${NC} %s\n" "$*"; }
log_err()  { printf "${RED}[ERROR]${NC} %s\n" "$*" >&2; }

# Environment defaults
TARGET_DIR="${TARGET_DIR:-${INSTALL_DIR:-}}"
REPO_URL="${REPO_URL:-https://github.com/forchain/UShareIPlay.git}"
BRANCH="${BRANCH:-feat/ubuntu-one-click-installer}"
QQMUSIC_APK_URL="${QQMUSIC_APK_URL:-http://imtt.dd.qq.com/sjy.00022/sjy.00004/16891/apk/7F21EA29367F8C5FC19DB2867E80766F.apk?fsname=com.tencent.qqmusic_20.7.5.8.apk}"
SOUL_APK_URL="${SOUL_APK_URL:-https://china-img.soulapp.cn/apk/channel/soul_channel_soul64.apk}"
GOOGLE_WEBVIEW_APK_URL="${GOOGLE_WEBVIEW_APK_URL:-https://github.com/JonaNorman/WebViewPackage/releases/download/google/146.0.7680.164_min29_arm32%2B64.apk}"
WECHAT_APK_URL="${WECHAT_APK_URL:-https://dldir1v6.qq.com/weixin/android/weixin8076android3141_0x28004c31_arm64.apk}"

# 1. Sanity Checks
check_prerequisites() {
  log_info "检查系统环境与权限..."
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" != "Linux" && "${os_type}" != "Darwin" ]]; then
    log_err "本一键安装脚本仅支持 Linux (推荐 Ubuntu 24.04 LTS) 或 macOS。"
    exit 1
  fi

  local arch
  arch="$(uname -m)"
  if [[ "${os_type}" == "Linux" ]]; then
    if [[ "${arch}" != "aarch64" && "${arch}" != "arm64" ]]; then
      log_warn "当前系统架构为 ${arch}。由于 QQ 音乐与 Soul App 为 ARM64 原生应用，推荐在 aarch64 (ARM64) 环境运行以获得最佳性能与兼容性。"
    fi
    if ! sudo -n true 2>/dev/null; then
      log_info "需要 sudo 权限进行系统组件配置，请输入密码："
      sudo true
    fi
  elif [[ "${os_type}" == "Darwin" ]]; then
    log_info "检测到 macOS 环境 (${arch})。"
    if ! command -v brew >/dev/null 2>&1; then
      log_warn "未检测到 Homebrew (brew)。推荐先安装 Homebrew 以便自动安装依赖工具：https://brew.sh"
    fi
  fi
  log_succ "系统与权限检查通过。"
}

# 2. Setup Repository Directory
setup_repository() {
  if [[ -z "${TARGET_DIR}" ]]; then
    if [[ -f "./pyproject.toml" && -f "./run.sh" ]]; then
      TARGET_DIR="$(pwd)"
      log_info "在当前仓库目录执行: ${TARGET_DIR}"
    else
      TARGET_DIR="${HOME}/UShareIPlay"
      log_info "未指定目标目录，默认安装至: ${TARGET_DIR}"
    fi
  fi

  if [[ -d "${TARGET_DIR}/.git" ]]; then
    log_info "更新现有代码仓库: ${TARGET_DIR}"
    git -C "${TARGET_DIR}" fetch --quiet || true
  elif [[ ! -d "${TARGET_DIR}" || ! -f "${TARGET_DIR}/pyproject.toml" ]]; then
    log_info "克隆 UShareIPlay 代码仓库至 ${TARGET_DIR}..."
    mkdir -p "$(dirname "${TARGET_DIR}")"
    git clone --branch "${BRANCH}" --depth 1 "${REPO_URL}" "${TARGET_DIR}"
  fi
  log_succ "代码仓库准备就绪: ${TARGET_DIR}"
}

# 3. System Packages
install_system_packages() {
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" == "Linux" ]]; then
    log_info "安装系统基础软件包及 PipeWire / ADB / iptables 依赖..."
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
      curl wget git iptables iptables-persistent netfilter-persistent \
      pipewire-pulse wireplumber pulseaudio-utils adb jq \
      python3 python3-pip python3-venv libglib2.0-0 libpulse0 >/dev/null
    log_succ "系统依赖安装完成。"
  elif [[ "${os_type}" == "Darwin" ]]; then
    log_info "检查 macOS 基础工具与依赖..."
    if command -v brew >/dev/null 2>&1; then
      local brew_pkgs=()
      command -v adb >/dev/null 2>&1 || brew_pkgs+=("android-platform-tools")
      command -v jq >/dev/null 2>&1 || brew_pkgs+=("jq")
      command -v wget >/dev/null 2>&1 || brew_pkgs+=("wget")
      if [[ ${#brew_pkgs[@]} -gt 0 ]]; then
        log_info "通过 Homebrew 安装依赖: ${brew_pkgs[*]}..."
        for pkg in "${brew_pkgs[@]}"; do
          if [[ "${pkg}" == "android-platform-tools" ]]; then
            brew install --cask "${pkg}" --quiet 2>/dev/null || brew install "${pkg}" --quiet 2>/dev/null || true
          else
            brew install "${pkg}" --quiet 2>/dev/null || true
          fi
        done
      fi
    else
      command -v adb >/dev/null 2>&1 || log_warn "未检测到 adb 命令，请确保已安装 Android SDK platform-tools 并加入 PATH。"
    fi
    log_succ "macOS 依赖检查完成。"
  fi
}

# 4. Install uv (Fast Python Package Manager)
install_uv() {
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv >/dev/null 2>&1; then
    log_info "安装 Astral uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
  if [[ -f "${HOME}/.local/bin/uv" ]]; then
    if [[ -w "/usr/local/bin" ]]; then
      ln -sf "${HOME}/.local/bin/uv" /usr/local/bin/uv 2>/dev/null || true
    elif sudo -n true 2>/dev/null; then
      sudo ln -sf "${HOME}/.local/bin/uv" /usr/local/bin/uv 2>/dev/null || true
    fi
  fi
  if ! grep -q '.local/bin' "${HOME}/.bashrc" 2>/dev/null; then
    echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.bashrc"
  fi
  if [[ -f "${HOME}/.zshrc" ]] && ! grep -q '.local/bin' "${HOME}/.zshrc" 2>/dev/null; then
    echo 'export PATH="${HOME}/.local/bin:${PATH}"' >> "${HOME}/.zshrc"
  fi
  log_succ "uv 版本: $(uv --version)"
}

# 5. Install Node.js Appium & uiautomator2 driver
install_appium() {
  log_info "检查并安装 Node.js LTS 与 Appium 及 uiautomator2 驱动..."
  local os_type
  os_type="$(uname -s)"

  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d'.' -f1 | tr -d 'v')" -lt 20 ]]; then
    if [[ "${os_type}" == "Linux" ]]; then
      log_info "配置并安装 Node.js LTS (v20)..."
      curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
    elif [[ "${os_type}" == "Darwin" ]]; then
      if command -v brew >/dev/null 2>&1; then
        log_info "通过 Homebrew 安装 Node.js..."
        brew install node --quiet 2>/dev/null || true
      else
        log_warn "macOS 未检测到 Node.js (>=20) 且未安装 Homebrew，请手动安装 Node.js LTS: https://nodejs.org"
      fi
    fi
  fi

  if ! command -v appium >/dev/null 2>&1; then
    log_info "全局安装 Appium..."
    npm install -g appium --quiet 2>/dev/null || (sudo -n true 2>/dev/null && sudo npm install -g appium --quiet) || true
  fi

  # Check uiautomator2 driver
  if command -v appium >/dev/null 2>&1; then
    if ! appium driver list --installed 2>&1 | grep -q "uiautomator2"; then
      log_info "安装 uiautomator2 驱动..."
      appium driver install uiautomator2 >/dev/null 2>&1 || (sudo -n true 2>/dev/null && sudo appium driver install uiautomator2 >/dev/null 2>&1) || true
    fi
    log_succ "Appium 就绪: $(appium --version 2>/dev/null || echo 'installed')"
  else
    log_warn "Appium 暂未成功安装，可后续手动执行 npm install -g appium 安装。"
  fi
}

# 6. Python Virtual Environment and Project Dependencies
setup_python_project() {
  log_info "初始化 Python 虚拟环境与依赖..."
  cd "${TARGET_DIR}"
  uv sync --quiet

  # config.yaml 为受版本管理的基准配置（同时充当示例）；config.local.yaml 为可选的
  # 本地覆盖文件，安装器不再代为创建。
  log_succ "Python 运行环境与依赖配置完成。"
}

# 7. Install & Configure Waydroid (Linux Only)
setup_waydroid() {
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" != "Linux" ]]; then
    log_info "macOS 环境跳过 Waydroid 虚拟容器配置 (macOS 支持物理 Android 设备或 Android Studio AVD 模拟器)。"
    return 0
  fi

  log_info "配置 Waydroid 虚拟 Android 环境..."
  if ! command -v waydroid >/dev/null 2>&1; then
    log_info "添加 Waydroid 官方软件源..."
    curl -fsSL https://repo.waydro.id | sudo bash >/dev/null 2>&1
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq waydroid >/dev/null
  fi

  # Ensure binder modules
  sudo modprobe binder_linux devices=binder,hwbinder,vndbinder 2>/dev/null || true
  echo "binder_linux" | sudo tee /etc/modules-load.d/waydroid-binder.conf >/dev/null

  # Initialize Waydroid if not already initialized
  if [[ ! -d /var/lib/waydroid/images ]] || [[ -z "$(ls -A /var/lib/waydroid/images 2>/dev/null || true)" ]]; then
    log_info "初始化 Waydroid Android 镜像 (首次初始化需下载镜像，请稍候)..."
    sudo waydroid init -y
  fi

  # Start waydroid container service
  sudo systemctl enable waydroid-container.service >/dev/null 2>&1 || true
  sudo systemctl restart waydroid-container.service

  # Start user session if needed
  if command -v waydroid >/dev/null 2>&1; then
    if ! waydroid status 2>/dev/null | grep -q "Session:[[:space:]]*RUNNING"; then
      log_info "启动 Waydroid Session..."
      waydroid session start >/dev/null 2>&1 &
      sleep 3
    fi
  fi

  # Optimize Android captive portal & network stack (domestic mirror)
  sudo lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- settings put global captive_portal_mode 0 2>/dev/null || true
  sudo lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- settings put global captive_portal_https_url https://connect.rom.miui.com/generate_204 2>/dev/null || true
  sudo lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- settings put global captive_portal_http_url http://connect.rom.miui.com/generate_204 2>/dev/null || true

  log_succ "Waydroid 服务与容器就绪。"
}

# 8. Install Applications (WebView, QQ Music, Soul, WeChat, Loopback Verifier)
install_apks() {
  local os_type
  os_type="$(uname -s)"

  if [[ "${os_type}" == "Darwin" ]]; then
    if [[ "${INSTALL_APKS:-0}" != "1" ]]; then
      log_info "macOS 环境跳过应用 APK 自动下载与安装 (设备端请确保安装 QQ 音乐与 Soul App；如需由脚本自动推送安装，请设置 INSTALL_APKS=1)。"
      return 0
    fi
    log_info "检查 macOS 下 Android 设备连接状态..."
    if ! command -v adb >/dev/null 2>&1; then
      log_info "未检测到 adb 命令，跳过 APK 检查与安装。"
      return 0
    fi
    local devices_count
    devices_count="$(adb devices 2>/dev/null | awk 'NR>1 && $2=="device" {count++} END {print count+0}')"
    if [[ "${devices_count}" -eq 0 ]]; then
      log_info "未检测到已连接并授权的 ADB 设备，跳过 APK 自动安装。连接物理设备或启动模拟器后可按需安装。"
      return 0
    fi
  fi

  log_info "检查并安装 Google WebView、QQ 音乐、Soul App、微信及回环验证组件..."
  local tmp_dir="/tmp/ushareiplay_apks"
  mkdir -p "${tmp_dir}"

  local install_apk_file
  install_apk_file() {
    local target_apk="$1"
    if [[ -s "${target_apk}" ]]; then
      if [[ "${os_type}" == "Linux" ]]; then
        local apk_size
        apk_size="$(stat -c%s "${target_apk}" 2>/dev/null || stat -f%z "${target_apk}" 2>/dev/null || true)"
        if [[ -n "${apk_size}" ]]; then
          sudo sh -c "lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- pm install -r -d -S ${apk_size} < '${target_apk}'" >/dev/null 2>&1 || \
            waydroid app install "${target_apk}" >/dev/null 2>&1 || adb install -r "${target_apk}" >/dev/null 2>&1 || true
        fi
      else
        adb install -r "${target_apk}" >/dev/null 2>&1 || true
      fi
    fi
  }

  local is_package_installed
  is_package_installed() {
    local pkg_name="$1"
    if [[ "${os_type}" == "Linux" ]]; then
      sudo lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- pm list packages 2>/dev/null | grep -q "${pkg_name}" || \
        (command -v adb >/dev/null 2>&1 && adb shell pm list packages 2>/dev/null | grep -q "${pkg_name}")
    else
      command -v adb >/dev/null 2>&1 && adb shell pm list packages 2>/dev/null | grep -q "${pkg_name}"
    fi
  }

  local grant_permission
  grant_permission() {
    local pkg_name="$1"
    local perm="$2"
    if [[ "${os_type}" == "Linux" ]]; then
      sudo lxc-attach -P /var/lib/waydroid/lxc -n waydroid -- pm grant "${pkg_name}" "${perm}" 2>/dev/null || true
    fi
    if command -v adb >/dev/null 2>&1; then
      adb shell pm grant "${pkg_name}" "${perm}" 2>/dev/null || true
    fi
  }

  # 8.1 Google Android System WebView
  if is_package_installed "com.google.android.webview"; then
    log_succ "Google System WebView (com.google.android.webview) 已安装。"
  else
    log_info "下载并安装 Google System WebView (ARM64)..."
    local webview_apk="${tmp_dir}/google_webview.apk"
    if [[ ! -s "${webview_apk}" ]]; then
      curl -fsSL -o "${webview_apk}" "${GOOGLE_WEBVIEW_APK_URL}" 2>/dev/null || wget -q -O "${webview_apk}" "${GOOGLE_WEBVIEW_APK_URL}" || true
    fi
    if [[ -s "${webview_apk}" ]]; then
      install_apk_file "${webview_apk}"
      log_succ "Google System WebView 安装成功。"
    fi
  fi

  # 8.2 QQ Music (Phone Edition)
  if is_package_installed "com.tencent.qqmusic"; then
    log_succ "QQ 音乐手机版 (com.tencent.qqmusic) 已安装。"
  else
    log_info "下载并安装 QQ 音乐手机版..."
    local qq_apk="${tmp_dir}/qqmusic.apk"
    if [[ ! -s "${qq_apk}" ]]; then
      curl -fsSL -A "Mozilla/5.0 (Linux; Android 13; Mobile)" -o "${qq_apk}" "${QQMUSIC_APK_URL}" 2>/dev/null || wget -q -U "Mozilla/5.0" -O "${qq_apk}" "${QQMUSIC_APK_URL}" || true
    fi
    if [[ -s "${qq_apk}" ]]; then
      install_apk_file "${qq_apk}"
      log_succ "QQ 音乐安装成功。"
    else
      log_warn "QQ 音乐 APK 下载未完成，可在启动后手动安装或通过环境变量 QQMUSIC_APK_URL 指定。"
    fi
  fi

  # 8.3 Soul App
  if is_package_installed "cn.soulapp.android"; then
    log_succ "Soul App (cn.soulapp.android) 已安装。"
  else
    log_info "下载并安装 Soul App..."
    local soul_apk="${tmp_dir}/soul.apk"
    if [[ ! -s "${soul_apk}" ]]; then
      curl -fsSL -A "Mozilla/5.0 (Linux; Android 13; Mobile)" -o "${soul_apk}" "${SOUL_APK_URL}" 2>/dev/null || wget -q -U "Mozilla/5.0" -O "${soul_apk}" "${SOUL_APK_URL}" || true
    fi
    if [[ -s "${soul_apk}" ]]; then
      install_apk_file "${soul_apk}"
      log_succ "Soul App 安装成功。"
    else
      log_warn "Soul App APK 下载未完成，可在启动后手动安装或通过环境变量 SOUL_APK_URL 指定。"
    fi
  fi

  # Grant Audio / Mic permissions to Soul App
  grant_permission "cn.soulapp.android" "android.permission.RECORD_AUDIO"
  grant_permission "cn.soulapp.android" "android.permission.MODIFY_AUDIO_SETTINGS"

  # 8.4 WeChat (for convenient authorization/QR scan login)
  if is_package_installed "com.tencent.mm"; then
    log_succ "微信 (com.tencent.mm) 已安装。"
  else
    log_info "下载并安装微信应用 (用于扫码与快捷授权登录)..."
    local wechat_apk="${tmp_dir}/wechat.apk"
    if [[ ! -s "${wechat_apk}" ]]; then
      curl -fsSL -A "Mozilla/5.0 (Linux; Android 13; Mobile)" -o "${wechat_apk}" "${WECHAT_APK_URL}" 2>/dev/null || wget -q -U "Mozilla/5.0" -O "${wechat_apk}" "${WECHAT_APK_URL}" || true
    fi
    if [[ -s "${wechat_apk}" ]]; then
      install_apk_file "${wechat_apk}"
      log_succ "微信安装成功。"
    fi
  fi

  # 8.5 Loopback Verifier
  local verifier_apk=""
  if [[ -f "${TARGET_DIR}/tools/loopback-verifier/build/loopback-verifier.apk" ]]; then
    verifier_apk="${TARGET_DIR}/tools/loopback-verifier/build/loopback-verifier.apk"
  elif [[ -f "${TARGET_DIR}/tools/loopback-verifier/loopback-verifier.apk" ]]; then
    verifier_apk="${TARGET_DIR}/tools/loopback-verifier/loopback-verifier.apk"
  fi

  if [[ -n "${verifier_apk}" ]]; then
    install_apk_file "${verifier_apk}"
    grant_permission "io.ushareiplay.loopback" "android.permission.RECORD_AUDIO"
    log_succ "回环验证组件 (io.ushareiplay.loopback) 已就绪。"
  fi
}

# 9. Setup Persistent ADB Port Forwarding via iptables & systemd (Linux Only)
setup_adb_forwarding() {
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" != "Linux" ]]; then
    log_info "macOS 环境跳过持久化 ADB 端口转发 (物理设备或模拟器直连)。"
    return 0
  fi

  log_info "配置持久化 ADB 端口转发 (宿主机:5555 -> Waydroid 容器:5555)..."

  # Enable IP forwarding persistently in sysctl
  printf "net.ipv4.ip_forward=1\nnet.ipv4.conf.all.route_localnet=1\n" | sudo tee /etc/sysctl.d/99-ushareiplay-forward.conf >/dev/null
  sudo sysctl -p /etc/sysctl.d/99-ushareiplay-forward.conf >/dev/null 2>&1 || sudo sysctl -w net.ipv4.ip_forward=1 >/dev/null

  # Install forward script
  sudo cp "${TARGET_DIR}/scripts/ushareiplay-adb-forward.sh" /usr/local/bin/ushareiplay-adb-forward.sh
  sudo chmod +x /usr/local/bin/ushareiplay-adb-forward.sh

  # Install systemd service
  sudo cp "${TARGET_DIR}/scripts/ushareiplay-adb-forward.service" /etc/systemd/system/ushareiplay-adb-forward.service
  sudo systemctl daemon-reload
  sudo systemctl enable ushareiplay-adb-forward.service >/dev/null 2>&1
  sudo systemctl restart ushareiplay-adb-forward.service || true

  log_succ "ADB 端口映射及持久化服务已生效。"
}

# 10. Setup Appium Background Service (Linux Only)
setup_appium_service() {
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" != "Linux" ]]; then
    log_info "macOS 环境跳过 systemd 后台服务配置 (可通过 ./appium.sh 手动启动 Appium)。"
    return 0
  fi

  log_info "配置 Appium 后台常驻服务..."
  sudo cp "${TARGET_DIR}/scripts/ushareiplay-appium.service" /etc/systemd/system/ushareiplay-appium.service
  sudo systemctl daemon-reload
  sudo systemctl enable ushareiplay-appium.service >/dev/null 2>&1
  sudo systemctl restart ushareiplay-appium.service
  log_succ "Appium 服务已启动并在后台常驻 (0.0.0.0:4723)。"
}

# 11. Configure PipeWire Audio Loopback (Linux) / Check BlackHole (macOS)
setup_audio_loopback() {
  local os_type
  os_type="$(uname -s)"
  if [[ "${os_type}" != "Linux" ]]; then
    log_info "检查 macOS 音频回环配置..."
    if command -v brew >/dev/null 2>&1; then
      if brew list --cask blackhole-2ch >/dev/null 2>&1; then
        log_succ "检测到 BlackHole 2ch 虚拟音频设备已安装。"
      else
        log_info "提示: 如需虚拟音频回环，可运行 'brew install --cask blackhole-2ch' 安装 BlackHole 2ch。"
      fi
    fi
    return 0
  fi

  log_info "配置 PipeWire 麦克风音频回环..."
  if command -v pactl >/dev/null 2>&1; then
    pactl list short sinks 2>/dev/null | grep -q "ushareiplay_music_sink" || \
      pactl load-module module-null-sink sink_name=ushareiplay_music_sink sink_properties=device.description=UShareIPlay_Music_Input >/dev/null 2>&1 || true
    pactl set-default-sink ushareiplay_music_sink >/dev/null 2>&1 || true
    pactl set-default-source ushareiplay_music_sink.monitor >/dev/null 2>&1 || true
  fi

  # Install user systemd service if available
  mkdir -p "${HOME}/.config/systemd/user"
  cp "${TARGET_DIR}/scripts/ushareiplay-loopback.service" "${HOME}/.config/systemd/user/ushareiplay-loopback.service" 2>/dev/null || true
  systemctl --user daemon-reload 2>/dev/null || true
  systemctl --user enable ushareiplay-loopback.service 2>/dev/null || true
  systemctl --user start ushareiplay-loopback.service 2>/dev/null || true
  log_succ "PipeWire 麦克风音频回环已配置。"
}

# 12. Completion Summary
print_summary() {
  local os_type
  os_type="$(uname -s)"

  if [[ "${os_type}" == "Darwin" ]]; then
    printf "\n========================================================\n"
    printf "${GREEN}🎉 UShareIPlay macOS 开发与运行环境配置完成！${NC}\n"
    printf "========================================================\n"
    printf "• 项目目录:   %s\n" "${TARGET_DIR}"
    printf "• Python 环境: uv sync 已就绪\n"
    printf "• Appium:     已就绪 (可运行 ./appium.sh 启动)\n"
    printf '%s\n' "--------------------------------------------------------"
    printf "${YELLOW}后续使用指南：${NC}\n"
    printf "1. 连接 Android 手机并开启 USB 调试，或启动 Android Studio 模拟器：\n"
    printf "   ${BLUE}adb devices${NC}\n"
    printf "2. 在独立终端启动 Appium 服务：\n"
    printf "   ${BLUE}./appium.sh${NC}\n"
    printf "3. （可选）创建 config.local.yaml 配置设备名称与 Soul 房间号：\n"
    printf "   ${BLUE}cat > config.local.yaml <<'EOF'\n"
    printf "device:\n"
    printf "  name: \"192.168.1.100:5555\"  # 填入实际 adb 设备标识\n"
    printf "soul:\n"
    printf "  default_party_id: \"FM00000000\"\n"
    printf "EOF${NC}\n"
    printf "4. 进入项目目录并启动：\n"
    printf "   ${BLUE}cd %s && ./run.sh${NC}\n" "${TARGET_DIR}"
    printf "========================================================\n\n"
    return 0
  fi

  local ip_addr="127.0.0.1"
  if command -v hostname >/dev/null 2>&1; then
    ip_addr="$(hostname -I 2>/dev/null | awk '{print $1}' || echo '127.0.0.1')"
  fi

  printf "\n========================================================\n"
  printf "${GREEN}🎉 UShareIPlay 一键安装与环境配置已圆满完成！${NC}\n"
  printf "========================================================\n"
  printf "• 项目目录:  %s\n" "${TARGET_DIR}"
  printf "• ADB 端口:  %s:5555 (外部/宿主机直连)\n" "${ip_addr}"
  printf "• Appium:    http://%s:4723\n" "${ip_addr}"
  printf "• 音频回环:  ushareiplay_music_sink (PipeWire Null Sink)\n"
  printf '%s\n' "--------------------------------------------------------"
  printf "${YELLOW}后续使用指南：${NC}\n"
  printf "1. 在云机/桌面中打开模拟器图形界面登录账号：\n"
  printf "   ${BLUE}waydroid show-full-ui${NC}\n"
  printf "2. 首次打开 QQ 音乐 与 Soul App 完成登录并授权麦克风权限。\n"
  printf "3. 进入项目目录并启动项目：\n"
  printf "   ${BLUE}cd %s && ./run.sh${NC}\n" "${TARGET_DIR}"
  printf "========================================================\n\n"
}

main() {
  check_prerequisites
  setup_repository
  install_system_packages
  install_uv
  install_appium
  setup_python_project
  setup_waydroid
  install_apks
  setup_adb_forwarding
  setup_appium_service
  setup_audio_loopback
  print_summary
}

# 仅在直接执行时运行 main()；被 `source` 时只加载函数，供测试调用
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
