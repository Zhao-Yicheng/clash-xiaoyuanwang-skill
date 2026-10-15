#!/usr/bin/env python3
"""CDN 入口 IP 封锁诊断 + 候选池扫描（方案 A 的核心工具）

用法:
  python clash_ip_scan.py --nodes <clash运行时配置.yaml> [--extra-ip 1.2.3.4 ...]

流程:
  1. 从 Clash 运行时配置提取所有 vless 节点的 (server 域名, servername, ws path)
  2. 对每个 server 域名: 国内 DNS 解析现 IP(带 DoH 对照), 记录被封入口
  3. 对被封 IP 的 /24 全段发标准 WS 握手包(SNI=节点真实 servername, path=节点真实 path)
  4. 以 HTTP/1.1 101 Switching Protocols 为验收标准 —— 这是 Xray/VLESS 服务端
     接受节点的决定性证据(裸 GET 会被 403/400 误导)
  5. 输出按 RTT 排序的候选 IP 池, 并直接生成 Clash Verge 全局脚本的 POOLS 片段

注意:
  - 禁用系统代理直连测(DNS 污染环境先用 --proxy 走代理做 DoH 对照)
  - 不写死任何 IP; 候选池每次现场扫出来
"""
import argparse, base64, json, os, socket, ssl, subprocess, sys, time
import asyncio
import concurrent.futures

TIMEOUT = 3.0
CONC = 48


def curl_doh(domain, proxy=None):
    """DoH 查真实 IP(可选经代理)。失败返回 []"""
    cmd = ["curl", "-sS", "-m", "8", f"https://dns.google/resolve?name={domain}&type=A"]
    if proxy:
        cmd += ["-x", proxy]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=12).stdout
        import re
        return re.findall(r'"data":"(\d+\.\d+\.\d+\.\d+)"', out)
    except Exception:
        return []


def query_dns(domain, server="223.5.5.5"):
    """系统 nslookup 查国内解析"""
    try:
        out = subprocess.run(["nslookup", domain, server], capture_output=True, timeout=10).stdout
        return [l.split()[-1] for l in out.decode("utf-8", "replace").splitlines()
                if l.strip().startswith(("Address", "Addresses")) and "223.5" not in l]
    except Exception:
        return []


