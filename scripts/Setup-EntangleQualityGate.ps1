# ============================================================
# Setup-EntangleQualityGate.ps1
# ------------------------------------------------------------
# Crea la Quality Gate "Entangle" en SonarCloud con las 9
# condiciones definidas en la memoria del TFG y la asigna a
# los dos proyectos del repo (Entangle-Core y Entangle-Visualizer).
#
# Uso:
#   $env:SONAR_TOKEN = "squ_xxxxxxxxxxxxxxxxxxxxxxxx"
#   ./Setup-EntangleQualityGate.ps1
#
# Es idempotente: se puede ejecutar varias veces sin romper nada.
# Si la Quality Gate ya existe, actualiza sus condiciones.
# ============================================================

[CmdletBinding()]
param(
    [string]$SonarUrl       = "https://sonarcloud.io",
    [string]$Organization   = "angel-tfg-uclm",
    [string]$QualityGateName = "Entangle",
    [string[]]$ProjectKeys  = @(
        "Angel-TFG-UCLM_Entangle-Core",
        "Angel-TFG-UCLM_Entangle-Visualizer"
    ),
    [string]$Token = $env:SONAR_TOKEN
)

if ([string]::IsNullOrWhiteSpace($Token)) {
    Write-Host "ERROR: define `$env:SONAR_TOKEN antes de ejecutar el script." -ForegroundColor Red
    Write-Host "Ej: `$env:SONAR_TOKEN = 'squ_xxxxxxxxxxxx'" -ForegroundColor Yellow
    exit 1
}

# ----- Helpers ------------------------------------------------
$pair = "$($Token):"
$basic = [Convert]::ToBase64String([System.Text.Encoding]::ASCII.GetBytes($pair))
$Headers = @{ Authorization = "Basic $basic" }

function Invoke-Sonar {
    param(
        [Parameter(Mandatory)][ValidateSet('GET','POST')] [string]$Method,
        [Parameter(Mandatory)][string]$Path,
        [hashtable]$Body
    )
    $uri = "$SonarUrl$Path"
    try {
        if ($Method -eq 'GET') {
            return Invoke-RestMethod -Method Get -Uri $uri -Headers $Headers -ErrorAction Stop
        } else {
            return Invoke-RestMethod -Method Post -Uri $uri -Headers $Headers -Body $Body -ErrorAction Stop
        }
    } catch {
        $resp = $_.Exception.Response
        $status = if ($resp) { [int]$resp.StatusCode } else { 0 }
        $msg = if ($_.ErrorDetails) { $_.ErrorDetails.Message } else { $_.Exception.Message }
        Write-Host ("Sonar API error [{0}] on {1} {2}: {3}" -f $status, $Method, $Path, $msg) -ForegroundColor Red
        throw
    }
}

# ----- Definicion de las 9 condiciones de la Quality Gate ----
# Op LT  = Less Than    (la metrica debe ser < error)
# Op GT  = Greater Than (la metrica debe ser > error)
# Sonar evalua "fallo si CONDICION SE CUMPLE", asi que para
# umbrales tipo "Coverage >= 60" usamos LT con error=60.
$conditions = @(
    # Reliability Rating <= C  (1=A, 2=B, 3=C, 4=D, 5=E)
    @{ metric = 'reliability_rating';                    op = 'GT'; error = '3' }
    # Security Rating <= A
    @{ metric = 'security_rating';                       op = 'GT'; error = '1' }
    # Maintainability Rating (sqale_rating) <= B
    @{ metric = 'sqale_rating';                          op = 'GT'; error = '2' }
    # Coverage >= 60 %
    @{ metric = 'coverage';                              op = 'LT'; error = '60' }
    # Duplicated Lines Density <= 5 %
    @{ metric = 'duplicated_lines_density';              op = 'GT'; error = '5' }
    # Duplicated Lines Density on New Code <= 3 %
    @{ metric = 'new_duplicated_lines_density';          op = 'GT'; error = '3' }
    # New Issues <= 0
    @{ metric = 'new_violations';                        op = 'GT'; error = '0' }
    # Security Hotspots Reviewed >= 80 %
    @{ metric = 'security_hotspots_reviewed';            op = 'LT'; error = '80' }
    # Vulnerabilities <= 0
    @{ metric = 'vulnerabilities';                       op = 'GT'; error = '0' }
)

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Setup Quality Gate '$QualityGateName' en $SonarUrl" -ForegroundColor Cyan
Write-Host " Organizacion: $Organization" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan

# ----- 1. Crear o reutilizar la Quality Gate -----------------
Write-Host "`n[1/4] Creando/recuperando Quality Gate '$QualityGateName'..." -ForegroundColor Yellow

