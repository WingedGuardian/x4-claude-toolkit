<#
  X4 Claude Toolkit installer - Windows (PowerShell).

  Three install methods, all with fully configurable paths (nothing hardcoded):
    in-game   Copy the toolkit INTO your X4 game folder (one workspace).
    separate  Keep the toolkit in its OWN folder, pointed at the game via config.
    global    Install skills/agents into %USERPROFILE%\.claude and write the X4_* paths
              into your global Claude settings, so they work across MANY mod repos.

  Every location is auto-detected where possible and overridable by parameter. Chosen paths
  are written to <toolkit>\.claude\x4-paths.env (the source of truth the hooks/scripts read).

  NOTE: the toolkit's hooks & bin/ scripts are bash; install with PowerShell, but to RUN the
  toolkit you still need Git Bash (https://git-scm.com/download/win), as upstream expects.

  Example:
    powershell -ExecutionPolicy Bypass -File install.ps1 -Method global
    powershell -ExecutionPolicy Bypass -File install.ps1 -Method separate -Game "D:\Steam\steamapps\common\X4 Foundations"
#>
[CmdletBinding()]
param(
  [ValidateSet('in-game','separate','global')] [string]$Method,
  [string]$Game, [string]$Profile, [string]$Toolkit, [string]$Mods,
  [string]$Reference, [string]$Extensions, [string]$XRCatTool,
  [switch]$Unpack, [switch]$Yes
)
$ErrorActionPreference = 'Stop'
$SRC = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "X4 Claude Toolkit installer (Windows) - source: $SRC"

# env fallbacks
if (-not $Game)      { $Game      = $env:X4_GAME }
if (-not $Profile)   { $Profile   = $env:X4_PROFILE }
if (-not $Toolkit)   { $Toolkit   = $env:X4_TOOLKIT }
if (-not $Mods)      { $Mods       = $env:X4_MODS }
if (-not $Reference) { $Reference  = $env:X4_REFERENCE }
if (-not $Extensions){ $Extensions = $env:X4_EXTENSIONS }
if (-not $XRCatTool) { $XRCatTool  = $env:XRCATTOOL }

# UTF-8 WITHOUT BOM, identical under Windows PowerShell 5.1 and pwsh 7. 5.1's
# -Encoding UTF8 writes a BOM, which bash reads as a command when it sources
# x4-paths.env - the whole bash half of the toolkit then fails on line 1.
function Write-Utf8NoBom($path, [string]$content) {
  [IO.File]::WriteAllText($path, $content, (New-Object System.Text.UTF8Encoding($false)))
}

function Ask($cur, $prompt, $def) {
  if ($cur) { $def = $cur }
  if ($Yes) { return $def }
  $ans = Read-Host "$prompt [$(if($def){$def}else{'blank'})]"
  if ([string]::IsNullOrWhiteSpace($ans)) { return $def } else { return $ans }
}

function Detect-Game {
  if ($Game) { return $Game }
  $roots = @("${env:ProgramFiles(x86)}\Steam", "$env:ProgramFiles\Steam")
  foreach ($root in $roots) {
    $p = Join-Path $root 'steamapps\common\X4 Foundations'
    if (Test-Path $p) { return $p }
    $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
    if (Test-Path $vdf) {
      foreach ($m in [regex]::Matches((Get-Content -Raw $vdf), '"path"\s*"([^"]+)"')) {
        $lib = $m.Groups[1].Value -replace '\\\\','\'
        $p = Join-Path $lib 'steamapps\common\X4 Foundations'
        if (Test-Path $p) { return $p }
      }
    }
  }
  return $Game
}

function Detect-Profile {
  if ($Profile) { return $Profile }
  $base = Join-Path $env:USERPROFILE 'Documents\Egosoft\X4'
  if (Test-Path $base) {
    $d = Get-ChildItem -Directory $base | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($d) { return $d.FullName }
  }
  return $Profile
}

function Detect-XRCat {
  if ($XRCatTool) { return $XRCatTool }
  foreach ($c in @("$SRC\tools\XRCatTool\XRCatTool.exe", "$SRC\XTools\XRCatTool.exe")) {
    if (Test-Path $c) { return $c }
  }
  return $XRCatTool
}

function Copy-Toolkit($dest) {
  New-Item -ItemType Directory -Force -Path $dest | Out-Null
  # 'mods' carries the game extension x4live needs (README: "copy that folder into
  # {game}/extensions/"). Omitting it shipped a documented instruction pointing at a
  # directory the installer never created.
  $items = '.claude','tools','bin','scripts','mods','CLAUDE.md','KNOWLEDGEBASE.md','README.md',
           'CHANGELOG.md','LICENSE','setup.sh','install.sh','install.ps1','SETUP_PROMPT.txt','.gitignore','.gitattributes'
  foreach ($i in $items) {
    $s = Join-Path $SRC $i
    if (Test-Path $s) { Copy-Item -Recurse -Force $s $dest }
  }
  Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $dest '.claude\settings.local.json'),(Join-Path $dest '.claude\x4-paths.env')
}

