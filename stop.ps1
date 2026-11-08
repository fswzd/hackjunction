# Stop the services registered by this checkout's run.py.
$runDir = Join-Path $PSScriptRoot ".run"
$frontendEntry = Join-Path $PSScriptRoot "frontend\node_modules\vite\bin\vite.js"
$commands = @{
  api = "-m backend.app"
  worker = "-m backend.manage worker"
  frontend = $frontendEntry
}
$failed = $false

foreach ($name in @("frontend", "worker", "api")) {
  $pidPath = Join-Path $runDir "$name.pid"
  if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) { continue }
  $record = Get-Item -LiteralPath $pidPath
  $processId = 0
  $savedPid = (Get-Content -LiteralPath $pidPath -Raw).Trim()
  if ([int]::TryParse($savedPid, [ref]$processId) -and $processId -gt 0) {
    try {
      $process = Get-CimInstance Win32_Process -Filter "ProcessId=$processId" -ErrorAction Stop
    } catch {
      Write-Warning "Could not verify $name (PID $processId)."
      $failed = $true
      continue
    }
    if ($process) {
      $ageAtRegistration = ($record.LastWriteTimeUtc - $process.CreationDate.ToUniversalTime()).TotalSeconds
      if (-not $process.CommandLine -or
          $process.CommandLine.IndexOf($commands[$name], [StringComparison]::OrdinalIgnoreCase) -lt 0 -or
          $ageAtRegistration -lt 0 -or $ageAtRegistration -gt 120) {
        Write-Warning "Ignored stale PID for $name (PID $processId)."
      } else {
        taskkill /T /F /PID $processId 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0 -and (Get-Process -Id $processId -ErrorAction SilentlyContinue)) {
          Write-Warning "Could not stop $name (PID $processId)."
          $failed = $true
          continue
        }
        Write-Host "[stop] $name stopped (PID $processId)."
      }
    }
  }
  Remove-Item -LiteralPath $pidPath
}
if ($failed) { exit 1 }
