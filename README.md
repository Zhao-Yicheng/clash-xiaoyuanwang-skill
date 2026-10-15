# clash-xiaoyuanwang-skill

> 破解部分校园网（家宽出口同理）对机场订阅节点 CDN 入口的 /32 单 IP 精确封锁。

## 这是什么

部分校园网 / 家宽出口会对代理订阅的 CDN 入口 IP 做**精确到单个 IP 的封锁**
（TCP SYN 静默丢包），表现为 Clash / mihomo 里大面积节点超时，但订阅本身正常、
换一个网络（如手机 5G）又能用。

利用 Cloudflare Anycast 的特性——同一 /24 网段的邻居 IP 提供完全相同的节点服务
（同一台后端 Xray）——把节点入口换到可达的邻居 IP，再由内核 `url-test` 周期性
现场测活、自动选优，实现长期自动容错。

## 安装

作为 agent skill 使用（兼容 Claude Code / Copilot / WorkBuddy 等 skills 目录规范）：

```bash
git clone https://github.com/Zhao-Yicheng/clash-xiaoyuanwang-skill.git
# 拷进你的 skills 目录，如：
cp -r clash-xiaoyuanwang-skill ~/.claude/skills/      # Claude Code
cp -r clash-xiaoyuanwang-skill ~/.workbuddy/skills/   # WorkBuddy
```

脚本也可以脱离 skill 直接当命令行工具用。

## 快速开始

```bash
# 1. 扫候选池（需要 Python 3.8+，无第三方依赖）
python scripts/clash_ip_scan.py --nodes "%APPDATA%\io.github.clash-verge-rev.clash-verge-rev\clash-verge.yaml"

# 2. 把扫描输出的 POOLS 片段填进全局脚本模板
#    编辑 scripts/verge_script_template.js 里的 POOLS

# 3. 粘贴到 Clash Verge → 订阅页 → 全局扩展脚本，更新任一订阅即生效
```

扫描器内置封锁判别：国内 DNS / DoH 对照、TCP 可达性检测、
全 /24 段 WebSocket 握手探测（以 `HTTP/1.1 101` 为验收标准，
裸 GET 的 403/400 会误判）、按 RTT 排序输出候选池。

## 工作原理

| 环节 | 职责 |
|---|---|
| `clash_ip_scan.py` | 配置期：扫出当前网络环境下可达的候选 IP 池 |
| 全局扩展脚本 | 配置期：把被封节点换到首选 IP，并克隆 N 个不同入口的副本 |
| 内核 `url-test` | 运行时：每 300s 现场测活，哪个通走哪个，新被封的自动沉底 |

脚本只做静态数据加工（沙箱里没有网络能力），现场测活完全交给内核，
两者分工不重叠。池里某个 IP 再被封 → 自动跳过无需干预；
整个池失效（罕见）→ 重跑扫描器更新 POOLS 即可。

## 前置确认（是不是 IP 级封锁）

扫描只在**入口 IP 被 /32 精确封锁**时有效，先对照
[references/diagnosis.md](references/diagnosis.md) 的五个判据：

1. 失败是 TCP SYN **超时**（不是 RST、不是 TLS 重置）
2. `tracert` 在进入国际出口**之前**断掉
3. 被封 IP 的同 /24 邻居可达（证明是 /32 精确而非网段封锁）
4. 经境外代理回连被封 IP 能拿到 HTTP 响应（服务器活着，单向封锁）
5. 同一订阅在别的网络（手机 5G）正常（排除机场故障）

## 适用场景

- 校园网出口封了机场 CDN 的个别入口 IP
- 节点全超时但订阅更新正常；手机 5G 同订阅可用
- VLESS + WebSocket + TLS（Cloudflare 中转）类节点

## 免责声明

本项目仅用于网络连通性诊断与学习研究。请遵守所在国家 / 地区法律法规
及所在网络的管理规定，在有权使用的网络环境下使用。

## 许可证

[MIT](LICENSE)
