import errno
import socket
import sys
import threading
from unittest.mock import patch, MagicMock

import pytest

from ushareiplay.core.network_bridge import (
    is_macos_local_network_error,
    diagnose_connection_error,
    LocalNetworkBridge,
    ensure_appium_endpoint,
    select_bridge_runner,
    verify_bridge_endpoint,
)


def test_is_macos_local_network_error_with_oserror():
    err = OSError(65, "No route to host")
    assert is_macos_local_network_error(err) is True


def test_is_macos_local_network_error_with_nested_exception():
    class DummyNewConnectionError(Exception):
        pass

    class DummyMaxRetryError(Exception):
        pass

    inner = DummyNewConnectionError("Failed to establish a new connection: [Errno 65] No route to host")
    outer = DummyMaxRetryError(f"Max retries exceeded with url: /session (Caused by {inner})")
    assert is_macos_local_network_error(outer) is True


def test_is_macos_local_network_error_negative():
    err = ConnectionRefusedError(errno.ECONNREFUSED, "Connection refused")
    assert is_macos_local_network_error(err) is False


def test_diagnose_connection_error_contains_guidance():
    err = OSError(65, "No route to host")
    msg = diagnose_connection_error("192.168.8.103", 4723, err)
    assert "192.168.8.103:4723" in msg
    assert "macOS" in msg
    assert "本地网络" in msg
    assert "run.sh" in msg


def test_local_network_bridge_loopback_forwarding():
    # 模拟真实远程目标（本地起一个 echo server 代表 appium）
    target_server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    target_server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    target_server.bind(("127.0.0.1", 0))
    target_port = target_server.getsockname()[1]
    target_server.listen(1)

    received_data = []

    def target_worker():
        conn, _ = target_server.accept()
        data = conn.recv(1024)
        received_data.append(data)
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nOK")
        conn.close()

    t = threading.Thread(target=target_worker, daemon=True)
    t.start()

    bridge = LocalNetworkBridge("127.0.0.1", target_port)
    bridge.start(timeout=5.0)

    try:
        assert bridge.is_running
        assert bridge.bridge_port > 0
        assert bridge.bridge_host == "127.0.0.1"

        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect((bridge.bridge_host, bridge.bridge_port))
        client.sendall(b"PING")
        resp = client.recv(1024)
        client.close()

        assert b"200 OK" in resp
        assert received_data == [b"PING"]
    finally:
        bridge.stop()
        target_server.close()
        assert not bridge.is_running


def test_ensure_appium_endpoint_when_direct_connection_succeeds():
    with patch("ushareiplay.core.network_bridge.check_socket_connectivity", return_value=(True, None)):
        host, port, bridge = ensure_appium_endpoint("192.168.8.103", 4723)
        assert host == "192.168.8.103"
        assert port == 4723
        assert bridge is None


def test_ensure_appium_endpoint_auto_bridge_on_errno_65():
    with patch("ushareiplay.core.network_bridge.check_socket_connectivity") as mock_conn:
        mock_conn.side_effect = [
            (False, OSError(65, "No route to host")),
            (True, None),
        ]
        with patch.object(LocalNetworkBridge, "start") as mock_start:
            host, port, bridge = ensure_appium_endpoint("192.168.8.103", 4723)
            assert host == "127.0.0.1"
            assert bridge is not None
            mock_start.assert_called_once()
            bridge.stop()


def test_select_bridge_runner_on_darwin():
    with patch("platform.system", return_value="Darwin"):
        with patch("os.path.exists") as mock_exists:
            # Case 1: ruby exists
            mock_exists.side_effect = lambda p: p == "/usr/bin/ruby"
            r_type, r_path = select_bridge_runner("192.168.8.103", 4723)
            assert r_type == "ruby"
            assert r_path == "/usr/bin/ruby"

            # Case 2: ruby absent, perl exists
            mock_exists.side_effect = lambda p: p == "/usr/bin/perl"
            r_type, r_path = select_bridge_runner("192.168.8.103", 4723)
            assert r_type == "perl"
            assert r_path == "/usr/bin/perl"

            # Case 3: loopback target always uses python
            r_type, r_path = select_bridge_runner("127.0.0.1", 4723)
            assert r_type == "python"


def test_verify_bridge_endpoint_success():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    def worker():
        conn, _ = server.accept()
        _ = conn.recv(1024)
        conn.sendall(b"HTTP/1.1 200 OK\r\n\r\n{\"value\":{\"ready\":true}}")
        conn.close()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    ok, err = verify_bridge_endpoint("127.0.0.1", port, "192.168.8.103", timeout=2.0)
    server.close()
    assert ok is True
    assert err is None


def test_verify_bridge_endpoint_immediate_close_fails():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    port = server.getsockname()[1]
    server.listen(1)

    def worker():
        conn, _ = server.accept()
        conn.close()

    t = threading.Thread(target=worker, daemon=True)
    t.start()

    ok, err = verify_bridge_endpoint("127.0.0.1", port, "192.168.8.103", timeout=2.0)
    server.close()
    assert ok is False
    assert err is not None


def test_ensure_appium_endpoint_stops_bridge_when_verification_fails():
    with patch("ushareiplay.core.network_bridge.check_socket_connectivity") as mock_conn:
        mock_conn.side_effect = [
            (False, OSError(65, "No route to host")),
            (True, None),
        ]
        with patch.object(LocalNetworkBridge, "start", return_value=12345):
            with patch("ushareiplay.core.network_bridge.verify_bridge_endpoint", return_value=(False, ConnectionError("Probe failed"))):
                with pytest.raises(ConnectionError) as exc_info:
                    ensure_appium_endpoint("192.168.8.103", 4723)
                assert "无法连接到 Appium 服务器" in str(exc_info.value)

