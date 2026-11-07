<#
停止 start.ps1 / run.py 启动的本地进程。
用法（仓库根）：.\stop.ps1

按 .run\*.pid 停止（taskkill /T 整树，避免 cmd.exe 下的 node 子进程变孤儿）；
兜底清理任何 backend.app / 本项目 vite 残留与 5000/5001/4173/4174 监听——
pid 文件会过期，残留旧进程会占端口/用旧代码服务（"Unsupported database
schema" 的老病根）。
#>
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$runDir = Join-Path $root ".run"

# 1) 兜底：清 backend.app 与本项目 vite 残留（含孤儿 node 子进程）
Get-CimInstance Win32_Process | Where-Object {
  $_.CommandLine -and (
    $_.CommandLine -like '*backend.app*' -or
    $_.CommandLine -like "*$root\frontend\node_modules*"
  )
} | ForEach-Object {
  taskkill /T /F /PID $_.ProcessId 2>$null | Out-Null
  Write-Host "[stop] 清理残留进程 pid=$($_.ProcessId)"
}

# 2) 释放相关端口上的监听（5000/5001 后端、4173/4174 前端）
foreach ($port in 5000, 5001, 4173, 4174) {
  $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) {
    taskkill /T /F /PID $conn.OwningProcess 2>$null | Out-Null
    Write-Host "[stop] 释放端口 $port (pid=$($conn.OwningProcess))"
  }
}

# 3) pid 文件清账
foreach ($name in @("api", "frontend")) {
  $pidFile = Join-Path $runDir "$name.pid"
  if (Test-Path $pidFile) {
    $procId = Get-Content $pidFile | Select-Object -First 1
    if ($procId) {
      taskkill /T /F /PID ([int]$procId) 2>$null | Out-Null
      Write-Host "[stop] $name (pid=$procId) 已停止"
    }
    Remove-Item $pidFile -Force
  } else {
    Write-Host "[stop] $name 未在运行（无 pid 文件）"
  }
}
