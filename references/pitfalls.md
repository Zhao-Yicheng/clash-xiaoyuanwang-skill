# 环境坑（踩过的，别人也会踩）

## mihomo external-controller 是 named pipe，不是 TCP 端口

Clash Verge Rev 的内核默认用 named pipe 暴露 API（`verge-mihomo-sidecar-...`），
不是 `127.0.0.1:9090`。查 API 要走 pipe，且响应是 chunked 编码——
PowerShell 的 `Invoke-RestMethod` 会解析失败，手动发 **HTTP/1.0** 请求避开：

```
GET /version HTTP/1.0`r`nHost: localhost`r`nAuthorization: Bearer <secret>`r`n`r`n
```

secret 在 `clash-verge.yaml` 里。延迟测试端点：
`GET /proxies/<节点名URL编码>/delay?url=...&timeout=5000`。
`scripts/pipe_delay.ps1` 里的 pipe 名含机器相关哈希，按机器改。

## Git Bash / 沙箱相关

- **curl 默认走沙箱代理**：直连测试先 `--noproxy "*"` 或 `env | grep -i proxy` 确认，
  否则“直连”实际走了代理，结论全错。最可靠的是 `/dev/tcp` 的 bash 原生测试。
- **Node spawnSync stdin EBUSY**（特定沙箱内）：宿主 Job Object 限制，
  用户本机终端正常。绕过：preload 补丁把 spawnSync stdio 改 ignore。
- **PowerShell 读注册表被沙箱拦截**：退路用 Bash + `/dev/tcp`，或让用户自己跑。

## 临时实例测试技巧

验证“换 IP 复活”又不碰用户配置：起独立实例（独立目录/端口/API），

```bash
verge-mihomo.exe -d ./test -f test.yaml &   # mixed-port: 7899, controller: 127.0.0.1:9098
curl -x http://127.0.0.1:7899 https://www.google.com/generate_204
curl -x http://127.0.0.1:7899 "http://ip-api.com/json/?fields=country,city,isp,query"
```

注意：后台启动的实例随 Bash 会话结束被回收——**在同一轮命令里完成全部测试**，
分两轮跑第二轮会失败（端口已释放），不是节点问题。
