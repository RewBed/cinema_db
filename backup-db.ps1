[CmdletBinding()]
param(
    [string]$SshHost,
    [string]$SshUser,
    [ValidateRange(1, 65535)]
    [int]$SshPort = 22,
    [string]$PythonExecutable,
    [string]$Service = 'cinema_db_cinema-postgres',
    [switch]$UseSudo,
    [switch]$Check
)

$ErrorActionPreference = "Stop"

# Resolve defaults after parameter binding for Windows PowerShell compatibility.
$backupScriptDirectory = $PSScriptRoot
if (-not $backupScriptDirectory) {
    $backupScriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
}

if (-not $PythonExecutable) {
    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if (-not $pythonCommand) { throw "Python 3 is required. Pass -PythonExecutable with its path." }
    $PythonExecutable = $pythonCommand.Source
}

$scriptFile = Join-Path $backupScriptDirectory "backup-db.py"
$backupArguments = @($scriptFile, '--port', $SshPort, '--service', $Service)
if ($SshHost) { $backupArguments += @('--host', $SshHost) }
if ($SshUser) { $backupArguments += @('--user', $SshUser) }
if ($UseSudo) { $backupArguments += '--sudo' }
if ($Check) {
    & $PythonExecutable @backupArguments --check
    if ($LASTEXITCODE -ne 0) { throw "Local configuration check failed." }
    return
}

$venvDirectory = Join-Path $backupScriptDirectory ".venv-db-backup"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "Preparing local Python environment..."
    & $PythonExecutable -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw "Unable to create the Python environment." }
}

& $venvPython -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('paramiko') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing the local SSH library (Paramiko)..."
    & $venvPython -m pip install --disable-pip-version-check "paramiko>=3.5,<5"
    if ($LASTEXITCODE -ne 0) { throw "Unable to install Paramiko. Check network access to PyPI." }
}

& $venvPython @backupArguments
if ($LASTEXITCODE -ne 0) { throw "Backup failed. Do not use partial files as backups." }
