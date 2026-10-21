<#
Builds SchemeUp as a Windows program.

  powershell -ExecutionPolicy Bypass -File packaging\build.ps1

It leaves, in dist\:
  SchemeUp\SchemeUp.exe            the program and its files (run it from anywhere)
  SchemeUp-<version>-windows.zip   the same folder zipped, with a .sha256 next to it
  SchemeUp-<version>-setup.exe     the installer, when Inno Setup is installed

Before it finishes it starts the new SchemeUp.exe with --smoke-test, which checks the
fonts, the icon and every export format, so a broken build stops here.
#>
param([switch]$NoInstaller)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-Tool([string]$name, [string[]]$candidates) {
    $found = Get-Command $name -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    return $candidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
}

$uv = Find-Tool 'uv' @("$env:LOCALAPPDATA\Microsoft\WinGet\Links\uv.exe", "$env:USERPROFILE\.local\bin\uv.exe")
if (-not $uv) { throw 'uv is not installed. See https://docs.astral.sh/uv/' }

$version = (& $uv run --no-sync python -c 'import schemeup; print(schemeup.__version__)').Trim()
Write-Host "Building SchemeUp $version"

& $uv run --no-sync pyinstaller packaging/schemeup.spec --noconfirm --clean --distpath dist --workpath build/pyi
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

Write-Host 'Checking the build (smoke test)'
$report = Join-Path $env:TEMP 'schemeup-smoke.txt'
Remove-Item $report -ErrorAction SilentlyContinue
$run = Start-Process -FilePath 'dist\SchemeUp\SchemeUp.exe' -ArgumentList '--smoke-test' -Wait -PassThru
if ($run.ExitCode -ne 0) {
    if (Test-Path $report) { Get-Content $report | ForEach-Object { Write-Host "  $_" } }
    throw "The smoke test failed (exit code $($run.ExitCode))"
}
Write-Host '  ok'

$zip = "dist\SchemeUp-$version-windows.zip"
Remove-Item $zip -ErrorAction SilentlyContinue
Compress-Archive -Path 'dist\SchemeUp' -DestinationPath $zip
$hash = (Get-FileHash $zip -Algorithm SHA256).Hash.ToLower()
"$hash  $(Split-Path -Leaf $zip)" | Set-Content "$zip.sha256" -Encoding ascii

if (-not $NoInstaller) {
    $iscc = Find-Tool 'iscc' @(
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    if ($iscc) {
        $env:SCHEMEUP_VERSION = $version
        & $iscc /Q packaging\installer.iss
        if ($LASTEXITCODE -ne 0) { throw 'Inno Setup failed' }
    } else {
        Write-Host 'Inno Setup is not installed, so no installer was made: winget install JRSoftware.InnoSetup'
    }
}

Write-Host ''
Get-ChildItem dist -File | ForEach-Object { '{0,-40} {1,8:N1} MB' -f $_.Name, ($_.Length / 1MB) }
Write-Host 'Program: dist\SchemeUp\SchemeUp.exe'
