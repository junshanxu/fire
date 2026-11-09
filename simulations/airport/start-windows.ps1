param([switch]$Build)
$ErrorActionPreference = "Stop"
$dockerCandidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)
$dockerExe = $dockerCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $dockerExe) { $dockerExe = (Get-Command docker.exe -ErrorAction Stop).Source }
# Docker invokes its credential helper by name when pulling public images.
$env:PATH = (Split-Path -Parent $dockerExe) + [IO.Path]::PathSeparator + $env:PATH
& $dockerExe info --format '{{.ServerVersion}}'
if ($LASTEXITCODE -ne 0) { throw "Start Docker Desktop and wait for its engine, then run this script again." }
Push-Location $PSScriptRoot
try {
    if ($Build) {
        & $dockerExe compose -p rmf-airport -f compose.yml build
        if ($LASTEXITCODE -ne 0) { throw "Image build failed." }
    }
    & $dockerExe compose -p rmf-airport -f compose.yml up -d
    if ($LASTEXITCODE -ne 0) { throw "Container startup failed." }
    Write-Host "Website: http://localhost:8092"
    Write-Host "Waiting for the simulator (up to 90 seconds)..."
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            $status = Invoke-RestMethod "http://localhost:8092/api/status" -TimeoutSec 3
            if ($status.ready) { break }
        } catch { }
        Start-Sleep -Seconds 3
    }
    Start-Process "http://localhost:8092"
} finally {
    Pop-Location
}
