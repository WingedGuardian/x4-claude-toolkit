<#
  x4-userenv.ps1 -- the ONE reader/writer of a Windows USER environment variable for both
  installers (install.ps1 calls it in-process; install.sh calls it through powershell.exe).

    x4-userenv.ps1 get              print the persisted user value (nothing if unset); rc 0
    x4-userenv.ps1 set  <value>     persist it for the user, then read it back;   rc 0 / 1
    x4-userenv.ps1 unset            remove it (the undo for `set`);                 rc 0 / 1
    -Name <NAME>                    the variable (default X4_TOOLKIT)
    -Utf8Out                        write stdout as UTF-8 (a caller reading it through a
                                    pipe, i.e. install.sh); install.ps1 calls in-process
                                    and reads the pipeline, so it leaves the console alone

  Production writes HKCU\Environment through [Environment]::SetEnvironmentVariable(..,'User'),
  which also broadcasts WM_SETTINGCHANGE so terminals started from Explorer see the value.
  Not `setx` (cannot be pointed at a test key, truncates at 1024 chars silently) and not
  `reg add` (no broadcast).

  TEST SEAM, not a feature: X4_INSTALL_ENV_REGKEY names a registry key to use INSTEAD of
  HKCU\Environment. It must lie under HKCU\Software\X4ToolkitTests\ -- anything else is
  REFUSED (rc 2), so the seam can never be aimed at a real environment.

  Exit codes: 0 ok, 1 the write or read-back failed, 2 usage / refused seam / not Windows.
#>
param(
  [Parameter(Position = 0)] [string]$Action,
  [Parameter(Position = 1)] [string]$Value,
  [string]$Name = 'X4_TOOLKIT',
  [switch]$Utf8Out
)
$ErrorActionPreference = 'Stop'
# A caller reading our stdout through a pipe (install.sh) gets UTF-8, not the OEM code page.
if ($Utf8Out) { try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false) } catch { } }

$TestRoot = 'HKCU\Software\X4ToolkitTests\'

function Fail($rc, $msg) { [Console]::Error.WriteLine('x4-userenv: ' + $msg); exit $rc }

$onWindows = ($PSVersionTable.PSEdition -ne 'Core') -or $IsWindows
if (-not $onWindows) { Fail 2 'the user environment lives in the registry on Windows only' }
if ($Action -notin @('get', 'set', 'unset')) { Fail 2 'usage: x4-userenv.ps1 get | set <value> | unset  [-Name NAME]' }
if ($Name -notmatch '^[A-Za-z_][A-Za-z0-9_]*$') { Fail 2 ('not a variable name: ' + $Name) }

$seam = $env:X4_INSTALL_ENV_REGKEY
$key = $null
if ($seam) {
  if (-not $seam.StartsWith($TestRoot, [StringComparison]::OrdinalIgnoreCase) -or $seam.Length -le $TestRoot.Length) {
    Fail 2 ('REFUSING: X4_INSTALL_ENV_REGKEY must lie under ' + $TestRoot + ' (it is a TEST seam): ' + $seam)
  }
  $key = 'Registry::HKEY_CURRENT_USER\' + $seam.Substring(5)
}

function Get-Persisted {
  if ($key) {
    if (-not (Test-Path -LiteralPath $key)) { return $null }
    $p = Get-ItemProperty -LiteralPath $key -Name $Name -ErrorAction SilentlyContinue
    if ($null -eq $p) { return $null }
    return [string]$p.$Name
  }
  return [Environment]::GetEnvironmentVariable($Name, 'User')
}

switch ($Action) {
  'get' {
    $v = Get-Persisted
    if ($v) { Write-Output $v }
    exit 0
  }
  'set' {
    if ([string]::IsNullOrEmpty($Value)) { Fail 2 'set needs a non-empty value' }
    try {
      if ($key) {
        # Test-Path then New-Item, NEVER `New-Item -Force` on a key that exists: on the
        # registry provider -Force REPLACES the key, deleting every sibling value.
        # Each missing level is created on its own, so -Force is never needed.
        $walk = 'Registry::HKEY_CURRENT_USER'
        foreach ($seg in $seam.Substring(5).Split([char]92)) {
          if (-not $seg) { continue }
          $walk = $walk + [char]92 + $seg
          if (-not (Test-Path -LiteralPath $walk)) { $null = New-Item -Path $walk }
        }
        Set-ItemProperty -LiteralPath $key -Name $Name -Value $Value -Type String
      } else {
        [Environment]::SetEnvironmentVariable($Name, $Value, 'User')
      }
    } catch { Fail 1 ('could not write ' + $Name + ': ' + $_.Exception.Message) }
    $back = Get-Persisted
    if ($back -cne $Value) { Fail 1 ('wrote ' + $Name + ' but read back a different value: ' + $back) }
    exit 0
  }
  'unset' {
    try {
      if ($key) {
        if (Test-Path -LiteralPath $key) { Remove-ItemProperty -LiteralPath $key -Name $Name -ErrorAction SilentlyContinue }
      } else {
        # [NullString]::Value, NOT $null: PowerShell turns $null into "" for a [string]
        # parameter, and under pwsh 7 (.NET Core) "" WRITES an empty value instead of
        # deleting it. MEASURED 2026-10-02 (lane H live probe): 5.1 deleted, pwsh 7 left ''.
        [Environment]::SetEnvironmentVariable($Name, [NullString]::Value, 'User')
      }
    } catch { Fail 1 ('could not remove ' + $Name + ': ' + $_.Exception.Message) }
    if ($null -ne (Get-Persisted)) { Fail 1 ($Name + ' is still set after unset') }
    exit 0
  }
}
