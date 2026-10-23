#!/usr/bin/env python3
"""探测座位面板在各种状态下能被 Appium 数到多少张桌位。

为什么需要这个：座位面板是一个 RecyclerView，面板展开与否决定座位带视口的高度，
而 RecyclerView 只把「视口内 + 被裁切的残片」物化成节点：

    面板收起（按钮写「展开座位」）  → 视口 ~290px → 2 张完整桌 + 2 张残片 = 4 个节点
    面板展开（按钮写「收起座位」）  → 视口 ~513px → 4 张完整桌 + 2 张残片 = 6 个节点

所以「展开状态下无论滚到哪都是 6」是成立的（真机实测），而
`found 4 desks, expected 6` 的真实含义是**扫描的那一刻面板已经被收起了**。

选择器与 Appium 地址都从 `config.yaml` 读（元素选择器的唯一事实源）。

用法：
    uv run python scripts/probe_seat_desk_count.py              # 自动发现 session
    uv run python scripts/probe_seat_desk_count.py --host 192.168.8.103:4723
    uv run python scripts/probe_seat_desk_count.py --no-toggle  # 只读，不点按钮
"""

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config.yaml"


def load_config():
    with CONFIG_PATH.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class AppiumClient:
    """Appium HTTP 客户端（只做这个脚本需要的几件事）。"""

    def __init__(self, host, session):
        self.base = f"http://{host}"
        self.session = session

    def request(self, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            self.base + path, data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)

    def source(self):
        return self.request("GET", f"/session/{self.session}/source")["value"]

    def find(self, selector):
        """按选择器找元素：resource-id 走 id 策略，XPath 走 xpath 策略。"""
        using = "xpath" if selector.startswith(("/", "(")) else "id"
        return self.request("POST", f"/session/{self.session}/element",
                            {"using": using, "value": selector})["value"]["ELEMENT"]

    def click(self, selector):
        element_id = self.find(selector)
        self.request("POST", f"/session/{self.session}/element/{element_id}/click", {})
        time.sleep(1.5)

    def swipe(self, start_x, start_y, end_x, end_y, duration_ms=400):
        """在指定坐标滑动一次。

        走 W3C actions —— 与生产 `GestureHandler.swipe` 完全同源：那个方法最终调的是
        `driver.swipe()`，而 Appium-Python-Client 3.x 的 `driver.swipe()` 本身就是
        pointerMove/pointerDown/pointerUp 这套 W3C 动作。这里只是同一个动作的
        HTTP 形态（本脚本不启动整套 bot，拿不到 driver 对象）。
        """
        self.request("POST", f"/session/{self.session}/actions", {"actions": [{
            "type": "pointer", "id": "f1", "parameters": {"pointerType": "touch"},
            "actions": [
                {"type": "pointerMove", "duration": 0, "x": start_x, "y": start_y},
                {"type": "pointerDown", "button": 0},
                {"type": "pause", "duration": 120},
                {"type": "pointerMove", "duration": duration_ms, "x": end_x, "y": end_y},
                {"type": "pointerUp", "button": 0},
            ],
        }]})
        time.sleep(1.2)


def attributes(tag):
    return dict(re.findall(r'([\w-]+)="([^"]*)"', tag))


def read_state(client, desk_selector, button_selector):
    src = client.source()
    tags = re.findall(r'<[\w.]+[^>]*>', src)
    parsed = [attributes(t) for t in tags]

    button = next((a for a in parsed if a.get("resource-id") == button_selector), None)
    desks = []
    for a in parsed:
        if a.get("resource-id") != desk_selector:
            continue
        m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", a.get("bounds", ""))
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            desks.append({"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1})

    band = None
    for i, a in enumerate(parsed):
        if a.get("resource-id") == desk_selector:
            for j in range(i - 1, max(0, i - 4), -1):
                b = parsed[j].get("bounds")
                if b and parsed[j].get("resource-id") != desk_selector:
                    m = re.match(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]", b)
                    x1, y1, x2, y2 = map(int, m.groups())
                    if y2 - y1 > 200:
                        band = {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}
                        break
            break
    return {"button": button, "desks": desks, "band": band}


def report(client, label, desk_selector, button_selector):
    st = read_state(client, desk_selector, button_selector)
    full = [d for d in st["desks"] if d["h"] >= 100]
    btn_text = st["button"].get("text") if st["button"] else None
    print(f"\n=== {label} ===")
    print(f"  面板按钮 : {btn_text!r}")
    print(f"  桌位节点 : {len(st['desks'])}  (完整 {len(full)} / 残片 {len(st['desks']) - len(full)})")
    for i, d in enumerate(st["desks"]):
        kind = "完整" if d["h"] >= 100 else "残片"
        print(f"     桌#{i + 1}: {kind}  y={d['y']:>4} h={d['h']:>3}")
    if st["band"]:
        print(f"  座位带视口: y={st['band']['y']} h={st['band']['h']}")
    return st


def discover(host):
    with urllib.request.urlopen(f"http://{host}/sessions", timeout=10) as r:
        sessions = json.load(r).get("value") or []
    if not sessions:
        sys.exit(f"no active Appium session on {host}")
    return sessions[0]["id"]


def main():
    config = load_config()
    appium = config["appium"]
    elements = config["soul"]["elements"]
    desk_selector = elements["seat_desk"]
    button_selector = elements["expand_seats"]
    default_host = f"{appium['host']}:{appium['port']}"

    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default=default_host)
    ap.add_argument("--session", default=None)
    ap.add_argument("--no-toggle", action="store_true",
                    help="只读探测，不点击展开/收起按钮")
    args = ap.parse_args()

    session = args.session or discover(args.host)
    client = AppiumClient(args.host, session)
    print(f"appium={args.host}  session={session}")

    st = report(client, "初始状态", desk_selector, button_selector)
    if args.no_toggle:
        return

    text = st["button"].get("text", "") if st["button"] else ""
    if "展开" in text:
        client.click(button_selector)
        st = report(client, "点「展开座位」之后", desk_selector, button_selector)

    if st["band"]:
        b = st["band"]
        cx = b["x"] + b["w"] // 2
        client.swipe(cx, b["y"] + b["h"] - 60, cx, b["y"] + 60, 500)
        report(client, "展开后向上滑（座位带内）", desk_selector, button_selector)
        client.swipe(cx, b["y"] + 60, cx, b["y"] + b["h"] - 60, 500)
        report(client, "展开后向下滑（座位带内）", desk_selector, button_selector)

    text = st["button"].get("text", "") if st["button"] else ""
    if "收起" in text:
        client.click(button_selector)
        report(client, "点「收起座位」还原", desk_selector, button_selector)


if __name__ == "__main__":
    main()
