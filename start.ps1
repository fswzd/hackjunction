param(
  [switch]$SkipApi,
  [switch]$SkipFrontend,
  [switch]$SkipWorker,
  [string]$DataDir = ""
)
$ErrorActionPreference = "Stop"
$launcher = Join-Path $PSScriptRoot "run.py"
$runArguments = @("--detach")
if ($SkipApi) { $runArguments += "--skip-api" }
if ($SkipFrontend) { $runArguments += "--skip-frontend" }
if ($SkipWorker) { $runArguments += "--skip-worker" }
if ($DataDir) { $runArguments += @("--data-dir", $DataDir) }
& python $launcher @runArguments
exit $LASTEXITCODE
