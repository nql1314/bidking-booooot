param(
    [string]$VersionTag = "v1.0",
    [switch]$NoObfuscation
)

$ErrorActionPreference = "Stop"

function Invoke-Python {
    param(
        [Parameter(Mandatory = $true)][string]$Cmd,
        [Parameter(Mandatory = $true)][string]$ErrMsg
    )
    Invoke-Expression $Cmd | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw $ErrMsg
    }
}

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$DistDir = Join-Path $RepoRoot "dist"
$BuildDir = Join-Path $RepoRoot "build"
$LauncherDir = Join-Path $BuildDir "launchers"
$ObfDir = Join-Path $BuildDir "obf"

Set-Location $RepoRoot

# Ensure all runtime/build dependencies are present in current environment
Invoke-Python -Cmd 'python -m pip install -U pip setuptools wheel' -ErrMsg "Failed to upgrade pip/setuptools/wheel."
Invoke-Python -Cmd 'python -m pip install -e ".[build]"' -ErrMsg "Failed to install project dependencies."
Invoke-Python -Cmd 'python -m pip install -U pyinstaller' -ErrMsg "Failed to install pyinstaller."

# Fast-fail if critical GUI automation dependency is missing
Invoke-Python -Cmd "python -c `"import pyautogui; print('pyautogui ok')`"" -ErrMsg "pyautogui import failed."

$UsePyArmor = -not $NoObfuscation
$SourceRoot = Join-Path $RepoRoot "src"

if ($UsePyArmor) {
    try {
        python -m pip install -U pyarmor | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "Failed to install pyarmor."
        }
        if (Test-Path $ObfDir) {
            Remove-Item -Recurse -Force $ObfDir
        }
        New-Item -ItemType Directory -Force -Path $ObfDir | Out-Null
        python -m pyarmor gen -O (Join-Path $ObfDir "src") (Join-Path $RepoRoot "src\bidking") | Out-Host
        if ($LASTEXITCODE -ne 0) {
            throw "PyArmor obfuscation failed."
        }
        $SourceRoot = Join-Path $ObfDir "src"
        Write-Host "[build] PyArmor obfuscation enabled."
    }
    catch {
        Write-Warning "[build] PyArmor unavailable; fallback to normal PyInstaller build."
        $SourceRoot = Join-Path $RepoRoot "src"
    }
}

if (Test-Path $LauncherDir) {
    Remove-Item -Recurse -Force $LauncherDir
}
New-Item -ItemType Directory -Force -Path $LauncherDir | Out-Null

$BotLauncher = Join-Path $LauncherDir "bot_runner_main.py"
$GridLauncher = Join-Path $LauncherDir "grid_view_main.py"

@"
import sys
sys.path.insert(0, r"$SourceRoot")
from bidking.ui.app import main
if __name__ == "__main__":
    main()
"@ | Set-Content -Path $BotLauncher -Encoding UTF8

@"
import sys
sys.path.insert(0, r"$SourceRoot")
from bidking.runner.viewer_main import main
if __name__ == "__main__":
    main()
"@ | Set-Content -Path $GridLauncher -Encoding UTF8

function Invoke-BuildExe {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$EntryFile
    )
    $targetExe = Join-Path $DistDir "$Name.exe"

    if (Test-Path $targetExe) {
        try {
            Remove-Item -Force $targetExe
        }
        catch {
            throw "Cannot overwrite $targetExe. Please close the running app and retry."
        }
    }

    python -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name "$Name" `
        --distpath "$DistDir" `
        --workpath (Join-Path $BuildDir "pyi_work") `
        --specpath (Join-Path $BuildDir "spec") `
        --paths "$SourceRoot" `
        --collect-all pyautogui `
        --collect-all pygetwindow `
        --collect-all pyscreeze `
        --collect-all mouseinfo `
        --collect-all pyrect `
        --collect-all pymsgbox `
        --collect-all rapidocr `
        --collect-all rapidocr_onnxruntime `
        --exclude-module pytest `
        --exclude-module tests `
        "$EntryFile" | Out-Host
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller build failed for $Name."
    }
}

Invoke-BuildExe -Name "bot_runner" -EntryFile $BotLauncher
Invoke-BuildExe -Name "grid_view" -EntryFile $GridLauncher

Write-Host ""
Write-Host "Build completed:"
Write-Host " - $(Join-Path $DistDir 'bot_runner.exe')"
Write-Host " - $(Join-Path $DistDir 'grid_view.exe')"
Write-Host "Version tag: $VersionTag"
