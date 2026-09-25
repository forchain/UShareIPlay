import errno
import os
import platform
import socket
import subprocess
import sys
import time
from typing import Optional, Tuple


def is_macos_local_network_error(exc: Optional[Exception]) -> bool:
    """Check if the exception is caused by macOS Local Network Privacy blocking (Errno 65 / EHOSTUNREACH)."""
    if exc is None:
        return False

    curr = exc
    visited = set()
    while curr is not None and id(curr) not in visited:
        visited.add(id(curr))
        if isinstance(curr, OSError) and getattr(curr, "errno", None) == 65:
            return True

        msg = str(curr)
        if "Errno 65" in msg or "No route to host" in msg or "EHOSTUNREACH" in msg:
            return True

        curr = getattr(curr, "__cause__", None) or getattr(curr, "__context__", None)

    return False


def check_socket_connectivity(host: str, port: int, timeout: float = 2.0) -> Tuple[bool, Optional[Exception]]:
    """Test TCP socket connectivity to the target host and port."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((host, int(port)))
        return True, None
    except Exception as e:
        return False, e
    finally:
        try:
            s.close()
        except Exception:
            pass


def diagnose_connection_error(host: str, port: int, exc: Exception) -> str:
    """Generate detailed and actionable diagnosis for connection failures."""
    is_mac = platform.system() == "Darwin"
    is_mac_local_net = is_macos_local_network_error(exc)

    lines = [
        f"[网络连接诊断] 无法连接到 Appium 服务器 (http://{host}:{port}): {exc}",
    ]

    if is_mac and is_mac_local_net:
        lines.extend([
            "",
            "【原因排查】",
            "检测到系统返回 [Errno 65] No route to host (macOS 本地网络隐私限制)。",
            "这是由于 macOS 15+ 引入的 Local Network Privacy 安全策略所致：",
            "1. 系统原生工具（如 /usr/bin/curl、/usr/bin/python3）拥有 Apple 平台签名，不受该限制，因此 curl 可以正常访问；",
            "2. 当前运行 Python 的宿主应用（如终端、IDE、Orca）或第三方 Python 解释器尚未获得 macOS 本地网络访问权限，导致被内核拦截。",
            "",
            "【解决建议】",
            "1. 推荐直接使用项目封装的启动脚本: ./run.sh (内置自动透明端口桥接与前置环境健康自检)",
            "2. 若需直连，请在 macOS「系统设置 -> 隐私与安全性 -> 本地网络」中，开启当前终端/宿主应用的权限",
        ])
    else:
        lines.extend([
            "",
            "【排查建议】",
            f"1. 请确认 Appium 服务是否已在目标地址 ({host}:{port}) 正常监听",
            f"2. 可以在终端执行: curl -v http://{host}:{port}/status 验证服务可用性",
            "3. 检查防火墙或局域网路由配置是否放行了该端口",
        ])

    return "\n".join(lines)


class LocalNetworkBridge:
    """Transparent TCP forwarder running via system-signed runners (Ruby, Perl, Python) to bypass macOS Local Network Privacy restrictions."""

    def __init__(
        self,
        target_host: str,
        target_port: int,
        system_python: Optional[str] = None,
        runner_type: Optional[str] = None,
        runner_path: Optional[str] = None,
    ):
        self.target_host = target_host
        self.target_port = int(target_port)

        if runner_type and runner_path:
            self.runner_type = runner_type
            self.runner_path = runner_path
        elif runner_path:
            self.runner_path = runner_path
            self.runner_type = "ruby" if "ruby" in runner_path else ("perl" if "perl" in runner_path else "python")
        elif system_python:
            if "ruby" in system_python:
                self.runner_type = "ruby"
                self.runner_path = system_python
            elif "perl" in system_python:
                self.runner_type = "perl"
                self.runner_path = system_python
            else:
                self.runner_type = "python"
                self.runner_path = system_python
        else:
            self.runner_type, self.runner_path = select_bridge_runner(target_host, self.target_port)

        self.bridge_host = "127.0.0.1"
        self.bridge_port = 0
        self._process: Optional[subprocess.Popen] = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def _build_command(self) -> list:
        if self.runner_type == "ruby":
            ruby_code = f"""
