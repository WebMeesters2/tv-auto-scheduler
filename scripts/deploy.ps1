param(
    [string]$SourceRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$HaConfigRoot = "J:\",
    [switch]$RestartHA,
    [switch]$DryRun,
    [string]$HaUrl = "https://jeeves:8123",
    [string]$Token = $env:HA_TOKEN
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
        [Parameter(Mandatory = $true)]
        [string]$Source,

        [Parameter(Mandatory = $true)]
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

if ($RestartHA) {
    if ([string]::IsNullOrWhiteSpace($Token)) {
        throw "RestartHA requested, but no token was supplied. Use -Token or set HA_TOKEN."
    }

    if ($DryRun) {
        Write-Host "DRY-RUN: Home Assistant restart skipped" -ForegroundColor Yellow
    }
    else {
        Write-Host "Restarting Home Assistant..." -ForegroundColor Cyan

        Invoke-RestMethod `
            -Method Post `
            -Uri "$HaUrl/api/services/homeassistant/restart" `
            -Headers @{
                Authorization = "Bearer $Token"
            }
    }
}
else {
    Write-Host "Restart Home Assistant or reload custom integrations if applicable."
}