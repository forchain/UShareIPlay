#!/usr/bin/env bash
# Manage a Waydroid session and its reversible PipeWire audio loopback.
set -euo pipefail
umask 077

STATE_DIR="${XDG_STATE_HOME:-${HOME}/.local/state}/ushareiplay"
STATE_FILE="${STATE_DIR}/waydroid-audio.env"
UI_UNIT="ushareiplay-waydroid-ui"
SESSION_UNIT="ushareiplay-waydroid-session"

if [[ -z "${XDG_RUNTIME_DIR:-}" && -d "/run/user/$(id -u)" ]]; then
  export XDG_RUNTIME_DIR="/run/user/$(id -u)"
fi
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" && -S "${XDG_RUNTIME_DIR}/bus" ]]; then
  export DBUS_SESSION_BUS_ADDRESS="unix:path=${XDG_RUNTIME_DIR}/bus"
fi

need() {
  command -v "$1" >/dev/null || { printf 'missing required command: %s\n' "$1" >&2; exit 1; }
}

waydroid_serial() {
  awk 'NF >= 3 { print $3; exit }' /var/lib/misc/dnsmasq.waydroid0.leases
}

adb_waydroid() {
  local serial
  serial="$(waydroid_serial)"
  [[ -n "${serial}" ]] || { printf 'Waydroid has no DHCP lease. Start it first.\n' >&2; exit 1; }
  adb -s "${serial}:5555" "$@"
}

start_session() {
  need waydroid
  need systemd-run
  if ! systemctl --user is-active --quiet "${SESSION_UNIT}"; then
    systemd-run --user --unit="${SESSION_UNIT}" --collect waydroid session start >/dev/null
  fi
  for _ in $(seq 1 30); do
    if waydroid status | grep -q '^Session:[[:space:]]*RUNNING'; then
      return
    fi
    sleep 1
  done
  printf 'Waydroid session did not become ready.\n' >&2
  exit 1
}

open_ui() {
  if ! systemctl --user is-active --quiet "${UI_UNIT}"; then
    systemd-run --user --unit="${UI_UNIT}" --collect waydroid show-full-ui >/dev/null
  fi
}

route_start() {
  need pactl
  mkdir -p "${STATE_DIR}"
  [[ ! -e "${STATE_FILE}" ]] || { printf 'Waydroid loopback is already active.\n' >&2; return; }
  local old_sink old_source module_id
  old_sink="$(pactl get-default-sink)"
  old_source="$(pactl get-default-source)"
  module_id="$(pactl load-module module-null-sink sink_name=ushareiplay_music_sink sink_properties=device.description=UShareIPlay_Music_Input)"
  {
    printf 'old_sink=%q\n' "${old_sink}"
    printf 'old_source=%q\n' "${old_source}"
    printf 'module_id=%q\n' "${module_id}"
  } > "${STATE_FILE}"
  pactl set-default-sink ushareiplay_music_sink
  pactl set-default-source ushareiplay_music_sink.monitor
  printf 'Waydroid loopback active: Android playback is routed to its microphone.\n'
}

route_stop() {
  [[ -r "${STATE_FILE}" ]] || { printf 'Waydroid loopback is not active.\n' >&2; return; }
  # shellcheck disable=SC1090
  source "${STATE_FILE}"
  pactl unload-module "${module_id}" || true
  for _ in $(seq 1 10); do
    if pactl list short sinks | awk '{print $2}' | grep -qx "${old_sink}" && pactl list short sources | awk '{print $2}' | grep -qx "${old_source}"; then
      break
    fi
    sleep 0.1
  done
  pactl set-default-sink "${old_sink}" || true
  pactl set-default-source "${old_source}" || true
  rm -f "${STATE_FILE}"
  printf 'Waydroid loopback stopped and previous PipeWire defaults restored.\n'
}

prepare() {
  need sudo
  need curl
  if ! apt-cache show waydroid >/dev/null 2>&1; then
    curl -fsSL https://repo.waydro.id | sudo bash
  fi
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y adb pipewire-pulse wireplumber pulseaudio-utils waydroid
  sudo modprobe binder_linux devices=binder,hwbinder,vndbinder || true
  sudo waydroid init
}

status() {
  waydroid status
  printf '\nPipeWire defaults:\n'
  pactl info | awk -F': ' '/Default Sink|Default Source/ { print $1 ": " $2 }'
  [[ -r "${STATE_FILE}" ]] && printf 'Loopback state: active\n' || printf 'Loopback state: inactive\n'
}

usage() {
  printf 'usage: %s {prepare|open [--loopback]|route-start|route-stop|status}\n' "$0" >&2
}

action="${1:-}"
case "${action}" in
  prepare)
    prepare
    ;;
  open)
    start_session
    if [[ "${2:-}" == "--loopback" ]]; then
      route_start
    elif [[ -n "${2:-}" ]]; then
      usage
      exit 2
    fi
    open_ui
    ;;
  route-start)
    route_start
    ;;
  route-stop)
    route_stop
    ;;
  status)
    status
    ;;
  *)
    usage
    exit 2
    ;;
esac
