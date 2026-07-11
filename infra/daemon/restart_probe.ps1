# Agent-Orchestra 探针一键重启脚本（Windows PowerShell）
#
# 行为：
#   1. 从仓库根的 .env 读取 HUB_HOST/HUB_PORT
#   2. health check：Invoke-WebRequest GET /api/messages?limit=1
#   3. Stop旧 cc_bridge.py 进程（Get-CimInstance Win32_Process 按 CommandLine 匹配）
#   4. Start-Process 后台启动新 cc_bridge.py，日志落 cc_bridge.out / .err
#   5. 等 1s 后检查进程是否仍在
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File daemon/restart_probe.ps1
#   powershell -ExecutionPolicy Bypass -File daemon/restart_probe.ps1 -RepoRoot C:\path\to\repo
[CmdletBinding()]
param(
    [string]$RepoRoot
)

$ErrorActionPreference = 'Stop'

if (-not $RepoRoot) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}
$RepoRoot = (Resolve-Path $RepoRoot).Path
$Bridge = Join-Path $RepoRoot 'cc_bridge.py'
$OutLog = Join-Path $RepoRoot 'cc_bridge.out'
$ErrLog = Join-Path $RepoRoot 'cc_bridge.err'

# 加载 .env（如存在）
$envFile = Join-Path $RepoRoot '.env'
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith('#') -and $line -match '^(?<k>[^=]+)=(?<v>.*)$') {
            Set-Item -Path \"Env:$($Matches.k)\" -Value $Matches.v
        }
    }
}

$HubHost = if ($env:HUB_HOST) { $env:HUB_HOST } else { '124.222.79.205' }
$HubPort = if ($env:HUB_PORT) { $env:HUB_PORT } else { '8765' }
$HealthUrl = \"http://${HubHost}:${HubPort}/api/messages?limit=1\"

Write-Host \"[restart_probe] health check: $HealthUrl\"
try {
    $null = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5
    Write-Host '[restart_probe] Hub OK'
} catch {
    Write-Host \"[restart_probe] ERROR: Hub 不健康 ($HealthUrl)，放弃重启\" -ForegroundColor Red
    exit 1
}

Write-Host '[restart_probe] killing old probe (if any)'
Get-CimInstance Win32_Process -Filter \"Name = 'python.exe'\" |
    Where-Object { $_.CommandLine -like \"*cc_bridge.py*\" } |
    ForEach-Object {
        Write-Host \"[restart_probe] killing pid=$($_.ProcessId)\"
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
    }
Start-Sleep -Seconds 1

Write-Host '[restart_probe] starting new probe in background'
$proc = Start-Process -FilePath 'python' -ArgumentList \"`\"$Bridge`\"\" `
    -RedirectStandardOutput $OutLog `
    -RedirectStandardError $ErrLog `
    -WorkingDirectory $RepoRoot `
    -WindowStyle Hidden `
    -PassThru
Start-Sleep -Seconds 1

if (-not $proc.HasExited) {
    Write-Host \"[restart_probe] probe up, pid=$($proc.Id), logs: $OutLog / $ErrLog\"
    exit 0
} else {
    Write-Host \"[restart_probe] ERROR: probe 进程已退出 (ExitCode=$($proc.ExitCode))，查看 $ErrLog\" -ForegroundColor Red
    if (Test-Path $ErrLog) { Get-Content $ErrLog -Tail 20 }
    exit 1
}