def ws_probe(ip, host, path):
    """TCP + TLS(SNI) + 标准 WS 握手。返回 dict"""
    out = {"ip": ip, "host": host, "tcp": "no"}
    try:
        sock = socket.create_connection((ip, 443), timeout=TIMEOUT)
    except Exception as e:
        out["tcp"] = type(e).__name__
        return out
    out["tcp"] = "open"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    t0 = time.time()
    try:
        tls = ctx.wrap_socket(sock, server_hostname=host)
    except Exception as e:
        out["tls"] = type(e).__name__
        sock.close()
        return out
    out["rtt"] = round((time.time() - t0) * 1000)
    key = base64.b64encode(os.urandom(16)).decode()
    req = (f"GET {path} HTTP/1.1\r\nHost: {host}\r\nConnection: Upgrade\r\n"
           f"Upgrade: websocket\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
    try:
        tls.sendall(req.encode())
        tls.settimeout(2)
        resp = tls.recv(128)
        out["http"] = resp.split(b"\r\n")[0].decode("utf-8", "replace")
    except Exception as e:
        out["http"] = type(e).__name__
    finally:
        tls.close()
    return out


def load_nodes(yaml_path):
    """从 Clash 运行时配置提 vless+ws 节点。无 yaml 库时回退到文本解析"""
    nodes = []
    try:
        import yaml
        cfg = yaml.safe_load(open(yaml_path, encoding="utf-8"))
        for p in cfg.get("proxies", []):
            if p.get("type") == "vless" and p.get("network") == "ws":
                nodes.append({
                    "name": p["name"],
                    "server": p["server"],
                    "servername": p.get("servername", p["server"]),
                    "path": p.get("ws-opts", {}).get("path", "/"),
                })
        return nodes
    except Exception:
        pass
    # 文本解析兜底
    cur = {}
    for line in open(yaml_path, encoding="utf-8"):
        s = line.strip()
        if s.startswith("- name:"):
            if cur.get("type") == "vless":
                nodes.append(cur)
            cur = {"name": s[7:].strip()}
        elif s.startswith("type:") and "vless" in s:
            cur["type"] = "vless"
        elif s.startswith("server:"):
            cur["server"] = s[8:].strip()
        elif s.startswith("servername:"):
            cur["servername"] = s[12:].strip()
        elif s.startswith("path:"):
            cur["path"] = s[6:].strip()
    if cur.get("type") == "vless":
        nodes.append(cur)
    seen = set()
    uniq = []
    for n in nodes:
        k = (n["server"], n.get("servername"), n.get("path"))
        if k not in seen:
            seen.add(k)
            uniq.append(n)
    return uniq


async def scan(target_pairs):
    """并发扫描 [(ip, host, path)]，返回全部结果"""
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(CONC)

    async def run(*w):
        async with sem:
            return await loop.run_in_executor(None, ws_probe, *w)

    return await asyncio.gather(*[run(*t) for t in target_pairs])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--nodes", required=True, help="Clash 运行时配置 yaml 路径")
    ap.add_argument("--proxy", default=None, help="做 DoH 对照用的代理 http://127.0.0.1:7897")
    ap.add_argument("--top", type=int, default=14, help="每域名取前 N 个候选")
    ap.add_argument("--scan-24", action="store_true", default=True, help="扫被封IP的/24全段")
    args = ap.parse_args()

    nodes = load_nodes(args.nodes)
    print(f"提取 vless+ws 节点 {len(nodes)} 个")
    servers = sorted({n["server"] for n in nodes if not n["server"].replace(".", "").isdigit()})

    # 1) 解析每个 server 域名, 对比国内 vs DoH
    server_map = {}
    for dom in servers:
        cn = query_dns(dom)
        doh = curl_doh(dom, args.proxy)
        server_map[dom] = {"cn": cn, "doh": doh}
        print(f"  {dom}  国内DNS={cn}  DoH={doh}")

    # 2) 找被封入口: TCP 连不上的 IP
    print("\n=== 检测入口 IP 可达性(直连) ===")
    blocked = {}
    for dom, m in server_map.items():
        ips = list(set(m["cn"] + m["doh"]))
        for ip in ips:
            try:
                socket.create_connection((ip, 443), timeout=4).close()
                status = "通"
            except Exception as e:
                status = f"不通({type(e).__name__})"
                blocked.setdefault(dom, []).append(ip)
            print(f"  {ip:<16} {dom:<28} {status}")

    if not blocked:
        print("\n没有入口域名被封 —— 节点超时可能是别的原因(服务器故障/机场维护), 走别的诊断路径。")
        return

    # 3) 对被封 IP 的 /24 全段做 WS 握手扫描(用该域名的真实节点参数)
    print(f"\n=== 被封入口: {list(blocked.keys())} —— 开始 /24 WS 握手扫描 ===")
    pairs_by_domain = {}
    for dom, ips in blocked.items():
        ns = [n for n in nodes if n["server"] == dom]
        if not ns:
            continue
        # 每个域名取最多 3 组不同的 (servername, path)
        seen = set()
        probes = []
        for n in ns:
            k = (n["servername"], n["path"])
            if k in seen:
                continue
            seen.add(k)
            probes.append((n["servername"], n["path"]))
            if len(probes) >= 3:
                break
        targets = []
        for base in ips:
            prefix = ".".join(base.split(".")[:3])
            for i in range(256):
                for sni, path in probes:
                    targets.append((f"{prefix}.{i}", sni, path))
        pairs_by_domain[dom] = (targets, probes)

    results_by_dom = {}
    for dom, (targets, probes) in pairs_by_domain.items():
        print(f"\n扫描 {dom} /24×{len(probes)}路: {len(targets)} 探测")
        t0 = time.time()
        results_by_dom[dom] = asyncio.run(scan(targets))
        ok = [r for r in results_by_dom[dom] if r.get("http", "").startswith("HTTP/1.1 101")]
        print(f"  耗时 {time.time()-t0:.0f}s, WS 握手成功(101): {len(ok)}")

    # 4) 生成 POOLS 片段
    print("\n=== 生成 POOLS 片段(填入 Clash Verge 全局脚本) ===")
    pools = {}
    for dom, results in results_by_dom.items():
        ok = {}
        for r in results:
            if r.get("http", "").startswith("HTTP/1.1 101"):
                ok.setdefault(r["ip"], min(ok.get(r["ip"], 99999), r.get("rtt", 99999)))
        top = sorted(ok.items(), key=lambda x: x[1])[:args.top]
        pools[dom] = [ip for ip, _ in top]
        print(f'  "{dom}": {json.dumps(pools[dom])}')

    out = {
        "blocked_entries": blocked,
        "pools": pools,
        "note": "候选池由 /24 WS 握手 101 扫描得出; 填入 scripts/verge_script_template.js 的 POOLS",
    }
    with open("scan_result.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print("\n已写 scan_result.json")


if __name__ == "__main__":
    main()
