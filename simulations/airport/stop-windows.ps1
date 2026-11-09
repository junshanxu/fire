$ErrorActionPreference = "Stop"
$candidates = @(
    (Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\resources\bin\docker.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe")
)
$dockerExe = $candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $dockerExe) { $dockerExe = (Get-Command docker.exe -ErrorAction Stop).Source }
& $dockerExe compose -p rmf-airport -f (Join-Path $PSScriptRoot "compose.yml") stop
if ($LASTEXITCODE -ne 0) { throw "Could not stop the demo." }