function Write-PathsEnv($t) {
  $dir = Join-Path $t '.claude'; New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $ref = if ($Reference) { $Reference } else { Join-Path $t 'reference' }
  $ext = if ($Extensions) { $Extensions } elseif ($Game) { Join-Path $Game 'extensions' } else { '' }
  $lines = @("# Written by install.ps1 ($(Get-Date -Format s)) - edit freely. All paths overridable.",
             "X4_TOOLKIT=`"$t`"")
  if ($Game)      { $lines += "X4_GAME=`"$Game`"" }
  $lines += "X4_REFERENCE=`"$ref`""
  if ($Profile)   { $lines += "X4_PROFILE=`"$Profile`""; $lines += "X4_DEBUGLOG=`"$Profile\debug.txt`"" }
  if ($Mods)      { $lines += "X4_MODS=`"$Mods`"" }
  if ($ext)       { $lines += "X4_EXTENSIONS=`"$ext`"" }
  if ($XRCatTool) { $lines += "XRCATTOOL=`"$XRCatTool`"" }
  $f = Join-Path $dir 'x4-paths.env'
  # UTF-8 WITHOUT BOM, LF endings: this file is sourced by bash (set -euo pipefail),
  # and Windows PowerShell 5.1's -Encoding UTF8 writes a BOM that bash reads as a
  # command ("command not found" on line 1, exit 127 before any path resolves).
  Write-Utf8NoBom $f (($lines -join "`n") + "`n")
  Write-Host "  wrote $f"
}

function Install-Global($t) {
  $hc = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
  New-Item -ItemType Directory -Force -Path (Join-Path $hc 'skills'),(Join-Path $hc 'agents') | Out-Null
  # Track exactly what WE copy - the $CLAUDE_PROJECT_DIR rewrite below must never
  # touch a user's pre-existing skills/agents (they may use that variable on purpose).
  $copied = @()
  Get-ChildItem -Directory (Join-Path $t '.claude\skills') -Filter 'x4-*' -ErrorAction SilentlyContinue |
    ForEach-Object {
      $dst = Join-Path $hc 'skills'
      Copy-Item -Recurse -Force $_.FullName $dst
      $copied += Get-ChildItem -Recurse -File (Join-Path $dst $_.Name) -Filter '*.md'
    }
  $agentsDst = Join-Path $hc 'agents'
  Get-ChildItem -File (Join-Path $t '.claude\agents') -Filter '*.md' -ErrorAction SilentlyContinue |
    ForEach-Object {
      Copy-Item -Force $_.FullName $agentsDst
      # NB: two-argument Join-Path only - the 3-arg form is pwsh 7+ and this script
      # must run under Windows PowerShell 5.1 (the README's own command).
      $copied += Get-Item (Join-Path $agentsDst $_.Name)
    }
  # global skills/agents run from any repo -> resolve validator via $X4_TOOLKIT
  foreach ($file in $copied) {
    $c = Get-Content -Raw $file.FullName
    if ($c.Contains('$CLAUDE_PROJECT_DIR')) {
      Write-Utf8NoBom $file.FullName ($c.Replace('$CLAUDE_PROJECT_DIR','$X4_TOOLKIT'))
    }
  }
  Write-Host "  installed x4 skills + agents into $hc"
  # merge env into settings.json
  $sj = Join-Path $hc 'settings.json'
  $cfg = if (Test-Path $sj) { Get-Content -Raw $sj | ConvertFrom-Json } else { [pscustomobject]@{} }
  if (-not $cfg.PSObject.Properties['env']) { $cfg | Add-Member -NotePropertyName env -NotePropertyValue ([pscustomobject]@{}) }
  $ref = if ($Reference) { $Reference } else { Join-Path $t 'reference' }
  $ext = if ($Extensions) { $Extensions } elseif ($Game) { Join-Path $Game 'extensions' } else { '' }
  function setenv($k,$v){ if ($v) { if ($cfg.env.PSObject.Properties[$k]) { $cfg.env.$k = $v } else { $cfg.env | Add-Member -NotePropertyName $k -NotePropertyValue $v } } }
  setenv X4_TOOLKIT $t; setenv X4_REFERENCE $ref; setenv X4_GAME $Game; setenv X4_PROFILE $Profile
  if ($Profile) { setenv X4_DEBUGLOG (Join-Path $Profile 'debug.txt') }
  setenv X4_MODS $Mods; setenv X4_EXTENSIONS $ext; setenv XRCATTOOL $XRCatTool
  Write-Utf8NoBom $sj (($cfg | ConvertTo-Json -Depth 20) + "`n")
  Write-Host "  merged X4_* env into $sj"
}

if (-not $Method) {
  Write-Host "`nInstall method:  1) in-game   2) separate   3) global (multi-repo)"
  $m = if ($Yes) { '2' } else { Read-Host "Choose [1/2/3]" }
  $Method = switch ($m) { '1' {'in-game'} '3' {'global'} default {'separate'} }
}
Write-Host "Method: $Method"

$Game = Detect-Game; $Profile = Detect-Profile; $XRCatTool = Detect-XRCat
$Game      = Ask $Game      'X4 game folder (01.cat..09.cat)' $Game
$Profile   = Ask $Profile   'X4 user profile folder'          $Profile
$XRCatTool = Ask $XRCatTool 'XRCatTool.exe path'              $XRCatTool

switch ($Method) {
  'in-game'  {
    if (-not $Game) { throw 'in-game needs -Game' }
    $Toolkit = $Game
    if ($SRC -ne $Toolkit) { Copy-Toolkit $Toolkit }
    Write-PathsEnv $Toolkit
  }
  'separate' {
    if (-not $Toolkit) { $Toolkit = $SRC }
    $Toolkit = Ask $Toolkit 'Toolkit folder' $Toolkit
    if ($SRC -ne $Toolkit) { Copy-Toolkit $Toolkit }
    Write-PathsEnv $Toolkit
  }
  'global'   {
    if (-not $Toolkit) { $Toolkit = $SRC }
    Write-PathsEnv $Toolkit
    Install-Global $Toolkit
  }
}

# wire x4validate (needs bash/uv); skip gracefully if bash missing
#
# `Get-Command bash` is NOT good enough. On any Windows machine with WSL enabled --
# which includes every Docker Desktop install -- `bash` resolves to the WSL stub at
# C:\Windows\System32\bash.exe (or the WindowsApps alias), NOT to Git Bash. MEASURED
# 2026-09-01 on a machine whose only distro is docker-desktop: setup.sh died with
#   WSL (9 - Relay) ERROR: CreateProcessCommon:640: execvpe(/bin/bash) failed
# and the installer reported INCOMPLETE. Worse, a machine WITH a real distro would
# have run setup.sh inside Linux, where C:\... paths do not resolve at all -- a
# silent wrong install rather than a loud failure.
#
# So: prefer a real Git Bash, and refuse the known stubs by path.
function Find-GitBash {
  $cands = @()
  foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)},
                      (Join-Path $env:LOCALAPPDATA 'Programs'))) {
    if ($base) { $cands += (Join-Path $base 'Git\bin\bash.exe') }
  }
  foreach ($c in $cands) { if (Test-Path $c) { return (Get-Command $c) } }
  # Fall back to PATH, but never to a WSL stub.
  foreach ($c in @(Get-Command bash -All -ErrorAction SilentlyContinue)) {
    $p = $c.Source
    if ($p -and $p -notmatch '\\(System32|SysWOW64|WindowsApps)\\') { return $c }
  }
  return $null
}
$bash = Find-GitBash
$failed = @()
if ($bash) {
  Push-Location $Toolkit
  # CLAUDE_PROJECT_DIR must be set explicitly: setup.sh falls back to $(pwd), and
  # if the caller already exports it (running from inside Claude Code is the
  # documented path) the fallback never applies and we would wire up THEIR repo
  # instead of the toolkit. install.sh has always passed it; this did not.
  $prev = $env:CLAUDE_PROJECT_DIR
  $env:CLAUDE_PROJECT_DIR = $Toolkit
  try {
    # $ErrorActionPreference='Stop' does NOT trap a native exit code, so each
    # call needs its own check - otherwise a failed unpack still reached
    # "=== install complete ===" and the user believed a broken install.
    & $bash.Source setup.sh
    if ($LASTEXITCODE -ne 0) { $failed += "setup.sh (exit $LASTEXITCODE)" }
    if ($Unpack) {
      & $bash.Source bin/unpack-reference.sh
      if ($LASTEXITCODE -ne 0) { $failed += "bin/unpack-reference.sh (exit $LASTEXITCODE)" }
    }
  } finally {
    $env:CLAUDE_PROJECT_DIR = $prev
    Pop-Location
  }
} else {
  # Git for Windows only adds ...\Git\cmd to PATH by default; bash.exe lives in
  # ...\Git\bin. Name the actual fix rather than telling them to run a command
  # they equally cannot run.
  Write-Host "  [note] bash not found on PATH, so x4validate was NOT wired up."
  Write-Host "         Git for Windows ships bash in <install>\bin (e.g. C:\Program Files\Git\bin)."
  Write-Host "         Either add that to PATH, or run setup from Git Bash:"
  Write-Host "           cd '$Toolkit' && CLAUDE_PROJECT_DIR='$Toolkit' bash setup.sh"
  $failed += "bash not found (x4validate not wired up)"
}

if ($failed.Count) {
  Write-Host "`n=== install INCOMPLETE ($Method) ===" -ForegroundColor Yellow
  foreach ($f in $failed) { Write-Host "  failed: $f" -ForegroundColor Yellow }
  Write-Host "Toolkit: $Toolkit"
  Write-Host "Fix the above and re-run, or complete the step by hand."
  exit 1
}

Write-Host "`n=== install complete ($Method) ==="
Write-Host "Toolkit: $Toolkit"
Write-Host "Config:  $Toolkit\.claude\x4-paths.env  (edit any path here)"
if ($Method -eq 'global') { Write-Host "Global:  skills/agents + X4_* env added to your ~/.claude - works from any mod repo." }
Write-Host ""
Write-Host "IMPORTANT - set X4_TOOLKIT in your user environment so the tools find the config"
Write-Host "above from ANY directory (they are often run from the game folder, which has a"
Write-Host ".claude\ but no x4-paths.env). This installer cannot do it for you:"
Write-Host "         setx X4_TOOLKIT `"$Toolkit`"        (takes effect in NEW shells)"
Write-Host "Verify:  cd `"$Toolkit\tools\x4validate`" ; uv run x4validate --paths"
