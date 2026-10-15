---
name: clash-xiaoyuanwang-skill
description: Clash Verge / mihomo 节点大面积超时的诊断与修复。用于校园网或家宽出口对机场 CDN 入口做 /32 单 IP 精确封锁的场景(SYN 静默丢包、同 /24 邻居可达、服务器存活、换网络即恢复)。提供封锁判别方法论、全 /24 WebSocket 握手扫描器(HTTP 101 验收)与 Clash Verge 全局扩展脚本模板——换可达 IP + 克隆副本, 由 url-test 自动测活选优。仅当用户明确要求使用本 skill 时加载, 不自动触发。
license: MIT
agent_created: true
---

# Clash CDN 入口封锁诊断与节点复活

> **调度约定**: 本 skill 不自动触发。仅当用户明确要求使用(如指名
> clash-xiaoyuanwang-skill)时加载执行。

## 场景

校园网 / 家宽出口对机场 CDN 入口 IP 做精确到 /32 的单 IP 封锁(SYN 静默丢包)，
表现为大面积节点超时，但订阅正常、手机 5G 同订阅可用。核心机制：CF Anycast
同段邻居 IP 提供相同节点服务(同一后端 Xray)，换入口即可复活。

## 工作流

### 0. 判断是不是 IP 级封锁(不要跳过)

对照 `references/diagnosis.md` 五判据：SYN 超时(非 RST) / tracert 断在国际出口前 /
同 /24 邻居可达 / 境外回连有响应(服务器活着) / 换网络恢复正常。
DoH 对照排除 DNS 污染(扫描脚本已内置)。

### 1. 扫候选池

```bash
python scripts/clash_ip_scan.py --nodes <clash-verge.yaml> --proxy http://127.0.0.1:7897
```

自动完成：提取 vless+ws 节点 → DNS/DoH 对照 → TCP 可达性 → 对被封 IP 的 /24
全段用**节点真实 SNI + ws path** 发 WS 握手 → 以 `HTTP/1.1 101` 验收 → 输出
RTT 排序的候选池(`scan_result.json` + 可直接粘贴的 POOLS 片段)。

**必须用 WS 握手而非裸 GET**：Xray 对非 WS 请求返回 400、CF 边缘可能 403，
裸 GET 的 403 会误导成“被拒”。详见 `references/diagnosis.md`。

### 2. 写入全局脚本

把 `scripts/verge_script_template.js` + 扫出的 POOLS 交给用户，粘贴到
**Clash Verge → 订阅页 → 全局扩展脚本**。全局版按 server 域名匹配所有订阅，
不锁定具体订阅链接。逻辑：命中节点换首选 IP(名字不变) + 克隆 3 个不同入口副本，
副本只插入 url-test/fallback 组；手动选择组、信息节点、非命中节点一律不动。

### 3. 验证

- 用户更新或重新激活任一订阅即生效
- 节点列表出现 `·IP1/·IP2/·IP3` 副本且延迟正常；或用
  `scripts/pipe_delay.ps1` 复诊全节点延迟(注意：pipe 名按机器改)

## 自动化分工(向用户讲清)

- **脚本(配置期)**: 静态枚举候选，订阅更新时跑一次。沙箱无网络能力，不能现场测速
- **url-test(运行时)**: 每 300s 对全部副本现场测活，通哪个走哪个，新被封的自动沉底
- 维护：池内单 IP 被封 → 自动跳过；**整个池失效** → 重跑扫描器更新 POOLS

## resources

- `references/diagnosis.md` — 五判据、反证清单、为什么必须 WS 握手验收
- `references/pitfalls.md` — 环境坑：mihomo named pipe + chunked、沙箱 curl 走代理、
  临时实例随会话退出
- `scripts/clash_ip_scan.py` — 主扫描器，输出 POOLS
- `scripts/verge_script_template.js` — 全局扩展脚本模板
- `scripts/pipe_delay.ps1` — named pipe 复诊全节点延迟
