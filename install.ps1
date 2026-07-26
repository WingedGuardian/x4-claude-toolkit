<#
  X4 Claude Toolkit installer — Windows (PowerShell).

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
Write-Host "X4 Claude Toolkit installer (Windows) — source: $SRC"

# env fallbacks
if (-not $Game)      { $Game      = $env:X4_GAME }
if (-not $Profile)   { $Profile   = $env:X4_PROFILE }
if (-not $Toolkit)   { $Toolkit   = $env:X4_TOOLKIT }
if (-not $Mods)      { $Mods       = $env:X4_MODS }
if (-not $Reference) { $Reference  = $env:X4_REFERENCE }
if (-not $Extensions){ $Extensions = $env:X4_EXTENSIONS }
if (-not $XRCatTool) { $XRCatTool  = $env:XRCATTOOL }

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
  $items = '.claude','tools','bin','scripts','CLAUDE.md','KNOWLEDGEBASE.md','README.md',
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
  $lines = @("# Written by install.ps1 ($(Get-Date -Format s)) — edit freely. All paths overridable.",
             "X4_TOOLKIT=`"$t`"")
  if ($Game)      { $lines += "X4_GAME=`"$Game`"" }
  $lines += "X4_REFERENCE=`"$ref`""
  if ($Profile)   { $lines += "X4_PROFILE=`"$Profile`""; $lines += "X4_DEBUGLOG=`"$Profile\debug.txt`"" }
  if ($Mods)      { $lines += "X4_MODS=`"$Mods`"" }
  if ($ext)       { $lines += "X4_EXTENSIONS=`"$ext`"" }
  if ($XRCatTool) { $lines += "XRCATTOOL=`"$XRCatTool`"" }
  $f = Join-Path $dir 'x4-paths.env'
  Set-Content -Path $f -Value $lines -Encoding UTF8
  Write-Host "  wrote $f"
}

function Install-Global($t) {
  $hc = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
  New-Item -ItemType Directory -Force -Path (Join-Path $hc 'skills'),(Join-Path $hc 'agents') | Out-Null
  Get-ChildItem -Directory (Join-Path $t '.claude\skills') -Filter 'x4-*' -ErrorAction SilentlyContinue |
    ForEach-Object { Copy-Item -Recurse -Force $_.FullName (Join-Path $hc 'skills') }
  Copy-Item -Force (Join-Path $t '.claude\agents\*.md') (Join-Path $hc 'agents') -ErrorAction SilentlyContinue
  # global skills/agents run from any repo -> resolve validator via $X4_TOOLKIT
  Get-ChildItem -Recurse -File (Join-Path $hc 'skills'),(Join-Path $hc 'agents') -Include '*.md' -ErrorAction SilentlyContinue |
    ForEach-Object {
      $c = Get-Content -Raw $_.FullName
      if ($c.Contains('$CLAUDE_PROJECT_DIR')) { $c.Replace('$CLAUDE_PROJECT_DIR','$X4_TOOLKIT') | Set-Content -Path $_.FullName -Encoding UTF8 }
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
  ($cfg | ConvertTo-Json -Depth 20) | Set-Content -Path $sj -Encoding UTF8
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
$bash = Get-Command bash -ErrorAction SilentlyContinue
if ($bash) {
  Push-Location $Toolkit
  & bash setup.sh
  if ($Unpack) { & bash bin/unpack-reference.sh }
  Pop-Location
} else {
  Write-Host "  [note] bash not found — install Git Bash, then run 'bash setup.sh' in $Toolkit"
}

Write-Host "`n=== install complete ($Method) ==="
Write-Host "Toolkit: $Toolkit"
Write-Host "Config:  $Toolkit\.claude\x4-paths.env  (edit any path here)"
if ($Method -eq 'global') { Write-Host "Global:  skills/agents + X4_* env added to your ~/.claude — works from any mod repo." }
