$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$HostAddress = "10.118.173.222"
$PostgresWaitSeconds = 60
$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$CaBundle = Join-Path $ProjectRoot "certs\python-ca-bundle.pem"
$ComposeFiles = @("-f", "docker-compose.yml", "-f", "docker-compose.dev.yml")

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python virtual environment not found: $Python`nCreate it with: python -m venv .venv"
}

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw "Docker was not found in PATH. Start Docker Desktop and make sure the docker command is available."
}

$CertifiPath = & $Python -c "import certifi; print(certifi.where())"
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $CertifiPath)) {
    throw "Could not locate certifi CA bundle: $CertifiPath"
}

# Python/OpenSSL does not automatically use the Windows certificate store.
# Combine certifi's public roots with the T-Bank Russian Trusted Root CA.
$certifiBytes = [System.IO.File]::ReadAllBytes($CertifiPath)
$tbankCaPath = Join-Path $ProjectRoot "certs\russian-trusted-root-ca.crt"
if (-not (Test-Path -LiteralPath $tbankCaPath)) {
    throw "T-Bank CA certificate was not found: $tbankCaPath"
}

$tbankCaBytes = [System.IO.File]::ReadAllBytes($tbankCaPath)
$separator = [System.Text.Encoding]::ASCII.GetBytes("`r`n")
$bundleBytes = [byte[]]::new($certifiBytes.Length + $separator.Length + $tbankCaBytes.Length)
[System.Array]::Copy($certifiBytes, 0, $bundleBytes, 0, $certifiBytes.Length)
[System.Array]::Copy($separator, 0, $bundleBytes, $certifiBytes.Length, $separator.Length)
[System.Array]::Copy($tbankCaBytes, 0, $bundleBytes, $certifiBytes.Length + $separator.Length, $tbankCaBytes.Length)
[System.IO.File]::WriteAllBytes($CaBundle, $bundleBytes)

$env:SSL_CERT_FILE = $CaBundle
Write-Host "Using TLS CA bundle: $CaBundle"

docker compose @ComposeFiles --profile tools up -d postgres adminer
if ($LASTEXITCODE -ne 0) {
    throw "Could not start PostgreSQL and Adminer."
}

Write-Host "Waiting for PostgreSQL to become ready..."
$ready = $false

for ($second = 1; $second -le $PostgresWaitSeconds; $second++) {
    docker compose @ComposeFiles exec -T postgres sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"' *> $null
    if ($LASTEXITCODE -eq 0) {
        $ready = $true
        break
    }

    Start-Sleep -Seconds 1
}

if (-not $ready) {
    throw "PostgreSQL did not become ready within $PostgresWaitSeconds seconds."
}

Write-Host "PostgreSQL is ready."

& $Python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    throw "Database migrations failed."
}

$WorkerProcess = $null
try {
    Write-Host "Starting background worker in a separate window..."
    $WorkerProcess = Start-Process `
        -FilePath $Python `
        -ArgumentList @("-m", "app.worker") `
        -WorkingDirectory $ProjectRoot `
        -PassThru

    & $Python -m uvicorn app.main:app --reload --host $HostAddress --port 8000
    $ApiExitCode = $LASTEXITCODE
}
finally {
    if ($null -ne $WorkerProcess -and -not $WorkerProcess.HasExited) {
        Write-Host "Stopping background worker..."
        Stop-Process -Id $WorkerProcess.Id -Force
    }
}

exit $ApiExitCode
