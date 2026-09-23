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
    """Transparent TCP forwarder running via system Python to bypass macOS Local Network Privacy restrictions."""

    def __init__(self, target_host: str, target_port: int, system_python: str = "/usr/bin/python3"):
        self.target_host = target_host
        self.target_port = int(target_port)
        self.system_python = system_python
        self.bridge_host = "127.0.0.1"
        self.bridge_port = 0
        self._process: Optional[subprocess.Popen] = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, timeout: float = 5.0) -> int:
        if self.is_running:
            return self.bridge_port

        if not os.path.exists(self.system_python):
            raise RuntimeError(f"System Python not found at {self.system_python}, cannot start bridge.")

        bridge_code = f"""
import socket, threading, sys, signal

target_host = {self.target_host!r}
target_port = {self.target_port}

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind(('127.0.0.1', 0))
port = server.getsockname()[1]
server.listen(64)
print(f'PORT:{{port}}', flush=True)

def forward(src, dst):
    try:
        while True:
            data = src.recv(8192)
            if not data:
                break
            dst.sendall(data)
    except Exception:
        pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def accept_loop():
    while True:
        try:
            client, _ = server.accept()
            remote = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            remote.connect((target_host, target_port))
            threading.Thread(target=forward, args=(client, remote), daemon=True).start()
            threading.Thread(target=forward, args=(remote, client), daemon=True).start()
        except Exception:
            break

threading.Thread(target=accept_loop, daemon=True).start()

def sig_handler(signum, frame):
    try: server.close()
    except: pass
    sys.exit(0)

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

try:
    signal.pause()
except (AttributeError, Exception):
    import time
    while True:
        time.sleep(1)
"""
        self._process = subprocess.Popen(
            [self.system_python, "-c", bridge_code],
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
                raise RuntimeError(f"Bridge process terminated unexpectedly: {stderr}")

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
        sys_py = "/usr/bin/python3"
        if os.path.exists(sys_py):
            bridge = LocalNetworkBridge(target_host=host, target_port=port, system_python=sys_py)
            try:
                b_port = bridge.start(timeout=5.0)
                # Verify local bridge reachability
                b_ok, b_err = check_socket_connectivity(bridge.bridge_host, b_port, timeout=2.0)
                if b_ok:
                    print(
                        f"[LocalNetworkBridge] 检测到 macOS 本地网络限制 (Errno 65)，已自动启用系统代理桥接: "
                        f"127.0.0.1:{b_port} -> {host}:{port}"
                    )
                    return bridge.bridge_host, b_port, bridge
                else:
                    bridge.stop()
            except Exception:
                bridge.stop()

    diag = diagnose_connection_error(host, port, err if err is not None else Exception("Connection failed"))
    raise ConnectionError(diag)