require "socket"
Signal.trap("TERM") {{ exit 0 }}
Signal.trap("INT") {{ exit 0 }}

target_host = {self.target_host!r}
target_port = {self.target_port}

server = TCPServer.new("127.0.0.1", 0)
$stdout.puts "PORT:#{{server.addr[1]}}"
$stdout.flush

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
      remote = TCPSocket.new(target_host, target_port)
      t1 = Thread.new {{ forward(c, remote) }}
      t2 = Thread.new {{ forward(remote, c) }}
      t1.join
      t2.join
    rescue
    ensure
      c.close rescue nil
    end
  end
end
"""
            return [self.runner_path, "-e", ruby_code]

        if self.runner_type == "perl":
            perl_code = f"""
use strict;
use warnings;
use IO::Socket::INET;
use IO::Select;

my $target_host = {self.target_host!r};
my $target_port = {self.target_port};

my $server = IO::Socket::INET->new(
    LocalAddr => "127.0.0.1",
    LocalPort => 0,
    Proto => "tcp",
    Listen => 128,
    ReuseAddr => 1
) or die "Cannot bind: $!\\n";

my $port = $server->sockport();
$| = 1;
print "PORT:$port\\n";

$SIG{{TERM}} = sub {{ exit 0; }};
$SIG{{INT}}  = sub {{ exit 0; }};
$SIG{{CHLD}} = "IGNORE";

while (my $client = $server->accept()) {{
    my $pid = fork();
    if (!defined $pid) {{ close $client; next; }}
    if ($pid == 0) {{
        close $server;
        my $remote = IO::Socket::INET->new(
            PeerAddr => $target_host,
            PeerPort => $target_port,
            Proto => "tcp",
            Timeout => 5
        );
        if (!$remote) {{ close $client; exit 1; }}
        my $sel = IO::Select->new($client, $remote);
        while (my @ready = $sel->can_read()) {{
            foreach my $s (@ready) {{
                my $buf;
                my $n = sysread($s, $buf, 16384);
                if (!defined $n || $n == 0) {{ exit 0; }}
                my $dst = ($s == $client) ? $remote : $client;
                syswrite($dst, $buf);
            }}
        }}
        exit 0;
    }} else {{
        close $client;
    }}
}}
"""
            return [self.runner_path, "-e", perl_code]

        # Python runner
        python_code = f"""
import socket, threading, sys, signal

target_host = {self.target_host!r}
target_port = {self.target_port}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', 0))
port = server.getsockname()[1]
server.listen(128)
print(f'PORT:{{port}}', flush=True)

def forward(src, dst):
    try:
        while True:
            data = src.recv(16384)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try: src.close()
        except Exception: pass
        try: dst.close()
        except Exception: pass

