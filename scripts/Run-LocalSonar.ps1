# ============================================================
# Run-LocalSonar.ps1 (Backend)
# ------------------------------------------------------------
# Ejecuta el flujo completo de análisis local para SonarQube
# Community (Docker en localhost:9000) usando la Quality Gate
# "Entangle" definida en el proyecto.
#
# Pasos que ejecuta:
#   1. Comprueba que SonarQube local está corriendo (lo arranca si no).
#   2. Ejecuta `pytest --cov=src --cov-report=xml:coverage.xml`.
#   3. Lanza sonar-scanner via Docker, leyendo sonar-project.properties
#      y publicando contra http://localhost:9000.
#   4. Espera a que SonarQube procese y muestra el estado de la QG.
#
# Uso:
#   $env:SONAR_LOCAL_TOKEN = "squ_xxxxxxxxxxxxxxxx"
#   ./scripts/Run-LocalSonar.ps1
#
#   # O con --skip-tests si solo quieres re-escanear:
#   ./scripts/Run-LocalSonar.ps1 -SkipTests
# ============================================================

[CmdletBinding()]
param(
    [string]$SonarUrl = "http://localhost:9000",
    [string]$Token    = $env:SONAR_LOCAL_TOKEN,
    [switch]$SkipTests,
    [string]$ContainerName = "sonarqube",
    [int]$WaitTimeoutSec = 180
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot

if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Host "ERROR: define `$env:SONAR_LOCAL_TOKEN antes de ejecutar." -ForegroundColor Red
    Write-Host "Generalo en http://localhost:9000 -> Avatar -> My Account -> Security." -ForegroundColor Yellow
    exit 1
}

Push-Location $repoRoot
try {
    # --- 1. Asegurar que SonarQube está UP ----------------------
    Write-Host "`n[1/4] Comprobando SonarQube en $SonarUrl..." -ForegroundColor Cyan
    $sqStatus = $null
    try {
        $sqStatus = (Invoke-RestMethod -Uri "$SonarUrl/api/system/status" -TimeoutSec 3).status
    } catch {
        Write-Host "  No responde, intentando arrancar contenedor '$ContainerName'..." -ForegroundColor Yellow
        docker start $ContainerName | Out-Null
    }
    $deadline = (Get-Date).AddSeconds($WaitTimeoutSec)
    while ($sqStatus -ne "UP") {
        if ((Get-Date) -gt $deadline) { throw "Timeout esperando a SonarQube en $SonarUrl" }
        Start-Sleep -Seconds 3
        try {
            $sqStatus = (Invoke-RestMethod -Uri "$SonarUrl/api/system/status" -TimeoutSec 3).status
            Write-Host "  estado: $sqStatus" -ForegroundColor DarkGray
        } catch {
            Write-Host "  conectando..." -ForegroundColor DarkGray
        }
    }
    Write-Host "  SonarQube UP" -ForegroundColor Green

    # --- 2. Tests + cobertura -----------------------------------
    if (-not $SkipTests) {
        Write-Host "`n[2/4] Ejecutando pytest con cobertura..." -ForegroundColor Cyan
        # Excluimos:
        #   - tests/integration: necesitan servicios externos
        #   - tests/test_api.py: incluye un test que lanza el pipeline completo
        #     real y queda colgado esperando MongoDB
        & python -m pytest `
            --cov=src `
            --cov-report=xml:coverage.xml `
            --cov-report=term-missing `
            --tb=no `
            --timeout=30 --timeout-method=thread `
            --ignore=tests/integration `
            --ignore=tests/test_api.py `
            -q
        if ($LASTEXITCODE -ne 0) {
            Write-Host "  AVISO: pytest reporto fallos (no bloqueantes para Sonar). Continuamos." -ForegroundColor Yellow
        } else {
            Write-Host "  Tests OK + coverage.xml generado" -ForegroundColor Green
        }
    } else {
        Write-Host "`n[2/4] Tests omitidos (-SkipTests)" -ForegroundColor DarkYellow
    }

    # --- 3. SonarScanner via Docker -----------------------------
    Write-Host "`n[3/4] Ejecutando sonar-scanner (Docker)..." -ForegroundColor Cyan

    # En Windows, contenedor accede al host por host.docker.internal
    $hostUrl = $SonarUrl -replace "localhost", "host.docker.internal" `
                        -replace "127\.0\.0\.1", "host.docker.internal"

    $containerWorkdir = "/usr/src"
    docker run --rm `
        -e SONAR_HOST_URL="$hostUrl" `
        -e SONAR_TOKEN="$Token" `
        -e SONAR_SCANNER_OPTS="-Dsonar.scm.disabled=true" `
        -v "$($repoRoot):$containerWorkdir" `
        sonarsource/sonar-scanner-cli:latest `
        "-Dproject.settings=sonar-project.local.properties"

    if ($LASTEXITCODE -ne 0) { throw "sonar-scanner fallo (exit $LASTEXITCODE)" }
    Write-Host "  Scan enviado correctamente" -ForegroundColor Green

    # --- 4. Esperar a que se procese y mostrar el QG ------------
    Write-Host "`n[4/4] Esperando procesamiento del analisis..." -ForegroundColor Cyan
    $pair = "$($Token):"
    $basic = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($pair))
    $h = @{ Authorization = "Basic $basic" }

    # Lee la projectKey del sonar-project.local.properties
    $propsPath = Join-Path $repoRoot "sonar-project.local.properties"
    if (-not (Test-Path $propsPath)) { throw "No se encontro sonar-project.local.properties" }
    $projectKey = (Select-String -Path $propsPath -Pattern '^sonar\.projectKey=' | Select-Object -First 1).Line.Split('=')[1].Trim()

    Start-Sleep -Seconds 5  # dar tiempo a SonarQube a procesar
    $qg = Invoke-RestMethod -Uri "$SonarUrl/api/qualitygates/project_status?projectKey=$projectKey" -Headers $h

    Write-Host ""
    Write-Host "================================================" -ForegroundColor Cyan
    Write-Host (" Quality Gate Status: {0}" -f $qg.projectStatus.status) -ForegroundColor $(if ($qg.projectStatus.status -eq "OK") { "Green" } else { "Red" })
    Write-Host "================================================" -ForegroundColor Cyan
    foreach ($c in $qg.projectStatus.conditions) {
        $color = if ($c.status -eq "OK") { "Green" } else { "Red" }
        Write-Host (" {0,-3} {1,-35} actual={2,-10} threshold={3} {4}" -f $c.status, $c.metricKey, $c.actualValue, $c.comparator, $c.errorThreshold) -ForegroundColor $color
    }
    Write-Host ""
    Write-Host " Dashboard: $SonarUrl/dashboard?id=$projectKey" -ForegroundColor Blue
    Write-Host ""
}
finally {
    Pop-Location
}
