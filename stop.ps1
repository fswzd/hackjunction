<#
停止 start.ps1 启动的本地进程（按 .run\*.pid）。
用法（仓库根）：.\stop.ps1
#>
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
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
