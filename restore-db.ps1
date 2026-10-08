param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$DumpPath,
    [string]$Container = 'cinema-postgres',
    [string]$Database = 'cinema',
    [string]$User = 'cinema'
)

$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $DumpPath -PathType Leaf)) {
    throw "Dump file not found: $DumpPath"
}
if ($DumpPath -like '*.partial') {
    throw 'Use a completed dump, not a .partial file.'
}

$dumpFile = (Resolve-Path -LiteralPath $DumpPath).Path
$containerFile = '/tmp/cinema-restore-' + [guid]::NewGuid().ToString('N') + '.dump'

try {
    docker cp $dumpFile "${Container}:$containerFile"
    if ($LASTEXITCODE -ne 0) { throw 'Failed to copy the dump.' }

    docker exec $Container pg_restore -U $User -d $Database --no-owner --no-privileges --single-transaction $containerFile
    if ($LASTEXITCODE -ne 0) { throw 'Restore failed; the transaction was rolled back.' }

    docker exec $Container psql -U $User -d $Database -v ON_ERROR_STOP=1 -c 'SELECT count(*) FROM movies; SELECT count(*) FROM users; ANALYZE;'
    if ($LASTEXITCODE -ne 0) { throw 'Restore completed, but data verification failed.' }

    Write-Host 'Restore and data verification completed.'
}
finally {
    docker exec $Container rm -f $containerFile
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Could not remove the temporary dump: $containerFile"
    }
}
