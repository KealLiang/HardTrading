"""诊断：Python(requests) 运行时到底走代理还是直连（只探测，不改动业务代码）。

检查顺序：
1) 进程环境变量代理
2) Windows 注册表「Internet 选项」代理（ProxyEnable/ProxyServer/AutoConfigURL/ProxyOverride）
3) urllib.request.getproxies() —— requests 实际读取的代理来源（Windows 含注册表）
4) 出口 IP：代理模式 vs 直连模式对比
5) 东财请求实际连到哪：socket peername 是代理端口(127.0.0.1:7890 之类)还是东财真实 IP

运行：python tests/test_proxy_egress.py
"""
from __future__ import annotations

import os
import socket
import urllib.request

import requests

EGRESS_URLS = [
    "https://api.ipify.org?format=json",
    "https://httpbin.org/ip",
    "https://myip.ipip.net",
    "https://ifconfig.me/ip",
]

EM_URL = "https://push2.eastmoney.com/api/qt/clist/get"
EM_PARAMS = {"pn": "1", "pz": "1", "po": "1", "np": "1",
             "ut": "bd1d9ddb04089700cf9c27f6f7426281", "fltt": "2", "invt": "2",
             "fid": "f12", "fs": "m:0 t:6", "fields": "f12,f14"}


def show_env() -> None:
    print("=" * 60)
    print("1) 进程环境变量")
    found = {k: v for k, v in os.environ.items() if "proxy" in k.lower()}
    print(f"   {found or '无'}")


def show_registry() -> None:
    print("=" * 60)
    print("2) Windows 注册表 Internet Settings（系统代理）")
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
        for name in ("ProxyEnable", "ProxyServer", "AutoConfigURL", "ProxyOverride"):
            try:
                print(f"   {name} = {winreg.QueryValueEx(key, name)[0]!r}")
            except FileNotFoundError:
                print(f"   {name} = <未设置>")
        print("   注：requests 不解析 AutoConfigURL(PAC)，只认 ProxyServer(明文 http=..;https=..)")
    except Exception as e:
        print(f"   读取失败: {e}")


def show_getproxies() -> None:
    print("=" * 60)
    print("3) urllib.request.getproxies()（requests trust_env 的来源）")
    print(f"   {urllib.request.getproxies()}")


def egress_ip(session: requests.Session, label: str) -> str:
    for u in EGRESS_URLS:
        try:
            r = session.get(u, timeout=8)
            return f"{label}: {r.text.strip()[:80]}  (via {u})"
        except Exception as e:
            last = f"{type(e).__name__}"
    return f"{label}: 全部回显站点失败 ({last})"


def show_egress() -> None:
    print("=" * 60)
    print("4) 出口 IP 对比")
    print("   " + egress_ip(requests.Session(), "默认(trust_env=True)"))
    s = requests.Session()
    s.trust_env = False
    print("   " + egress_ip(s, "直连(trust_env=False)"))


def show_em_peer() -> None:
    print("=" * 60)
    print("5) 东财请求实际连到哪（peername=代理端口说明走代理，=东财IP说明直连）")
    try:
        print(f"   DNS push2.eastmoney.com -> {socket.gethostbyname('push2.eastmoney.com')}")
    except Exception as e:
        print(f"   DNS 失败: {e}")
    for label, trust in (("默认", True), ("直连", False)):
        s = requests.Session()
        s.trust_env = trust
        try:
            r = s.get(EM_URL, params=EM_PARAMS, timeout=12,
                      headers={"User-Agent": "Mozilla/5.0"})
            peer = None
            for attr in ("_connection", "connection"):
                conn = getattr(r.raw, attr, None)
                sock = getattr(conn, "sock", None)
                if sock is not None:
                    try:
                        peer = sock.getpeername()
                        break
                    except Exception:
                        pass
            print(f"   {label}: status={r.status_code} bytes={len(r.content)} peer={peer}")
        except Exception as e:
            print(f"   {label}: {type(e).__name__}: {str(e)[:80]}")


def show_socket_trace() -> None:
    """6) 直接看 socket 连的是代理端口还是东财真实 IP（最硬的判据）"""
    print("=" * 60)
    print("6) socket 连接目标追踪（连 127.0.0.1:7897 之类=走代理；连东财IP=直连）")
    origin = socket.create_connection
    hits = []

    def traced(addr, *a, **kw):
        hits.append(addr)
        return origin(addr, *a, **kw)

    socket.create_connection = traced
    for label, trust in (("默认(trust_env=True)", True), ("直连(trust_env=False)", False)):
        hits.clear()
        s = requests.Session()
        s.trust_env = trust
        try:
            r = s.get(EM_URL, params=EM_PARAMS, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
            print(f"   {label}: status={r.status_code} -> connect {hits}")
        except Exception as e:
            print(f"   {label}: {type(e).__name__} -> connect {hits}")
    socket.create_connection = origin


if __name__ == "__main__":
    show_env()
    show_registry()
    show_getproxies()
    show_egress()
    show_em_peer()
    show_socket_trace()
