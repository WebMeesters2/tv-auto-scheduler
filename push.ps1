param(
    [Parameter(Mandatory = $true)]
    [string]$Message,

    [switch]$Force
)

$ErrorActionPreference = "Stop"

# Configuration
$GitExe = "C:\Program Files\Git\bin\git.exe"

Write-Host "Checking Git status..." -ForegroundColor Cyan
& $GitExe status --short

Write-Host ""
Write-Host "Adding changes..." -ForegroundColor Cyan
& $GitExe add .

Write-Host ""
Write-Host "Committing..." -ForegroundColor Cyan
& $GitExe commit -m $Message

Write-Host ""
Write-Host "Pushing to origin main..." -ForegroundColor Cyan

if ($Force) {
    & $GitExe push -u origin main --force-with-lease
}
else {
    & $GitExe push -u origin main
}

Write-Host ""
Write-Host "Done." -ForegroundColor Green