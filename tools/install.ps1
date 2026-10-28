$ErrorActionPreference = 'Stop'
$studioRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $studioRoot
$studioBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$studioPython = $null
if (Test-Path -LiteralPath $studioBundledPython) {
    $studioPython = $studioBundledPython
} else {
    foreach ($studioCandidate in @('python', 'py')) {
        $studioCommand = Get-Command $studioCandidate -ErrorAction SilentlyContinue
        if ($studioCommand) {
            try {
                & $studioCommand.Source -c 'import sys; assert (3, 10) <= sys.version_info[:2] < (3, 15)'
                if ($LASTEXITCODE -eq 0) { $studioPython = $studioCommand.Source; break }
            } catch { }
        }
    }
}
if (-not $studioPython) { throw 'Zainstaluj Python 3.12 x64, a potem uruchom instalator ponownie.' }
$studioDrive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($studioRoot).Substring(0,1))
if ($studioDrive.Free -lt 2GB) { throw 'Brak 2 GiB wolnego miejsca na biblioteki aplikacji.' }
Write-Host 'Instaluje biblioteki interfejsu. Modele AI NIE sa pobierane.'
& $studioPython -m venv --without-pip .venv
if ($LASTEXITCODE -ne 0) { throw 'Nie udalo sie utworzyc srodowiska.' }
& $studioPython -m pip --python '.venv\Scripts\python.exe' install --no-cache-dir -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Blad instalacji bibliotek. Sprawdz polaczenie i pip w Pythonie.' }
Write-Host 'Gotowe. Uruchom Uruchom.bat.'
