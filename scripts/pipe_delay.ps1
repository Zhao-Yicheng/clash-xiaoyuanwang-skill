param([int]$Timeout = 3000)
$ErrorActionPreference = "Stop"
$pipeName = "verge-mihomo-sidecar-release-3033d8c4fd917c07397830f1514197af8acd890f0670391217792b768d169dbc"

function Invoke-PipeApi {
    param([string]$Path)
    $pipe = New-Object System.IO.Pipes.NamedPipeClientStream(".", $pipeName, [System.IO.Pipes.PipeDirection]::InOut)
    $pipe.Connect(5000)
    $ms = New-Object System.IO.MemoryStream
    $buf = New-Object byte[] 65536
    $req = "GET $Path HTTP/1.0`r`nHost: localhost`r`nAuthorization: Bearer set-your-secret`r`n`r`n"
    $reqBytes = [System.Text.Encoding]::ASCII.GetBytes($req)
    $pipe.Write($reqBytes, 0, $reqBytes.Length)
    $pipe.Flush()
    do {
        $read = $pipe.Read($buf, 0, $buf.Length)
        if ($read -gt 0) { $ms.Write($buf, 0, $read) }
    } while ($read -gt 0)
    $pipe.Dispose()
    $text = [System.Text.Encoding]::UTF8.GetString($ms.ToArray())
    $idx = $text.IndexOf("`r`n`r`n")
    if ($idx -ge 0) { return $text.Substring($idx + 4) } else { return $text }
}

$proxiesJson = Invoke-PipeApi "/proxies"
$j = $proxiesJson | ConvertFrom-Json
$names = @()
foreach ($p in $j.proxies.PSObject.Properties) {
    if ($p.Value.type -in @("Vless","Hysteria2","Shadowsocks","Trojan","Vmess")) {
        $names += $p.Name
    }
}
Write-Output "共 $($names.Count) 个实体节点，开始逐个延迟测试（超时 ${Timeout}ms）..."
$results = @()
foreach ($name in $names) {
    $enc = [uri]::EscapeDataString($name)
    try {
        $d = Invoke-PipeApi "/proxies/$enc/delay?url=http%3A%2F%2Fwww.gstatic.com%2Fgenerate_204&timeout=$Timeout"
        $dj = $d | ConvertFrom-Json
        if ($dj.delay -gt 0) {
            $results += [pscustomobject]@{ Name = $name; Delay = $dj.delay }
            Write-Output "  OK  $($dj.delay)ms  $name"
        } else {
            Write-Output "  --  超时  $name"
        }
    } catch {
        Write-Output "  ERR 测试失败: $name"
    }
}
Write-Output ""
Write-Output "===== 汇总 ====="
Write-Output "可用: $($results.Count) / $($names.Count)"
$results | Sort-Object Delay | ForEach-Object { "{0,6} ms  {1}" -f $_.Delay, $_.Name }
