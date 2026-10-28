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
if (-not $studioPython) { throw 'Install Python 3.12 x64, then run the installer again.' }
$studioDrive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($studioRoot).Substring(0,1))
if ($studioDrive.Free -lt 2GB) { throw 'At least 2 GiB of free space is required for application dependencies.' }
Write-Host 'Installing KoeSub dependencies. AI model weights are NOT downloaded.'
& $studioPython -m venv --without-pip .venv
if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
& $studioPython -m pip --python '.venv\Scripts\python.exe' install --no-cache-dir -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed. Check your connection and Python pip installation.' }
Write-Host 'Ready. Run Run.bat to launch KoeSub.'
