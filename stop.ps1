<#
停止 start.ps1 启动的本地进程（按 .run\*.pid）。
用法（仓库根）：.\stop.ps1
#>
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
# 兜底：清掉任何 backend.app 进程与 5000/5001 监听（pid 文件可能过期，
# 残留旧进程会占端口/用旧代码服务，正是"Unsupported database schema"的来源）
Get-CimInstance Win32_Process -Filter "Name='python.exe'" | Where-Object {
  $_.CommandLine -like '*backend.app*'
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
  Write-Host "[stop] 清理残留 api 进程 (pid=$($_.ProcessId))" }
foreach ($port in 5000, 5001) {
  $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
  if ($conn) { Stop-Process -Id $conn.OwningProcess -Force -ErrorAction SilentlyContinue
    Write-Host "[stop] 释放端口 $port (pid=$($conn.OwningProcess))" }
}
$runDir = Join-Path $root ".run"
foreach ($name in @("api", "frontend")) {
  $pidFile = Join-Path $runDir "$name.pid"
  if (Test-Path $pidFile) {
    $procId = Get-Content $pidFile | Select-Object -First 1
    if ($procId) {
      try {
        Stop-Process -Id ([int]$procId) -Force -ErrorAction Stop
        Write-Host "[stop] $name (pid=$procId) 已停止"
      } catch {
        Write-Host "[stop] $name (pid=$procId) 不存在或已退出"
      }
    }
    Remove-Item $pidFile -Force
  } else {
    Write-Host "[stop] $name 未在运行（无 pid 文件）"
  }
}
