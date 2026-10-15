// Clash Verge 全局扩展脚本模板 —— CDN 入口 IP 优选（方案 A）
// 使用方法: 把本文件内容粘贴到 Clash Verge → 订阅页 → 全局扩展脚本(或右键订阅→编辑脚本)
// 然后:
//   1. 运行 scripts/clash_ip_scan.py 扫出现网可达候选池
//   2. 用扫描输出的 POOLS 片段替换下面的 POOLS
//   3. 任意订阅更新/重新激活后生效; url-test/fallback 会现场测活自动选优
//
// 原理: 部分家宽出口对 CDN 入口做 /32 单 IP 精确封锁(SYN 静默丢包),
// 但 CF Anycast 同段邻居 IP 提供完全相同的节点服务(TLS 握手拿机场证书、
// WS 101、全链路实测)。本脚本把命中被封域名的节点换到可达 IP,
// 并克隆副本进入自动测活组, 由内核周期性现场测活选优。
// 脚本本身只做配置期静态数据加工(沙箱里没有网络能力),
// 现场测活由 url-test 在运行时完成 —— 两者分工不重叠。

const POOLS = {
  // 示例: 实际使用前用 clash_ip_scan.py 的输出替换
  // "cfyes.example.com": ["<首选IP>", "<备1>", "<备2>", ...],
};

function main(config, profileName) {
  if (!Array.isArray(config.proxies)) return config;

  const isInfo = (n) =>
    n.includes("剩余流量") || n.includes("重置") || n.includes("到期") || n.includes("套餐");

  const cloneCount = 3; // 每节点克隆的备 IP 副本数
  const newProxies = [];
  const cloneNames = [];

  for (const p of config.proxies) {
    const pool = POOLS[p.server];
    if (!pool || p.type !== "vless") {
      newProxies.push(p);
      continue;
    }
    // 原节点: 换到首选可达 IP, 名字不变(原组照常引用)
    p.server = pool[0];
    newProxies.push(p);

    if (isInfo(p.name)) continue;

    for (let i = 1; i <= cloneCount && i < pool.length; i++) {
      const c = JSON.parse(JSON.stringify(p));
      c.name = p.name + "·IP" + i;
      c.server = pool[i];
      newProxies.push(c);
      cloneNames.push(c.name);
    }
  }

  // 副本只进自动测活组(url-test/fallback), 不进手动选择组, 避免 GUI 列表翻倍
  for (const g of config["proxy-groups"] || []) {
    if (g.type === "url-test" || g.type === "fallback") {
      g.proxies = (g.proxies || []).concat(cloneNames);
    }
  }

  config.proxies = newProxies;
  return config;
}
