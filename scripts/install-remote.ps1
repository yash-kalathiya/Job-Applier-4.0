# Job Applier 4.0 installer for Windows
& {
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Repo = 'yash-kalathiya/Job-Applier-4.0'
$Dir = if ($env:JOB_APPLIER_DIR) { $env:JOB_APPLIER_DIR } else { Join-Path $env:USERPROFILE '.job-applier-app' }
function Ok($m) { Write-Host "  v $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  ! $m" -ForegroundColor Yellow }
function Die($m) { Write-Host "  x $m" -ForegroundColor Red; throw "Job Applier 4.0 install stopped: $m" }

Write-Host "Installing Job Applier 4.0" -ForegroundColor White

$Py = $null
foreach ($c in @(@('py', '-3'), @('python'), @('python3'))) {
  try {
    $exe = & $c[0] $c[1] -c "import sys; print(sys.executable if sys.version_info >= (3, 9) else '')"
    if ($exe -and (Test-Path $exe.Trim())) { $Py = $exe.Trim(); break }
  } catch {}
}
if (-not $Py) { Die "Job Applier 4.0 needs Python 3.9+." }
Ok "Python ($Py)"
if (Get-Command npx -ErrorAction SilentlyContinue) { Ok "Node.js $(node -v)" } else { Warn "Node.js not found." }

Ok "Job Applier 4.0 in $Dir"
Write-Host "`n* Star on GitHub: https://github.com/yash-kalathiya/Job-Applier-4.0" -ForegroundColor Yellow
}
