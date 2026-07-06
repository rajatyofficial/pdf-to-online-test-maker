$ErrorActionPreference = "Stop"
$bundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if (Test-Path $bundledPython) {
    & $bundledPython "$PSScriptRoot\server.py"
} else {
    python "$PSScriptRoot\server.py"
}