$qgList = Invoke-Sonar -Method GET -Path "/api/qualitygates/list?organization=$Organization"
$existing = $qgList.qualitygates | Where-Object { $_.name -eq $QualityGateName }

if ($existing) {
    $gateId = "$($existing.id)"
    Write-Host "   - Ya existia (id=$gateId). Se actualizaran sus condiciones." -ForegroundColor DarkYellow
} else {
    $created = Invoke-Sonar -Method POST -Path "/api/qualitygates/create" -Body @{
        organization = $Organization
        name         = $QualityGateName
    }
    $gateId = "$($created.id)"
    Write-Host "   - Creada (id=$gateId)" -ForegroundColor Green
}

# ----- 2. Sincronizar condiciones (idempotente) --------------
Write-Host "`n[2/4] Sincronizando 9 condiciones..." -ForegroundColor Yellow

$current = Invoke-Sonar -Method GET -Path "/api/qualitygates/show?organization=$Organization&id=$gateId"

# Borrar condiciones que no estan en el set deseado
if ($current.conditions) {
    foreach ($c in $current.conditions) {
        $stillWanted = $conditions | Where-Object {
            $_.metric -eq $c.metric -and $_.op -eq $c.op -and "$($_.error)" -eq "$($c.error)"
        }
        if (-not $stillWanted) {
            try {
                Invoke-Sonar -Method POST -Path "/api/qualitygates/delete_condition" -Body @{
                    organization = $Organization
                    id           = $c.id
                } | Out-Null
                Write-Host "   - Eliminada condicion obsoleta: $($c.metric) $($c.op) $($c.error)" -ForegroundColor DarkGray
            } catch {
                Write-Host "   - No se pudo borrar condicion id=$($c.id): $($_.Exception.Message)" -ForegroundColor DarkRed
            }
        }
    }
}

# Crear las que faltan
$currentSet = @{}
if ($current.conditions) {
    foreach ($c in $current.conditions) {
        $currentSet["$($c.metric)|$($c.op)|$($c.error)"] = $true
    }
}

foreach ($cond in $conditions) {
    $key = "$($cond.metric)|$($cond.op)|$($cond.error)"
    if ($currentSet.ContainsKey($key)) {
        Write-Host ("   = OK : {0,-35} {1,-2} {2}" -f $cond.metric, $cond.op, $cond.error) -ForegroundColor DarkGray
        continue
    }
    try {
        Invoke-Sonar -Method POST -Path "/api/qualitygates/create_condition" -Body @{
            organization = $Organization
            gateId       = $gateId
            metric       = $cond.metric
            op           = $cond.op
            error        = $cond.error
        } | Out-Null
        Write-Host ("   + ADD: {0,-35} {1,-2} {2}" -f $cond.metric, $cond.op, $cond.error) -ForegroundColor Green
    } catch {
        Write-Host ("   ! ERR: {0} -> {1}" -f $cond.metric, $_.Exception.Message) -ForegroundColor Red
    }
}

# ----- 3. Asignar la Quality Gate a cada proyecto ------------
Write-Host "`n[3/4] Asignando QG '$QualityGateName' a los proyectos..." -ForegroundColor Yellow

foreach ($pk in $ProjectKeys) {
    try {
        Invoke-Sonar -Method POST -Path "/api/qualitygates/select" -Body @{
            organization = $Organization
            projectKey   = $pk
            gateId       = $gateId
        } | Out-Null
        Write-Host "   * $pk -> $QualityGateName" -ForegroundColor Green
    } catch {
        Write-Host "   ! No se pudo asignar a $pk : $($_.Exception.Message)" -ForegroundColor Red
    }
}

# ----- 4. Resumen final --------------------------------------
Write-Host "`n[4/4] Verificacion final..." -ForegroundColor Yellow
$final = Invoke-Sonar -Method GET -Path "/api/qualitygates/show?organization=$Organization&id=$gateId"

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host " Quality Gate '$QualityGateName' configurada" -ForegroundColor Cyan
Write-Host "================================================" -ForegroundColor Cyan
Write-Host (" Total condiciones: {0}" -f $final.conditions.Count) -ForegroundColor Green
Write-Host ""
Write-Host " Dashboard:" -ForegroundColor White
Write-Host "   $SonarUrl/organizations/$Organization/quality_gates" -ForegroundColor Blue
Write-Host ""
Write-Host " Proyectos asignados:" -ForegroundColor White
foreach ($pk in $ProjectKeys) {
    Write-Host "   - $SonarUrl/project/overview?id=$pk" -ForegroundColor Blue
}
Write-Host ""
