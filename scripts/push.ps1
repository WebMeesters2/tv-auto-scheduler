param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [string]$Branch = "main",

    [switch]$Force
)

$ErrorActionPreference = "Stop"

Push-Location (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

try {
    Write-Host "Checking Git status..." -ForegroundColor Cyan
    git status --short

    $HasChanges = git status --porcelain

    if (-not $HasChanges) {
        Write-Host ""
        Write-Host "No changes to commit." -ForegroundColor Yellow
        return
    }

    Write-Host ""
    Write-Host "Adding changes..." -ForegroundColor Cyan
    git add .

    Write-Host ""
    Write-Host "Committing..." -ForegroundColor Cyan
    git commit -m $Message

    Write-Host ""
    Write-Host "Pushing to origin $Branch..." -ForegroundColor Cyan

    if ($Force) {
        git push -u origin $Branch --force-with-lease
    }
    else {
        git push -u origin $Branch
    }

    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
}
finally {
    Pop-Location
}