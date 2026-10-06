$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = Join-Path $RepoRoot ".venv/Scripts/python.exe"
if (-not (Test-Path -LiteralPath $Python)) {
    $Python = Join-Path $RepoRoot ".venv/bin/python"
}
$FrontendRoot = Join-Path $RepoRoot "frontend"

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Missing .venv. Run the setup steps in AGENTS.md first."
}
if (-not (Test-Path -LiteralPath (Join-Path $FrontendRoot "node_modules"))) {
    throw "Missing frontend/node_modules. Run npm install in frontend first."
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Command
    )

    Write-Host "==> $Name"
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw "$Name failed with exit code $LASTEXITCODE"
    }
}

function Get-SharedFileSha256 {
    param([Parameter(Mandatory = $true)][string]$Path)

    $stream = [System.IO.File]::Open(
        $Path,
        [System.IO.FileMode]::Open,
        [System.IO.FileAccess]::Read,
        [System.IO.FileShare]::ReadWrite
    )
    try {
        $sha256 = [System.Security.Cryptography.SHA256]::Create()
        try {
            return ([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace("-", "")
        }
        finally {
            $sha256.Dispose()
        }
    }
    finally {
        $stream.Dispose()
    }
}

function Get-RuntimeSnapshot {
    $paths = @(
        "backend/data",
        "backend/config",
        "backend/generated",
        "backend/runtime"
    ) | ForEach-Object { Join-Path $RepoRoot $_ } | Where-Object { Test-Path -LiteralPath $_ }

    $files = foreach ($path in $paths) {
        Get-ChildItem -LiteralPath $path -Recurse -File -Force
    }
    $pluginRoot = Join-Path $RepoRoot "plugins"
    if (Test-Path -LiteralPath $pluginRoot) {
        $files = @($files) + @(
            Get-ChildItem -LiteralPath $pluginRoot -Recurse -File -Force -Filter "Cookie.json"
        )
    }
    $files |
        Sort-Object FullName |
        ForEach-Object {
            [pscustomobject]@{
                Path = $_.FullName
                Length = $_.Length
                LastWriteTimeUtc = $_.LastWriteTimeUtc.ToString("o")
                Sha256 = Get-SharedFileSha256 -Path $_.FullName
            }
        }
}

$before = @(Get-RuntimeSnapshot)
$verificationError = $null

try {
    Push-Location (Join-Path $RepoRoot "backend")
    try {
        Invoke-Checked "Backend compile" { & $Python -m compileall -q app }
        Invoke-Checked "Python dependencies" { & $Python -m pip check }
        Invoke-Checked "Backend tests" { & $Python -m pytest -q }

        $validator = Join-Path $RepoRoot "backend/scripts/validate_source_plugin.py"
        $pluginRoot = Join-Path $RepoRoot "plugins/sources"
        $pluginFiles = @(
            Get-ChildItem $pluginRoot -Recurse -Filter metadata.yaml
            Get-ChildItem $pluginRoot -Recurse -Filter source.py
        )
        $pluginDirs = $pluginFiles.DirectoryName | Sort-Object -Unique
        foreach ($pluginDir in $pluginDirs) {
            Invoke-Checked "Plugin $(Split-Path $pluginDir -Leaf)" {
                & $Python $validator --plugin $pluginDir
            }
        }
    }
    finally {
        Pop-Location
    }

    Push-Location $FrontendRoot
    try {
        Invoke-Checked "Frontend dependency audit" { & npm audit }
        Invoke-Checked "Frontend lint" { & npm run lint }
        Invoke-Checked "Frontend tests" { & npx --no-install vitest run }
        Invoke-Checked "Frontend build" { & npm run build }
        Invoke-Checked "Frontend visual compare" { & node (Join-Path $FrontendRoot "visual-diff/run-visual-diff.mjs") }
    }
    finally {
        Pop-Location
    }

    Push-Location (Join-Path $RepoRoot "backend")
    try {
        Invoke-Checked "Runtime import smoke" { & $Python -c "import app.main; print('runtime smoke: ok')" }
    }
    finally {
        Pop-Location
    }
}
catch {
    $verificationError = $_
}
finally {
    $after = @(Get-RuntimeSnapshot)
}

$runtimeChanges = @(
    Compare-Object `
        -ReferenceObject $before `
        -DifferenceObject $after `
        -Property Path, Length, LastWriteTimeUtc, Sha256
)
if ($runtimeChanges.Count -gt 0) {
    $changedPaths = ($runtimeChanges | ForEach-Object { "$($_.SideIndicator) $($_.Path)" }) -join "; "
    $message = "Verification modified backend runtime data or configuration: $changedPaths"
    if ($verificationError) {
        $message += " Original failure: $($verificationError.Exception.Message)"
    }
    throw $message
}
if ($verificationError) {
    throw $verificationError
}

Write-Host "Verification passed without runtime data changes."
