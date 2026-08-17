param(
    [Parameter(Position = 0)]
    [string]$Url = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

$LocalPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (Test-Path -LiteralPath $LocalPython) {
    $Python = $LocalPython
} else {
    $Python = (Get-Command python -ErrorAction Stop).Source
}

$Arguments = @("scripts\one_click_youtube.py")
if ($Url.Trim()) {
    $Arguments += $Url.Trim()
}

& $Python @Arguments
exit $LASTEXITCODE
