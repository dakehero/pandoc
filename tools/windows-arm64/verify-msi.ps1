# Run on a disposable Windows CI runner: this installs and uninstalls the MSI.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$MsiPath,
    [Parameter(Mandatory)][ValidateSet('x64', 'arm64')][string]$Architecture,
    [Parameter(Mandatory)][string]$ReportDirectory,
    [ValidateSet('Pandoc', 'Arm64Fixture')][string]$PayloadKind = 'Pandoc'
)
$ErrorActionPreference = 'Stop'
$msi = (Resolve-Path -LiteralPath $MsiPath).Path
$reports = [IO.Path]::GetFullPath($ReportDirectory)
[IO.Directory]::CreateDirectory($reports) | Out-Null
$installer = New-Object -ComObject WindowsInstaller.Installer
$database = $installer.OpenDatabase($msi, 0)
$summary = $database.SummaryInformation(0)
$template = $summary.Property(7)
$expected = @{ x64 = 'x64'; arm64 = 'Arm64' }[$Architecture]
if (($template -split ';')[0] -cne $expected) {
    throw "Wrong MSI architecture: expected $expected, got $template"
}
$installerVersion = $summary.Property(14)
if ($Architecture -eq 'arm64' -and $installerVersion -lt 500) {
    throw "ARM64 MSI requires Windows Installer 5.0: got $installerVersion"
}
$directoryQuery = $database.OpenView('SELECT `Directory_Parent` FROM `Directory` WHERE `Directory` = ''APPLICATIONFOLDER''')
$directoryQuery.Execute()
$directoryRecord = $directoryQuery.Fetch()
if ($directoryRecord.StringData(1) -ne 'ProgramFiles64Folder') {
    throw '64-bit application directory must use ProgramFiles64Folder'
}
$directoryQuery.Close()
$query = $database.OpenView('SELECT `Value` FROM `Property` WHERE `Property` = ''ProductCode''')
$query.Execute()
$record = $query.Fetch()
$productCode = $record.StringData(1)
$query.Close()
$components = $database.OpenView('SELECT `Attributes` FROM `Component`')
$components.Execute()
while ($null -ne ($component = $components.Fetch())) {
    if (($component.IntegerData(1) -band 256) -eq 0) {
        throw 'A 64-bit MSI contains a component without the 64-bit attribute'
    }
}
$components.Close()
if (-not $env:RUNNER_TEMP) {
    throw 'RUNNER_TEMP must be set on a disposable CI runner'
}
$installDirectory = Join-Path $env:RUNNER_TEMP "pandoc-msi-$Architecture"
if (Test-Path -LiteralPath $installDirectory) {
    throw 'A fresh RUNNER_TEMP install directory is required'
}
try {
    $installArguments = "/i `"$msi`" /qn /norestart ALLUSERS=2 MSIINSTALLPERUSER=1 APPLICATIONFOLDER=`"$installDirectory`" /l*v `"$reports/install.log`""
    $process = Start-Process msiexec.exe -ArgumentList $installArguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "MSI install failed with exit code $($process.ExitCode)"
    }
    if ($PayloadKind -eq 'Arm64Fixture') {
        python "$PSScriptRoot/msi-fixture.py" --verify "$installDirectory/pandoc.exe"
    } else {
        python "$PSScriptRoot/verify-pandoc.py" "$installDirectory/pandoc.exe" --architecture $Architecture --report "$reports/verification-msi-$Architecture.json"
    }
    if ($LASTEXITCODE -ne 0) { throw 'Installed Pandoc verification failed' }
} finally {
    $uninstallArguments = "/x $productCode /qn /norestart /l*v `"$reports/uninstall.log`""
    $process = Start-Process msiexec.exe -ArgumentList $uninstallArguments -Wait -PassThru -WindowStyle Hidden
    if ($process.ExitCode -notin @(0, 3010, 1605)) {
        throw "MSI uninstall failed with exit code $($process.ExitCode)"
    }
}
if (Test-Path -LiteralPath "$installDirectory/pandoc.exe") {
    throw 'MSI uninstall left pandoc.exe behind'
}
@{ architecture = $Architecture; payloadKind = $PayloadKind; template = $template; installerVersion = $installerVersion; programFiles = 'ProgramFiles64Folder'; productCode = $productCode; install = 'passed'; uninstall = 'passed' } |
    ConvertTo-Json | Set-Content -LiteralPath "$reports/msi-lifecycle-$Architecture.json" -Encoding utf8
