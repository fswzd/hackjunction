<#
一键启动：数据库迁移 → Flask API (127.0.0.1:5001) → 前端 Vite (127.0.0.1:4173)

用法（PowerShell，在仓库根执行）：
  .\start.ps1                  # 全量启动
  .\start.ps1 -SkipFrontend    # 只起后端 API
  .\start.ps1 -SkipApi         # 只起前端（默认走演示适配器，不依赖后端）
  .\start.ps1 -DataDir X:\data # 指定数据目录（默认 birthco-local\data）
停止：.\stop.ps1

已知边界（完整度评审 F-01）：队列→工作流的自动执行 worker 尚未接入，
API 创建的任务处于 QUEUED，业务推进当前由 CLI（birthco-local/tools）与
Mock 演示（run_mock_demo.py）驱动。
#>
param(
  [switch]$SkipApi,
  [switch]$SkipFrontend,
  [string]$DataDir = ""
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

# ---------- 1) 环境（只用进程环境变量；不读取任何 .env 文件） ----------
if ($DataDir) { $env:BIRTHCO_DATA_DIR = $DataDir }
if (-not $env:BIRTHCO_DATA_DIR) { $env:BIRTHCO_DATA_DIR = Join-Path $root "birthco-local\data" }
if (-not $env:BIRTHCO_PORT) { $env:BIRTHCO_PORT = "5001" }
Write-Host "[cfg] HOST=$($env:BIRTHCO_HOST) PORT=$($env:BIRTHCO_PORT) DATA=$($env:BIRTHCO_DATA_DIR) MODEL_MODE=$($env:BIRTHCO_MODEL_MODE)"

$runDir = Join-Path $root ".run"
New-Item -ItemType Directory -Force -Path $runDir | Out-Null

# ---------- 2) 数据库迁移 ----------
Push-Location (Join-Path $root "birthco-local")
Write-Host "[db ] migrate --data-dir $env:BIRTHCO_DATA_DIR"
python -m backend.manage migrate --data-dir "$env:BIRTHCO_DATA_DIR"
if ($LASTEXITCODE -ne 0) { Pop-Location; throw "database migrate failed" }
Pop-Location

# ---------- 3) Flask API ----------
if (-not $SkipApi) {
  $apiLog = Join-Path $runDir "api.log"
  $api = Start-Process -FilePath "python" -ArgumentList "-m", "backend.app" `
    -WorkingDirectory (Join-Path $root "birthco-local") `
    -RedirectStandardOutput $apiLog -RedirectStandardError (Join-Path $runDir "api.err.log") `
    -PassThru -WindowStyle Hidden
  $api.Id | Out-File (Join-Path $runDir "api.pid") -Encoding ascii
  Write-Host "[api] 启动中 pid=$($api.Id) → http://127.0.0.1:$($env:BIRTHCO_PORT)  日志 $apiLog"
}

# ---------- 4) 前端 ----------
if (-not $SkipFrontend) {
  $fe = Join-Path $root "frontend"
  if (-not (Test-Path (Join-Path $fe "node_modules"))) {
    Write-Host "[fe ] 首次启动：npm install（可能需要几分钟）"
    Push-Location $fe
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
    Pop-Location
  }
  $feLog = Join-Path $runDir "frontend.log"
  $feProc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c", "npm", "run", "dev" `
    -WorkingDirectory $fe `
    -RedirectStandardOutput $feLog -RedirectStandardError (Join-Path $runDir "frontend.err.log") `
    -PassThru -WindowStyle Hidden
  $feProc.Id | Out-File (Join-Path $runDir "frontend.pid") -Encoding ascii
  Write-Host "[fe ] 启动中 pid=$($feProc.Id) → http://127.0.0.1:4173  日志 $feLog"
}

Write-Host ""
Write-Host "=== 启动完成 ==="
Write-Host "前端工作台  http://127.0.0.1:4173   （默认演示适配器，无需后端也可体验）"
if (-not $SkipApi) { Write-Host "后端 API    http://127.0.0.1:$($env:BIRTHCO_PORT)" }
Write-Host "停止服务    .\stop.ps1"
Write-Host "已知边界：自动执行 worker 未接入（评审 F-01），业务推进用："
Write-Host "  python run_mock_demo.py                                    # 编排 Mock 全流程"
Write-Host "  cd birthco-local; python tools/run_operator.py --input examples/operator-task.json --output out.json"
