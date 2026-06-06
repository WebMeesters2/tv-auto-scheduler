param(
    [string]$SourceRoot = "P:\Projects\HA\tv-auto-scheduler",
    [string]$HaConfigRoot = "J:\",
    [switch]$RestartHA,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$IntegrationName = "tv_auto_scheduler"

$SourceIntegration = Join-Path $SourceRoot "custom_components\$IntegrationName"
$TargetIntegration = Join-Path $HaConfigRoot "custom_components\$IntegrationName"

$SourceExamples = Join-Path $SourceRoot "examples"
$TargetRulesDir = Join-Path $HaConfigRoot "tv_auto_scheduler"

Write-Host "Deploying $IntegrationName..." -ForegroundColor Cyan
Write-Host "Source: $SourceRoot"
Write-Host "Target HA config: $HaConfigRoot"
Write-Host ""

if (-not (Test-Path $SourceIntegration)) {
    throw "Source integration folder not found: $SourceIntegration"
}

if (-not (Test-Path $HaConfigRoot)) {
    throw "HA config root not found: $HaConfigRoot"
}

function Copy-Folder {
    param(
        [string]$Source,
        [string]$Target
    )

    if (-not (Test-Path $Source)) {
        Write-Host "Skipping missing source: $Source" -ForegroundColor Yellow
        return
    }

    Write-Host "Copying:"
    Write-Host "  From: $Source"
    Write-Host "  To:   $Target"

    if ($DryRun) {
        Write-Host "  DRY-RUN: copy skipped" -ForegroundColor Yellow
        return
    }

    New-Item -ItemType Directory -Force -Path $Target | Out-Null

    robocopy $Source $Target /MIR /XD __pycache__ .pytest_cache /XF *.pyc | Out-Null

    if ($LASTEXITCODE -gt 7) {
        throw "Robocopy failed with exit code $LASTEXITCODE"
    }
}

Copy-Folder -Source $SourceIntegration -Target $TargetIntegration

# Copy example rules only if no rules file exists yet.
$ExampleRules = Join-Path $SourceExamples "tv-rules.csv"
$TargetRules = Join-Path $TargetRulesDir "rules.csv"

if (Test-Path $ExampleRules) {
    if (-not (Test-Path $TargetRules)) {
        Write-Host ""
        Write-Host "Installing initial rules file:"
        Write-Host "  From: $ExampleRules"
        Write-Host "  To:   $TargetRules"

        if (-not $DryRun) {
            New-Item -ItemType Directory -Force -Path $TargetRulesDir | Out-Null
            Copy-Item $ExampleRules $TargetRules
        }
    }
    else {
        Write-Host ""
        Write-Host "Rules file already exists, leaving it untouched:" -ForegroundColor Green
        Write-Host "  $TargetRules"
    }
}

Write-Host ""
Write-Host "Deploy complete." -ForegroundColor Green
Write-Host "Restart Home Assistant or reload custom integrations if applicable."

if ($RestartHA) {
    Write-Host "Restarting Home Assistant..."

    Invoke-RestMethod `
        -Method Post `
        -Uri "https://jeeves:8123/api/services/homeassistant/restart" `
        -Headers @{
            Authorization = "Bearer $Token"
        }
}