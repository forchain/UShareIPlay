#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TARGET_CFG="${ROOT_DIR}/config.local.yaml"
SOURCE_CFG="${HOME}/github.com/forchain/UShareIPlay/config.local.yaml"
EXAMPLE_CFG="${ROOT_DIR}/config.local.yaml.example"
TARGET_VENV="${ROOT_DIR}/.venv"

log() {
  printf '[run.sh] %s\n' "$*"
}

link_main_branch_venv() {
  local current_path="" branch_ref="" main_worktree="" candidate_venv=""
  while IFS= read -r line; do
    case "${line}" in
      worktree\ *)
        current_path="${line#worktree }"
        ;;
      branch\ refs/heads/main)
        branch_ref="refs/heads/main"
        ;;
      "")
        if [[ "${branch_ref}" == "refs/heads/main" ]]; then
          main_worktree="${current_path}"
          break
        fi
        current_path=""
        branch_ref=""
        ;;
    esac
  done < <(git -C "${ROOT_DIR}" worktree list --porcelain 2>/dev/null || true)

  if [[ -z "${main_worktree}" ]]; then
    return 1
  fi

  candidate_venv="${main_worktree}/.venv"
  if [[ ! -d "${candidate_venv}" ]]; then
    return 1
  fi

  ln -s "${candidate_venv}" "${TARGET_VENV}"
  log "当前目录缺少 .venv，已链接 main 分支虚拟环境：${candidate_venv}"
  return 0
}

ensure_config() {
  if [[ ! -f "${TARGET_CFG}" ]]; then
    if [[ -f "${SOURCE_CFG}" ]]; then
      cp "${SOURCE_CFG}" "${TARGET_CFG}"
      log "已从 ${SOURCE_CFG} 复制 config.local.yaml"
    elif [[ -f "${EXAMPLE_CFG}" ]]; then
      cp "${EXAMPLE_CFG}" "${TARGET_CFG}"
      log "已从示例配置初始化 ${TARGET_CFG}"
    else
      log "警告: 未找到 config.local.yaml 或示例文件，将依赖默认 config.yaml"
    fi
  fi
}

ensure_environment() {
  if [[ ! -e "${TARGET_VENV}" ]]; then
    if ! link_main_branch_venv; then
      if command -v uv >/dev/null 2>&1; then
        log "正在使用 uv 初始化 Python 虚拟环境与依赖..."
        (cd "${ROOT_DIR}" && uv sync --quiet || true)
      fi
    fi
  fi
}

preflight_checks() {
  log "执行前置运行环境健康检查..."

  # 1. Linux PipeWire Audio Loopback check
  if [[ "$(uname -s)" == "Linux" ]] && command -v pactl >/dev/null 2>&1; then
    if ! pactl list short sinks 2>/dev/null | grep -q "ushareiplay_music_sink"; then
      log "正在激活 PipeWire 麦克风音频回环..."
      pactl load-module module-null-sink sink_name=ushareiplay_music_sink sink_properties=device.description=UShareIPlay_Music_Input >/dev/null 2>&1 || true
      pactl set-default-sink ushareiplay_music_sink >/dev/null 2>&1 || true
      pactl set-default-source ushareiplay_music_sink.monitor >/dev/null 2>&1 || true
    fi
  fi

  # 2. Appium Service check
  local appium_host="${APPIUM_HOST:-}"
  local appium_port="${APPIUM_PORT:-}"

  if [[ -z "${appium_host}" || -z "${appium_port}" ]]; then
    if command -v uv >/dev/null 2>&1; then
      local cfg_host="" cfg_port=""
      read -r cfg_host cfg_port < <(uv run python -c "
try:
    from ushareiplay.core.config_loader import ConfigLoader
    cfg = ConfigLoader.load_config('${ROOT_DIR}/config.yaml')
    print(cfg.get('appium', {}).get('host', '127.0.0.1'), cfg.get('appium', {}).get('port', 4723))
except Exception:
    print('127.0.0.1 4723')
" 2>/dev/null || echo "127.0.0.1 4723")
      appium_host="${appium_host:-$cfg_host}"
      appium_port="${appium_port:-$cfg_port}"
    fi
  fi

  appium_host="${appium_host:-127.0.0.1}"
  appium_port="${appium_port:-4723}"

  local is_local=0
  if [[ "${appium_host}" == "127.0.0.1" || "${appium_host}" == "localhost" ]]; then
    is_local=1
  fi

  if command -v curl >/dev/null 2>&1; then
    local appium_url="http://${appium_host}:${appium_port}/status"
    if ! curl -s -L -k -m 3 "${appium_url}" >/dev/null 2>&1; then
      if [[ "${is_local}" -eq 1 ]]; then
        log "本地 Appium 服务 (${appium_url}) 未就绪，尝试唤起系统服务..."
        if command -v systemctl >/dev/null 2>&1; then
          sudo systemctl start ushareiplay-appium 2>/dev/null || systemctl --user start ushareiplay-appium 2>/dev/null || true
        fi
        sleep 2
        if ! curl -s -L -k -m 3 "${appium_url}" >/dev/null 2>&1; then
          log "提示: 本地 Appium (${appium_url}) 仍在启动中或未安装为服务。"
        fi
      else
        log "警告: 远程 Appium 服务 (${appium_url}) 当前无法连通，请检查网络或远程服务状态。"
      fi
    else
      log "Appium 服务健康 (${appium_url})。"
    fi
  fi


  # 3. ADB connectivity check
  if command -v adb >/dev/null 2>&1; then
    local devices_count
    devices_count="$(adb devices | awk 'NR>1 && $2=="device" {count++} END {print count+0}')"
    if [[ "${devices_count}" -eq 0 ]]; then
      log "检测到未连接 ADB 设备，尝试连接本机/Waydroid ADB..."
      if [[ -r /var/lib/misc/dnsmasq.waydroid0.leases ]]; then
        local waydroid_ip
        waydroid_ip="$(awk 'NF >= 3 { print $3; exit }' /var/lib/misc/dnsmasq.waydroid0.leases 2>/dev/null || true)"
        if [[ -n "${waydroid_ip}" ]]; then
          adb connect "${waydroid_ip}:5555" >/dev/null 2>&1 || true
        fi
      fi
      adb connect 127.0.0.1:5555 >/dev/null 2>&1 || true
    fi
  fi
  log "前置检查完成。"
}

main() {
  ensure_config
  ensure_environment

  if [[ "${1:-}" == "--check" || "${1:-}" == "--check-only" ]]; then
    preflight_checks
    log "环境验证通过 (check-only)。"
    exit 0
  fi

  preflight_checks

  mkdir -p "${ROOT_DIR}/logs"
  exec uv run ushareiplay "$@"
}

main "$@"