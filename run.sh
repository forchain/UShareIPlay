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

stop_bridge() {
  local bridge_pid="${1:-${USHAREIPLAY_BRIDGE_PID:-}}"
  if [[ -z "${bridge_pid}" ]]; then
    return 0
  fi
  # The perl runner forks one child per connection; those children outlive a
  # signal aimed at the parent alone, so take them down first.
  pkill -P "${bridge_pid}" 2>/dev/null || true
  kill "${bridge_pid}" 2>/dev/null || true
  return 0
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

  # 2.1 Python runtime reachability & macOS Local Network Privacy bridge
  if command -v uv >/dev/null 2>&1; then
    local py_status=0
    uv run python -c "
import sys
from ushareiplay.core.network_bridge import check_socket_connectivity, is_macos_local_network_error
ok, err = check_socket_connectivity('${appium_host}', int('${appium_port}'), timeout=2.0)
if not ok:
    if is_macos_local_network_error(err):
        sys.exit(65)
    sys.exit(1)
" 2>/dev/null || py_status=$?

    if [[ "${py_status}" -eq 65 ]]; then
      if [[ "$(uname -s)" == "Darwin" ]]; then
        local bridge_runner=""
        if [[ -x "/usr/bin/ruby" ]]; then
          bridge_runner="ruby"
        elif [[ -x "/usr/bin/perl" ]]; then
          bridge_runner="perl"
        elif [[ -x "/usr/bin/python3" ]]; then
          bridge_runner="python"
        fi

        if [[ -z "${bridge_runner}" ]]; then
          log "警告: 未找到可用的系统桥接运行时 (/usr/bin/ruby、/usr/bin/perl、/usr/bin/python3 均不可用)，跳过桥接，将依赖应用内自愈机制。"
        else
          log "[macOS 本地网络策略兼容] 检测到系统限制 Python 访问局域网 (Errno 65)，启动原生透明代理桥接 (${bridge_runner})..."
          local bridge_fifo
          bridge_fifo="$(mktemp -u /tmp/ushareiplay_bridge.XXXXXX)"
          mkfifo "${bridge_fifo}"

          if [[ "${bridge_runner}" == "ruby" ]]; then
            /usr/bin/ruby -e "
require 'socket'
Signal.trap('TERM') { exit 0 }
Signal.trap('INT') { exit 0 }

target_host = ARGV[0]
target_port = Integer(ARGV[1])

server = TCPServer.new('127.0.0.1', 0)
File.open('${bridge_fifo}', 'w') { |f| f.puts(server.addr[1]) }

def forward(src, dst)
  while (data = src.readpartial(16384))
    dst.write(data)
  end
rescue
ensure
  src.close rescue nil
  dst.close rescue nil
end

loop do
  client = server.accept
  Thread.new(client) do |c|
    begin
      remote = Socket.tcp(target_host, target_port, connect_timeout: 5)
      t1 = Thread.new { forward(c, remote) }
      t2 = Thread.new { forward(remote, c) }
      t1.join
      t2.join
    rescue
    ensure
      c.close rescue nil
    end
  end
end
" "${appium_host}" "${appium_port}" &
          elif [[ "${bridge_runner}" == "perl" ]]; then
            /usr/bin/perl -e "
use strict;
use warnings;
use IO::Socket::INET;
use IO::Select;

my \$target_host = \$ARGV[0];
my \$target_port = int(\$ARGV[1]);

my \$server = IO::Socket::INET->new(
    LocalAddr => '127.0.0.1',
    LocalPort => 0,
    Proto => 'tcp',
    Listen => 128,
    ReuseAddr => 1
) or die \"Cannot bind: \$!\\n\";

my \$port = \$server->sockport();
open(my \$fh, '>', '${bridge_fifo}') or die \"Cannot open fifo: \$!\\n\";
print \$fh \"\$port\\n\";
close(\$fh);

\$SIG{TERM} = sub { exit 0; };
\$SIG{INT}  = sub { exit 0; };
\$SIG{CHLD} = 'IGNORE';

while (my \$client = \$server->accept()) {
    my \$pid = fork();
    if (!defined \$pid) { close \$client; next; }
    if (\$pid == 0) {
        close \$server;
        my \$remote = IO::Socket::INET->new(
            PeerAddr => \$target_host,
            PeerPort => \$target_port,
            Proto => 'tcp',
            Timeout => 5
        );
        if (!\$remote) { close \$client; exit 1; }
        my \$sel = IO::Select->new(\$client, \$remote);
        while (my @ready = \$sel->can_read()) {
            foreach my \$s (@ready) {
                my \$buf;
                my \$n = sysread(\$s, \$buf, 16384);
                if (!defined \$n || \$n == 0) { exit 0; }
                my \$dst = (\$s == \$client) ? \$remote : \$client;
                syswrite(\$dst, \$buf);
            }
        }
        exit 0;
    } else {
        close \$client;
    }
}
" "${appium_host}" "${appium_port}" &
          else
            /usr/bin/python3 -c "
import socket, threading, sys, signal

target_host = sys.argv[1]
target_port = int(sys.argv[2])

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', 0))
port = server.getsockname()[1]
server.listen(128)
with open('${bridge_fifo}', 'w') as f:
    f.write(f'{port}\n')

def forward(src, dst):
    try:
        while True:
            data = src.recv(16384)
            if not data: break
            dst.sendall(data)
    except Exception: pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle_client(client):
    try:
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.settimeout(5.0)
        remote.connect((target_host, target_port))
        remote.settimeout(None)
        t1 = threading.Thread(target=forward, args=(client, remote), daemon=True)
        t2 = threading.Thread(target=forward, args=(remote, client), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
    except Exception: pass
    finally:
        try: client.close()
        except: pass

def accept_loop():
    while True:
        try:
            client, _ = server.accept()
            threading.Thread(target=handle_client, args=(client,), daemon=True).start()
        except Exception: break

threading.Thread(target=accept_loop, daemon=True).start()

def sig_handler(signum, frame):
    try: server.close()
    except: pass
    sys.exit(0)

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

try:
    signal.pause()
except Exception:
    import time
    while True: time.sleep(1)
" "${appium_host}" "${appium_port}" &
          fi
          local bridge_pid=$!
          local allocated_port=""
          # Open the FIFO read-write before reading: a read-only open blocks until
          # the runner opens its end, so a runner that dies first (/usr/bin/ruby is
          # a Command Line Tools shim that exits without touching the FIFO) would
          # hang the launcher forever. `read -t` bounds the read, not that open.
          if exec 9<> "${bridge_fifo}"; then
            read -r -t 5 -u 9 allocated_port || true
            exec 9>&-
          fi
          rm -f "${bridge_fifo}"

          if [[ -n "${allocated_port}" ]]; then
            if curl -s -m 2 "http://127.0.0.1:${allocated_port}/status" >/dev/null 2>&1; then
              export APPIUM_HOST="127.0.0.1"
              export APPIUM_PORT="${allocated_port}"
              export USHAREIPLAY_BRIDGE_PID="${bridge_pid}"
              trap 'stop_bridge' EXIT INT TERM
              log "已启用系统原生桥接 (${bridge_runner}): 127.0.0.1:${allocated_port} -> ${appium_host}:${appium_port} (PID: ${bridge_pid})。"
            else
              stop_bridge "${bridge_pid}"
              log "警告: 系统桥接连通性验证失败，将依赖应用内自愈机制。"
            fi
          else
            stop_bridge "${bridge_pid}"
            log "警告: 系统桥接未能在超时前上报端口或已退出，将依赖应用内自愈机制。"
          fi
        fi
      fi
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
  uv run ushareiplay "$@"
  local exit_code=$?
  exit ${exit_code}
}

main "$@"