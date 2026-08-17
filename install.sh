#!/usr/bin/env bash
# UShareIPlay Ubuntu One-Click Installer
# Idempotent setup for Ubuntu ARM64/x86_64 host: Waydroid, Audio Loopback, Appium, ADB Forwarding, Dependencies & APKs.
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
QQMUSIC_APK_URL="${QQMUSIC_APK_URL:-https://dldir1v6.qq.com/music/release/upload/t_mm_file_publish/10200113.apk}"
SOUL_APK_URL="${SOUL_APK_URL:-https://china-img.soulapp.cn/apk/channel/soul_channel_soul64.apk}"

# 1. Sanity Checks
check_prerequisites() {
  log_info "检查系统环境与权限..."
  if [[ "$(uname -s)" != "Linux" ]]; then
    log_err "本一键安装脚本仅支持 Linux (推荐 Ubuntu 24.04 LTS)。"
    exit 1
  fi

  local arch
  arch="$(uname -m)"
  if [[ "${arch}" != "aarch64" && "${arch}" != "arm64" ]]; then
    log_warn "当前系统架构为 ${arch}。由于 QQ 音乐与 Soul App 为 ARM64 原生应用，推荐在 aarch64 (ARM64) 环境运行以获得最佳性能与兼容性。"
  fi

  if ! sudo -n true 2>/dev/null; then
    log_info "需要 sudo 权限进行系统组件配置，请输入密码："
    sudo true
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
  log_info "安装系统基础软件包及 PipeWire / ADB / iptables 依赖..."
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    curl wget git iptables iptables-persistent netfilter-persistent \
    pipewire-pulse wireplumber pulseaudio-utils adb jq \
    python3 python3-pip python3-venv libglib2.0-0 libpulse0 >/dev/null
  log_succ "系统依赖安装完成。"
}

# 4. Install uv (Fast Python Package Manager)
install_uv() {
  export PATH="${HOME}/.local/bin:${PATH}"
  if ! command -v uv >/dev/null 2>&1; then
    log_info "安装 Astral uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1
    export PATH="${HOME}/.local/bin:${PATH}"
  fi
  log_succ "uv 版本: $(uv --version)"
}

# 5. Install Node.js Appium & uiautomator2 driver
install_appium() {
  log_info "检查并安装 Node.js LTS 与 Appium 及 uiautomator2 驱动..."
  if ! command -v node >/dev/null 2>&1 || [[ "$(node -v | cut -d'.' -f1 | tr -d 'v')" -lt 20 ]]; then
    log_info "配置并安装 Node.js LTS (v20)..."
    curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash - >/dev/null 2>&1
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq nodejs >/dev/null
  fi

  if ! command -v appium >/dev/null 2>&1; then
    sudo npm install -g appium --quiet
  fi

  # Check uiautomator2 driver
  if ! appium driver list --installed 2>/dev/null | grep -q "uiautomator2"; then
    log_info "安装 uiautomator2 驱动..."
    appium driver install uiautomator2 || sudo appium driver install uiautomator2 || true
  fi
  log_succ "Appium 就绪: $(appium --version 2>/dev/null || echo 'installed')"
}

# 6. Python Virtual Environment and Project Dependencies
setup_python_project() {
  log_info "初始化 Python 虚拟环境与依赖..."
  cd "${TARGET_DIR}"
  uv sync --quiet

  if [[ ! -f "${TARGET_DIR}/config.local.yaml" ]]; then
    if [[ -f "${TARGET_DIR}/config.local.yaml.example" ]]; then
      cp "${TARGET_DIR}/config.local.yaml.example" "${TARGET_DIR}/config.local.yaml"
      log_info "已从示例文件创建 config.local.yaml"
    fi
  fi
  log_succ "Python 运行环境与依赖配置完成。"
}

# 7. Install & Configure Waydroid
setup_waydroid() {
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
  log_succ "Waydroid 服务与容器就绪。"
}

# 8. Install Applications (QQ Music, Soul, Loopback Verifier)
install_apks() {
  log_info "检查并安装 QQ 音乐、Soul App 及回环验证组件..."
  local tmp_dir="/tmp/ushareiplay_apks"
  mkdir -p "${tmp_dir}"

  local install_apk_file
  install_apk_file() {
    local target_apk="$1"
    if [[ -s "${target_apk}" ]]; then
      waydroid app install "${target_apk}" >/dev/null 2>&1 || adb install -r "${target_apk}" >/dev/null 2>&1 || true
    fi
  }

  # 8.1 QQ Music
  if sudo waydroid shell pm list packages 2>/dev/null | grep -q "com.tencent.qqmusic"; then
    log_succ "QQ 音乐 (com.tencent.qqmusic) 已安装。"
  else
    log_info "下载并安装 QQ 音乐..."
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

  # 8.2 Soul App
  if sudo waydroid shell pm list packages 2>/dev/null | grep -q "cn.soulapp.android"; then
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
  sudo waydroid shell pm grant cn.soulapp.android android.permission.RECORD_AUDIO 2>/dev/null || true
  sudo waydroid shell pm grant cn.soulapp.android android.permission.MODIFY_AUDIO_SETTINGS 2>/dev/null || true

  # 8.3 Loopback Verifier
  local verifier_apk=""
  if [[ -f "${TARGET_DIR}/tools/loopback-verifier/build/loopback-verifier.apk" ]]; then
    verifier_apk="${TARGET_DIR}/tools/loopback-verifier/build/loopback-verifier.apk"
  elif [[ -f "${TARGET_DIR}/tools/loopback-verifier/loopback-verifier.apk" ]]; then
    verifier_apk="${TARGET_DIR}/tools/loopback-verifier/loopback-verifier.apk"
  fi

  if [[ -n "${verifier_apk}" ]]; then
    install_apk_file "${verifier_apk}"
    sudo waydroid shell pm grant io.ushareiplay.loopback android.permission.RECORD_AUDIO 2>/dev/null || true
    log_succ "回环验证组件 (io.ushareiplay.loopback) 已就绪。"
  fi
}

# 9. Setup Persistent ADB Port Forwarding via iptables & systemd
setup_adb_forwarding() {
  log_info "配置持久化 ADB 端口转发 (宿主机:5555 -> Waydroid 容器:5555)..."

  # Enable IP forwarding persistently in sysctl
  echo "net.ipv4.ip_forward=1" | sudo tee /etc/sysctl.d/99-ushareiplay-forward.conf >/dev/null
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

# 10. Setup Appium Background Service
setup_appium_service() {
  log_info "配置 Appium 后台常驻服务..."
  sudo cp "${TARGET_DIR}/scripts/ushareiplay-appium.service" /etc/systemd/system/ushareiplay-appium.service
  sudo systemctl daemon-reload
  sudo systemctl enable ushareiplay-appium.service >/dev/null 2>&1
  sudo systemctl restart ushareiplay-appium.service
  log_succ "Appium 服务已启动并在后台常驻 (0.0.0.0:4723)。"
}

# 11. Configure PipeWire Audio Loopback
setup_audio_loopback() {
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
  local ip_addr
  ip_addr="$(hostname -I | awk '{print $1}' || echo '127.0.0.1')"

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

main "$@"