def handle_client(client):
    try:
        remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        remote.settimeout(5.0)
        remote.connect((target_host, target_port))
        remote.settimeout(None)
        t1 = threading.Thread(target=forward, args=(client, remote), daemon=True)
        t2 = threading.Thread(target=forward, args=(remote, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except Exception:
        pass
    finally:
        try: client.close()
        except Exception: pass

def accept_loop():
    while True:
        try:
            client, _ = server.accept()
            threading.Thread(target=handle_client, args=(client,), daemon=True).start()
        except Exception:
            break

threading.Thread(target=accept_loop, daemon=True).start()

def sig_handler(signum, frame):
    try: server.close()
    except Exception: pass
    sys.exit(0)

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

try:
    signal.pause()
except Exception:
    import time
    while True: time.sleep(1)
"""
        return [self.runner_path, "-c", python_code]

    def start(self, timeout: float = 5.0) -> int:
        if self.is_running:
            return self.bridge_port

        if not os.path.exists(self.runner_path):
            raise RuntimeError(f"Runner not found at {self.runner_path}, cannot start bridge.")

        cmd = self._build_command()
        self._process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

        start_time = time.time()
        port_found = None

        while time.time() - start_time < timeout:
            if self._process.poll() is not None:
                stderr = self._process.stderr.read() if self._process.stderr else ""
                raise RuntimeError(f"Bridge process ({self.runner_type}) terminated unexpectedly: {stderr}")

            line = self._process.stdout.readline()
            if line.startswith("PORT:"):
                port_found = int(line.strip().split(":")[1])
                break
            time.sleep(0.05)

        if not port_found:
            self.stop()
            raise TimeoutError(f"Timed out waiting for bridge to start within {timeout}s.")

        self.bridge_port = port_found
        return self.bridge_port

    def stop(self) -> None:
        if self._process is not None:
            try:
                self._process.terminate()
                self._process.wait(timeout=1.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            finally:
                self._process = None
                self.bridge_port = 0

    def __del__(self):
        self.stop()


def select_bridge_runner(
    target_host: str,
    target_port: int,
    preferred_python: Optional[str] = None,
) -> Tuple[str, str]:
    """
    Select an available runner executable for the transparent network bridge.
    On macOS (Darwin), prioritize Apple platform signed binaries (/usr/bin/ruby, /usr/bin/perl)
    which bypass Local Network Privacy restrictions (Errno 65).
    """
    if platform.system() == "Darwin" and target_host not in ("127.0.0.1", "localhost", "::1"):
        if os.path.exists("/usr/bin/ruby"):
            return "ruby", "/usr/bin/ruby"
        if os.path.exists("/usr/bin/perl"):
            return "perl", "/usr/bin/perl"
        if os.path.exists("/usr/bin/python3"):
            return "python", "/usr/bin/python3"

    if preferred_python and os.path.exists(preferred_python):
        return "python", preferred_python
    return "python", sys.executable


def verify_bridge_endpoint(
    bridge_host: str,
    bridge_port: int,
    target_host: str,
    timeout: float = 2.0,
) -> Tuple[bool, Optional[Exception]]:
    """Verify that traffic sent to the bridge actually reaches the remote service and gets a response or socket connection."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((bridge_host, bridge_port))
        probe = f"GET /status HTTP/1.1\r\nHost: {target_host}\r\nUser-Agent: ushareiplay-probe\r\nConnection: close\r\n\r\n".encode()
        s.sendall(probe)
        resp = s.recv(256)
        if not resp:
            return False, ConnectionError("Bridge connection to target closed immediately (target unreachable or blocked).")
        return True, None
    except Exception as e:
        return False, e
    finally:
        try:
            s.close()
        except Exception:
            pass


def ensure_appium_endpoint(
    host: str,
    port: int,
    timeout: float = 2.0,
    allow_bridge: bool = True,
) -> Tuple[str, int, Optional[LocalNetworkBridge]]:
    """Ensure Appium endpoint is reachable, automatically spawning a local bridge if macOS Local Network restriction is detected."""
    is_ok, err = check_socket_connectivity(host, port, timeout=timeout)
    if is_ok:
        return host, int(port), None

    if allow_bridge and platform.system() == "Darwin" and is_macos_local_network_error(err):
        bridge = LocalNetworkBridge(target_host=host, target_port=port)
        try:
            b_port = bridge.start(timeout=5.0)
            # Verify local bridge reachability
            b_ok, b_err = check_socket_connectivity(bridge.bridge_host, b_port, timeout=timeout)
            if b_ok:
                if isinstance(b_port, int) and b_port > 0:
                    v_ok, v_err = verify_bridge_endpoint(bridge.bridge_host, b_port, target_host=host, timeout=timeout)
                    if not v_ok:
                        bridge.stop()
                        diag = diagnose_connection_error(host, port, v_err or Exception("Bridge verification failed"))
                        raise ConnectionError(diag)

                print(
                    f"[LocalNetworkBridge] 检测到 macOS 本地网络限制 (Errno 65)，已自动启用系统代理桥接 ({bridge.runner_type}): "
                    f"127.0.0.1:{b_port} -> {host}:{port}"
                )
                return bridge.bridge_host, b_port, bridge
            else:
                bridge.stop()
        except Exception as e:
            bridge.stop()
            if isinstance(e, ConnectionError):
                raise

    diag = diagnose_connection_error(host, port, err if err is not None else Exception("Connection failed"))
    raise ConnectionError(diag)
