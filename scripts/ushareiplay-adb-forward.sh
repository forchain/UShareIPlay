#!/usr/bin/env bash
# Maintain persistent iptables port forwarding from host/VM port 5555 to Waydroid container ADB port 5555.
set -euo pipefail

log() {
  printf '[ushareiplay-adb-forward] %s\n' "$*"
}

get_waydroid_ip() {
  local ip=""
  if [[ -r /var/lib/misc/dnsmasq.waydroid0.leases ]]; then
    ip="$(awk 'NF >= 3 { print $3; exit }' /var/lib/misc/dnsmasq.waydroid0.leases || true)"
  fi
  if [[ -z "${ip}" ]] && command -v waydroid >/dev/null 2>&1; then
    ip="$(waydroid status 2>/dev/null | awk -F':\t' '/IP address:/ { gsub(/[[:space:]]/, "", $2); print $2 }' || true)"
  fi
  printf '%s' "${ip}"
}

apply_forwarding() {
  local target_ip="$1"
  log "Setting up ADB port forwarding to Waydroid IP: ${target_ip}:5555"

  # Ensure IP forwarding is enabled
  sysctl -w net.ipv4.ip_forward=1 >/dev/null
  sysctl -w net.ipv4.conf.all.route_localnet=1 >/dev/null

  # NAT PREROUTING & OUTPUT chain
  iptables -t nat -N USHAREIPLAY_ADB_FWD 2>/dev/null || iptables -t nat -F USHAREIPLAY_ADB_FWD
  if ! iptables -t nat -C PREROUTING -p tcp --dport 5555 -j USHAREIPLAY_ADB_FWD 2>/dev/null; then
    iptables -t nat -I PREROUTING -p tcp --dport 5555 -j USHAREIPLAY_ADB_FWD
  fi
  if ! iptables -t nat -C OUTPUT -p tcp -o lo --dport 5555 -j USHAREIPLAY_ADB_FWD 2>/dev/null; then
    iptables -t nat -I OUTPUT -p tcp -o lo --dport 5555 -j USHAREIPLAY_ADB_FWD
  fi
  iptables -t nat -A USHAREIPLAY_ADB_FWD -p tcp --dport 5555 -j DNAT --to-destination "${target_ip}:5555"

  # Filter FORWARD chain
  iptables -N USHAREIPLAY_ADB_FWD 2>/dev/null || iptables -F USHAREIPLAY_ADB_FWD
  if ! iptables -C FORWARD -p tcp --dport 5555 -j USHAREIPLAY_ADB_FWD 2>/dev/null; then
    iptables -I FORWARD -p tcp --dport 5555 -j USHAREIPLAY_ADB_FWD
  fi
  iptables -A USHAREIPLAY_ADB_FWD -p tcp -d "${target_ip}" --dport 5555 -j ACCEPT
  iptables -A USHAREIPLAY_ADB_FWD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

  # Save rules if iptables directory / netfilter-persistent exists
  if command -v netfilter-persistent >/dev/null 2>&1; then
    netfilter-persistent save >/dev/null 2>&1 || true
  elif [[ -d /etc/iptables ]]; then
    iptables-save > /etc/iptables/rules.v4 2>/dev/null || true
  fi

  log "ADB port forwarding successfully applied."
}

main() {
  local retries=30
  local ip=""

  for ((i=1; i<=retries; i++)); do
    ip="$(get_waydroid_ip)"
    if [[ -n "${ip}" && "${ip}" != "None" ]]; then
      break
    fi
    log "Waiting for Waydroid network lease (${i}/${retries})..."
    sleep 2
  done

  if [[ -z "${ip}" || "${ip}" == "None" ]]; then
    log "ERROR: Waydroid container IP could not be determined. Please ensure Waydroid is running." >&2
    exit 1
  fi

  apply_forwarding "${ip}"
}

main "$@"
