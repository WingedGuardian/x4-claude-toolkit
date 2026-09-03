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
  [switch]$Unpack, [switch]$Yes, [switch]$OverExisting, [switch]$DryRun
)
$ErrorActionPreference = 'Stop'
$SRC = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "X4 Claude Toolkit installer (Windows) - source: $SRC"

# Did a HUMAN name the destination, or did we find it by scanning? An explicit
# switch or an env var is a deliberate act; a Steam-folder scan is not.
$GameNamed    = if ($Game)    { 'named' } elseif ($env:X4_GAME)    { 'named' } else { 'detected' }
$ToolkitNamed = if ($Toolkit) { 'named' } elseif ($env:X4_TOOLKIT) { 'named' } else { 'detected' }

# env fallbacks
if (-not $Game)      { $Game      = $env:X4_GAME }
if (-not $Profile)   { $Profile   = $env:X4_PROFILE }
if (-not $Toolkit)   { $Toolkit   = $env:X4_TOOLKIT }
if (-not $Mods)      { $Mods       = $env:X4_MODS }
if (-not $Reference) { $Reference  = $env:X4_REFERENCE }
if (-not $Extensions){ $Extensions = $env:X4_EXTENSIONS }
if (-not $XRCatTool) { $XRCatTool  = $env:XRCATTOOL }

# THE DRY-RUN GATE. Called from every function that WRITES, never from the
# dispatch -- the same placement as refuse_if_dry_run in install.sh, and for the
# same reason: an arm added later cannot write without passing through one of
# these three, so it cannot silently escape the flag.
#
# It had to exist at all because $DryRun was consulted in exactly ONE place,
# inside Show-Target, which the global arm never reaches. MEASURED in a sandbox:
# `-Method global -DryRun` overwrote x4-paths.env and printed
# '=== install complete (global) ==='.
#
# Defined here, above every writer, because PowerShell defines a function when
# execution REACHES it -- the same trap that already moved Write-PathsEnv's
# helper above the dispatch.
function Refuse-IfDryRun($what, $where) {
  if (-not $DryRun) { return }
  Write-Host ''
  Write-Host ('  -DryRun: NOT ' + $what + ':')
  Write-Host ('      ' + $where)
  Write-Host ''
  Write-Host '=== dry run complete: nothing was changed ==='
  exit 0
}

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
    if (Test-Path -LiteralPath $p) { return $p }
    $vdf = Join-Path $root 'steamapps\libraryfolders.vdf'
    if (Test-Path -LiteralPath $vdf) {
      foreach ($m in [regex]::Matches((Get-Content -Raw -LiteralPath $vdf), '"path"\s*"([^"]+)"')) {
        $lib = $m.Groups[1].Value -replace '\\\\','\'
        $p = Join-Path $lib 'steamapps\common\X4 Foundations'
        if (Test-Path -LiteralPath $p) { return $p }
      }
    }
  }
  return $Game
}

function Detect-Profile {
  if ($Profile) { return $Profile }
  $base = Join-Path $env:USERPROFILE 'Documents\Egosoft\X4'
  if (Test-Path -LiteralPath $base) {
    $d = Get-ChildItem -Directory -LiteralPath $base | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($d) { return $d.FullName }
  }
  return $Profile
}

function Detect-XRCat {
  if ($XRCatTool) { return $XRCatTool }
  foreach ($c in @("$SRC\tools\XRCatTool\XRCatTool.exe", "$SRC\XTools\XRCatTool.exe")) {
    if (Test-Path -LiteralPath $c) { return $c }
  }
  return $XRCatTool
}

# Paths never copied between toolkits, pruned from the destination BOTH before and
# after the copy. One list, named once: two passes over two hand-written lists is how
# they drift, and the defect this fixes was one of the passes not running at all.
$X4CopyPrune = @('tools\x4validate\.venv','tools\x4validate\.pytest_cache','tools\x4validate\.mutation-probe-pristine')

# Copy $SRC\REL to DEST\REL, never descending into a pruned relative path.
#
# The virtualenv used to be copied in full and deleted on arrival, while the
# CHANGELOG said it no longer travels. Copy-Item -Exclude cannot express this: it
# matches LEAF NAMES, not paths, and is unreliable with -Recurse. So the walk is
# explicit, and ONLY where needed -- a directory containing no pruned path is
# still copied in a single call, so only tools\ is ever descended into.
#
# The Copy-Item target is the destination's PARENT: -Recurse into the path itself
# nests on an upgrade, which is the .claude\.claude shape.
function Copy-Excluding([string]$rel, [string]$dest) {
  foreach ($junk in $X4CopyPrune) { if ($junk -ieq $rel) { return } }
  # $fromPath, NOT $src. PowerShell variable names are CASE-INSENSITIVE, so a local
  # `$src` IS the script-scope `$SRC` -- assigning it overwrote the source root, and
  # the first recursion then built `src\tools\tools\basex` and died with
  # "Cannot find path". In bash those are two different variables; here they are one.
  $fromPath = Join-Path $SRC $rel
  $needsWalk = $false
  foreach ($junk in $X4CopyPrune) {
    if ($junk -like ($rel + [char]92 + '*') -or $junk -like ($rel + '/*')) {
      $needsWalk = $true
    }
  }
  $isDir = Test-Path -LiteralPath $fromPath -PathType Container
  $target = Join-Path $dest $rel
  if (-not $isDir -or -not $needsWalk) {
    $parent = Split-Path -Parent $target
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    # NO Remove-Item on the target first. A draft cleared it to avoid nesting and
    # thereby deleted the .bak files Copy-Toolkit had just written into $dest\.claude
    # -- 11 of 17 harness cases red, including "a backup was made". This is the exact
    # form the original loop used, and the upgrade case proves it merges rather than
    # nesting.
    Copy-Item -Recurse -Force -LiteralPath $fromPath -Destination $parent
    return
  }
  New-Item -ItemType Directory -Force -Path $target | Out-Null
  foreach ($c in (Get-ChildItem -Force -LiteralPath $fromPath)) {
    Copy-Excluding ($rel + [char]92 + $c.Name) $dest
  }
}

function Copy-Toolkit($dest) {
  Refuse-IfDryRun 'copying the toolkit into' $dest
  New-Item -ItemType Directory -Force -Path (Join-Path $dest '.claude') | Out-Null

  # BACK UP BEFORE THE COPY, and that ordering IS the fix. The Copy-Item loop below
  # overwrites .claude wholesale, so anything saved afterwards is the SOURCE machine's
  # file being reported as the user's. MEASURED on the bash side against a source that
  # had itself been set up -- the destination's X4_NEXUS_KEY was gone from every file
  # while the run printed "kept your existing".
  #
  # This side had no backup at all: it ended with a bare Remove-Item of both files, no
  # copy, no message, exit 0. Windows is the platform this toolkit targets, and
  # install.ps1 is the README's own Windows command.
  $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
  $keeps = @('settings.local.json','x4-paths.env')
  $saved = @{}
  foreach ($k in $keeps) {
    $live = Join-Path $dest (Join-Path '.claude' $k)
    if (Test-Path -LiteralPath $live) {
      $bak = "$live.bak-$stamp"
      Copy-Item -Force -LiteralPath $live -Destination $bak
      $saved[$k] = $bak
    }
  }

  # 'mods' carries the game extension x4live needs (README: "copy that folder into
  # {game}/extensions/"). Omitting it shipped a documented instruction pointing at a
  # directory the installer never created.
  $items = '.claude','tools','bin','scripts','mods','CLAUDE.md','KNOWLEDGEBASE.md','README.md',
           'CHANGELOG.md','LICENSE','setup.sh','install.sh','install.ps1','SETUP_PROMPT.txt','.gitignore','.gitattributes'
  # -LiteralPath throughout. Without it PowerShell treats [ and ] as WILDCARDS, so a
  # source folder named e.g. "x4-claude-toolkit [v3.0.0]" -- the shape a download gives
  # you -- matches nothing. MEASURED 2026-09-01: bare Test-Path returned False and bare
  # Copy-Item copied 0 files, while -LiteralPath copied all of them. The installer then
  # printed "install complete" over an empty destination, and the README says "extract
  # it anywhere".
  # PRUNE THE DESTINATION FIRST. The same list runs after the copy loop, and running
  # it ONLY after is what broke the bash installer on the documented upgrade path:
  # uv hardlinks package files from a shared cache, so once both trees have been synced
  # the same file has the same inode in each and a recursive copy refuses. A cleanup
  # that only runs after the copy cannot make the copy possible. Kept in step with
  # install.sh deliberately -- one installer correct by accident is how the two drift.
  foreach ($junk in $X4CopyPrune) {
    $p = Join-Path $dest $junk
    if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p -ErrorAction SilentlyContinue }
  }

  $missing = @()
  foreach ($i in $items) {
    $s = Join-Path $SRC $i
    if (Test-Path -LiteralPath $s) {
      Copy-Excluding $i $dest
    } else {
      # NAMED, never silently skipped: that silence is how the absent mods/ folder
      # survived a whole release.
      $missing += $i
    }
  }
  if ($missing.Count) {
    Write-Host ("  [note] not in the source, so not copied: " + ($missing -join ", "))
  }

  # A VIRTUALENV MUST NOT TRAVEL. uv hardlinks package files from a shared cache, so
  # once both trees have been synced independently the same file has the same inode in
  # each -- and a recursive copy then fails with "are the same file", 1,334 times, part
  # way through. pyvenv.cfg and the Scripts shims also embed absolute paths, so a copied
  # venv points back at the source. setup.sh recreates it anyway.
  # ...and again afterwards, so the SOURCE machine's virtualenv does not linger here.
  foreach ($junk in $X4CopyPrune) {
    $p = Join-Path $dest $junk
    if (Test-Path -LiteralPath $p) { Remove-Item -Recurse -Force -LiteralPath $p -ErrorAction SilentlyContinue }
  }

  # PUT THE USER'S BACK. Whatever the copy just landed came from the SOURCE machine --
  # its paths, its Nexus key -- and has no business on this one. PRESERVED, not merely
  # archived: setup.sh only recreates settings.local.json when it is ABSENT, so keeping
  # it here is what makes an upgrade non-destructive rather than merely recoverable.
  foreach ($k in $keeps) {
    $live = Join-Path $dest (Join-Path '.claude' $k)
    if ($saved.ContainsKey($k)) {
      Copy-Item -Force -LiteralPath $saved[$k] -Destination $live
      Write-Host ("  [note] kept your existing $k (backup: " + (Split-Path $saved[$k] -Leaf) + ")")
    } elseif (Test-Path -LiteralPath $live) {
      # Nothing was here before, so anything present now arrived from the source.
      Remove-Item -Force -LiteralPath $live -ErrorAction SilentlyContinue
    }
  }
}

# MOVED ABOVE THE DISPATCH. PowerShell defines a function when execution REACHES
# it, so this sitting below `switch ($Method)` meant Write-PathsEnv's
# can-bash-source-this check called a name that did not exist yet and the install
# died with CommandNotFoundException after the copy.
# Strip a trailing path separator. `-Toolkit "$SRC\"` is not -eq to
# $SRC, so the copy branch is taken and the tree is copied onto itself. The bash
# twin of this was MEASURED failing with 'are the same file' and writing no
# config at all. A drive root keeps its separator.
# Are these the SAME directory? Asked canonically, never as a string -- the bash
# twin of this compared an MSYS spelling against a Windows one and copied the tree
# onto itself. Resolve-Path settles dialect, trailing separators and relative
# segments; a destination that does not exist yet cannot be the source.
function Test-SameDir([string]$a, [string]$b) {
  if (-not $a -or -not $b) { return $false }
  try {
    $ra = (Resolve-Path -LiteralPath $a -ErrorAction Stop).ProviderPath
    $rb = (Resolve-Path -LiteralPath $b -ErrorAction Stop).ProviderPath
  } catch { return $false }
  return ([System.IO.Path]::GetFullPath($ra).TrimEnd([char]92, [char]47) -ieq
          [System.IO.Path]::GetFullPath($rb).TrimEnd([char]92, [char]47))
}

function Remove-TrailingSep([string]$p) {
  if (-not $p) { return $p }
  while ($p.Length -gt 1 -and ($p.EndsWith('/') -or $p.EndsWith([char]92))) {
    if ($p.Length -eq 3 -and $p[1] -eq ':') { break }   # C:/ or C:\
    $p = $p.Substring(0, $p.Length - 1)
  }
  return $p
}

function Find-GitBash {
  $cands = @()
  foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)},
                      (Join-Path $env:LOCALAPPDATA 'Programs'))) {
    if ($base) { $cands += (Join-Path $base 'Git\bin\bash.exe') }
  }
  foreach ($c in $cands) { if (Test-Path -LiteralPath $c) { return (Get-Command $c) } }
  # Fall back to PATH, but never to a WSL stub.
  foreach ($c in @(Get-Command bash -All -ErrorAction SilentlyContinue)) {
    $p = $c.Source
    if ($p -and $p -notmatch '\\(System32|SysWOW64|WindowsApps)\\') { return $c }
  }
  return $null
}

function Get-EscapedEnvValue($v) {
  # The value lands inside a bash DOUBLE-QUOTED string, so a trailing separator is not
  # cosmetic: X4_TOOLKIT="C:\path\" never closes its quote, `set -a; . "$cfg"` aborts on
  # it, and EVERY X4_* comes out unset while this installer reports success. Windows
  # tab-completion appends that backslash, and a drive root IS one.
  # MEASURED: with a trailing separator the sourced config yielded X4_GAME, X4_REFERENCE
  # and X4_EXTENSIONS all UNSET, exit 0, "=== install complete ===".
  if ($null -eq $v) { return '' }
  $v = ([string]$v).TrimEnd('/','\')
  $v = $v.Replace('\','\\')      # backslashes FIRST, or we double the ones added below
  $v = $v.Replace('"','\"')
  $v = $v.Replace('$','\$')
  $v = $v.Replace('`','\`')
  return $v
}

function Write-PathsEnv($t) {
  $dir = Join-Path $t '.claude'; New-Item -ItemType Directory -Force -Path $dir | Out-Null
  $f = Join-Path $dir 'x4-paths.env'

  Refuse-IfDryRun 'writing the path config into' $f

  # BACKED UP HERE, not at the call sites -- the placement install.sh uses, so a
  # method added later cannot write without a backup. The bash side got this fix;
  # this one did not, which made it the fourth 'fixed in bash, absent in
  # PowerShell' defect of the release.
  #
  # Less severe than the bash case was, and worth stating rather than glossing:
  # the carry-over loop below preserves every key this function does not own, so
  # X4_NEXUS_KEY and hand-added lines survive. But the OWNED keys are replaced
  # outright, and nothing else records what they used to say.
  #
  # A backup that silently did not happen is worse than none, because the message
  # would have claimed it did -- so a failure is reported, not swallowed.
  if (Test-Path -LiteralPath $f) {
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
    try {
      Copy-Item -LiteralPath $f -Destination ($f + '.bak-' + $stamp) -Force -ErrorAction Stop
      Write-Host ('  [note] kept your previous x4-paths.env as x4-paths.env.bak-' + $stamp)
    } catch {
      Write-Host ('  [warn] could not back up x4-paths.env: ' + $_.Exception.Message)
      Write-Host '         the existing values are about to be replaced'
    }
  }
  $ref = if ($Reference) { $Reference } else { Join-Path $t 'reference' }
  $ext = if ($Extensions) { $Extensions } elseif ($Game) { Join-Path $Game 'extensions' } else { '' }

  # KEYS THIS FUNCTION DOES NOT OWN ARE CARRIED OVER. setup.sh tells the user to keep
  # X4_NEXUS_KEY in this file and its own header says "edit freely", yet every upgrade
  # rebuilt it from scratch -- so the key survived only in a .bak nobody opens.
  $owned = @('X4_TOOLKIT','X4_GAME','X4_REFERENCE','X4_PROFILE','X4_DEBUGLOG','X4_MODS','X4_EXTENSIONS','XRCATTOOL')
  $carried = @()
  if (Test-Path -LiteralPath $f) {
    foreach ($line in (Get-Content -LiteralPath $f)) {
      if ($line -match '^\s*#' -or $line -notmatch '=') { continue }
      $key = ($line -split '=', 2)[0].Trim()
      if ($owned -notcontains $key) { $carried += $line }
    }
  }

  $lines = @("# Written by install.ps1 ($(Get-Date -Format s)) - edit freely. All paths overridable.",
             ('X4_TOOLKIT="' + (Get-EscapedEnvValue $t) + '"'))
  if ($Game)      { $lines += ('X4_GAME="' + (Get-EscapedEnvValue $Game) + '"') }
  $lines += ('X4_REFERENCE="' + (Get-EscapedEnvValue $ref) + '"')
  if ($Profile)   { $lines += ('X4_PROFILE="' + (Get-EscapedEnvValue $Profile) + '"')
                    $lines += ('X4_DEBUGLOG="' + (Get-EscapedEnvValue (Join-Path $Profile 'debug.txt')) + '"') }
  if ($Mods)      { $lines += ('X4_MODS="' + (Get-EscapedEnvValue $Mods) + '"') }
  if ($ext)       { $lines += ('X4_EXTENSIONS="' + (Get-EscapedEnvValue $ext) + '"') }
  if ($XRCatTool) { $lines += ('XRCATTOOL="' + (Get-EscapedEnvValue $XRCatTool) + '"') }
  if ($carried.Count) {
    $lines += '# --- carried over from your previous x4-paths.env ---'
    $lines += $carried
  }

  # UTF-8 WITHOUT BOM, LF endings: this file is sourced by bash (set -euo pipefail),
  # and Windows PowerShell 5.1's -Encoding UTF8 writes a BOM that bash reads as a
  # command ("command not found" on line 1, exit 127 before any path resolves).
  Write-Utf8NoBom $f (($lines -join "`n") + "`n")

  # VERIFY THE ARTIFACT, never the exit code. A config bash cannot source is exactly
  # what the escaping above exists to prevent, and proving it costs one bash call --
  # the same rule this installer already applies to the jq merge. Skipped, loudly, only
  # when there is no bash to ask.
  $bash = Find-GitBash
  if ($bash) {
    # ONE argument, no embedded double quote, and the path inside a SINGLE-quoted
    # bash string. Windows PowerShell 5.1 splits a native argument that itself
    # contains double quotes at the first space, so the previous form failed on
    # every destination with a space in it -- which is the README's own command on
    # a stock Steam install, and Write-PathsEnv runs for all three methods.
    #
    # ErrorActionPreference is relaxed around the call for the second half of the
    # same fault: with 'Stop' in force, the 2>&1 merge turns bash's stderr into a
    # TERMINATING error, so the script died here instead of reaching the branch
    # below and printing the message written for exactly this case.
    # .Replace, not -replace: the operator read the concatenation as extra
    # operands ("allows only two elements to follow it, not 4") and the script
    # died before installing anything. A path is not a regex either, so
    # -replace was the wrong tool twice over. A single quote inside a
    # single-quoted bash string is closed, escaped and reopened.
    $sq = [string][char]39
    $bp = ($f -replace '\\','/').Replace($sq, $sq + [char]92 + $sq + $sq)
    $prevEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
      $probe = & $bash -c "set -a; . '$bp'" 2>&1
    } finally {
      $ErrorActionPreference = $prevEAP
    }
    if ($LASTEXITCODE -ne 0) {
      Write-Host "ERROR: wrote $f but bash cannot SOURCE it, so every X4_* would come out unset." -ForegroundColor Red
      Write-Host "       Refusing to report success. This is a quoting fault in one of the paths." -ForegroundColor Red
      Write-Host ("       bash said: " + ($probe -join ' ')) -ForegroundColor Red
      exit 1
    }
  } else {
    Write-Host "  [warn] no bash found, so $f was NOT verified as sourceable"
  }
  Write-Host "  wrote $f"
  if ($carried.Count) { Write-Host ("  [note] carried over " + $carried.Count + " setting(s) you had added") }
}

function Test-LooksInstalled($d) {
  foreach ($m in @('.claude\hooks\protect-bash.sh','tools\x4validate','CLAUDE.md','KNOWLEDGEBASE.md')) {
    if (Test-Path -LiteralPath (Join-Path $d $m)) { return $true }
  }
  return $false
}

function Assert-Direction($dest, $named) {
  # MEASURED 2026-09-02 on the bash side: an install with an auto-detected destination
  # and -Yes wrote 1,642 files into a real Steam install and exited 0. Every X4_*
  # variable had been cleared first and none of it mattered, because the Steam path is
  # HARDCODED. Seven personal files were overwritten, including a 145 KB CLAUDE.md and a
  # 631 KB KNOWLEDGEBASE.md, recovered only from a Volume Shadow Copy.
  #
  # The rule (user-set): a new install must not proceed over an EXISTING install without
  # strict DIRECTION -- a switch naming the intent -- not merely an approval that can be
  # clicked through. And a destination nobody named is not a destination at all when
  # nobody is watching.
  if ($named -eq 'detected' -and $Yes) {
    Write-Host "REFUSING: -Yes with an auto-detected destination." -ForegroundColor Red
    Write-Host "  Detected: $dest" -ForegroundColor Red
    Write-Host "  Nothing named that path - it came from scanning the usual Steam locations," -ForegroundColor Red
    Write-Host "  and -Yes means no one will see this before the write starts." -ForegroundColor Red
    Write-Host "  Name it explicitly:  -Game `"$dest`"   (or -Toolkit for separate/global)" -ForegroundColor Red
    exit 2
  }
  if ((Test-LooksInstalled $dest) -and -not $OverExisting) {
    Write-Host "REFUSING: there is already an installation at the destination." -ForegroundColor Red
    Write-Host "  Destination: $dest" -ForegroundColor Red
    Write-Host "  Found:" -ForegroundColor Red
    foreach ($m in @('.claude\hooks\protect-bash.sh','tools\x4validate','CLAUDE.md','KNOWLEDGEBASE.md')) {
      if (Test-Path -LiteralPath (Join-Path $dest $m)) { Write-Host "      $m" -ForegroundColor Red }
    }
    Write-Host "" -ForegroundColor Red
    Write-Host "  Installing over it REPLACES those files. If any of them are yours - an" -ForegroundColor Red
    Write-Host "  edited CLAUDE.md, your own KNOWLEDGEBASE.md, customised skills - they are" -ForegroundColor Red
    Write-Host "  gone, and only .claude\x4-paths.env and settings.local.json are preserved." -ForegroundColor Red
    Write-Host "" -ForegroundColor Red
    Write-Host "  To upgrade it anyway, say so explicitly:" -ForegroundColor Red
    Write-Host "      .\install.ps1 -Method $Method -OverExisting ..." -ForegroundColor Red
    exit 2
  }
}

# Says WHERE, and nothing else -- see announce_target in install.sh for why the
# dry-run listing moved out: it only makes sense where a copy happens, and having
# both jobs in one function kept the global arm silent about its destination.
function Show-Target($dest) {
  Write-Host ""
  Write-Host "  About to write the toolkit into:"
  Write-Host "      $dest"
}

# The dry-run listing, for the arms where a COPY would actually happen. The gate
# itself is Refuse-IfDryRun, which sits inside all three writers.
function Show-CopyPlan {
  if ($DryRun) {
    Write-Host "  -DryRun: nothing will be written. Items that would be copied:"
    foreach ($i in @('.claude','tools','bin','scripts','mods','CLAUDE.md','KNOWLEDGEBASE.md','README.md',
                     'CHANGELOG.md','LICENSE','setup.sh','install.sh','install.ps1','SETUP_PROMPT.txt',
                     '.gitignore','.gitattributes')) {
      if (Test-Path -LiteralPath (Join-Path $SRC $i)) { Write-Host "      $i" }
    }
    Write-Host ""
    Write-Host "=== dry run complete: nothing was changed ==="
    exit 0
  }
}

function Install-Global($t) {
  Refuse-IfDryRun 'installing the global Claude config for' $t
  $hc = if ($env:CLAUDE_CONFIG_DIR) { $env:CLAUDE_CONFIG_DIR } else { Join-Path $env:USERPROFILE '.claude' }
  New-Item -ItemType Directory -Force -Path (Join-Path $hc 'skills'),(Join-Path $hc 'agents') | Out-Null
  # Track exactly what WE copy - the $CLAUDE_PROJECT_DIR rewrite below must never
  # touch a user's pre-existing skills/agents (they may use that variable on purpose).
  $copied = @()
  Get-ChildItem -Directory -LiteralPath (Join-Path $t '.claude\skills') -Filter 'x4-*' -ErrorAction SilentlyContinue |
    ForEach-Object {
      $dst = Join-Path $hc 'skills'
      Copy-Item -Recurse -Force -LiteralPath $_.FullName -Destination $dst
      $copied += Get-ChildItem -Recurse -File -LiteralPath (Join-Path $dst $_.Name) -Filter '*.md'
    }
  $agentsDst = Join-Path $hc 'agents'
  Get-ChildItem -File -LiteralPath (Join-Path $t '.claude\agents') -Filter '*.md' -ErrorAction SilentlyContinue |
    ForEach-Object {
      Copy-Item -Force -LiteralPath $_.FullName -Destination $agentsDst
      # NB: two-argument Join-Path only - the 3-arg form is pwsh 7+ and this script
      # must run under Windows PowerShell 5.1 (the README's own command).
      $copied += Get-Item -LiteralPath (Join-Path $agentsDst $_.Name)
    }
  # global skills/agents run from any repo -> resolve validator via $X4_TOOLKIT
  foreach ($file in $copied) {
    $c = Get-Content -Raw -LiteralPath $file.FullName
    if ($c.Contains('$CLAUDE_PROJECT_DIR')) {
      Write-Utf8NoBom $file.FullName ($c.Replace('$CLAUDE_PROJECT_DIR','$X4_TOOLKIT'))
    }
  }
  # "I copied nothing" must never print as "installed". The whole function used bare
  # path cmdlets, so a toolkit path containing `[` or `]` -- which PowerShell reads as a
  # WILDCARD CHARACTER CLASS, not as text -- matched nothing, `-ErrorAction
  # SilentlyContinue` swallowed the miss, and this said "installed x4 skills + agents"
  # over an empty directory. MEASURED 2026-09-01 under a path named `toolkit [v3]`:
  # bare Get-ChildItem found 0, -LiteralPath found 1, in both the skills and agents legs.
  if ($copied.Count -eq 0) {
    Write-Host "  ERROR: copied NOTHING from $t (.claude\skills\x4-* and .claude\agents\*.md)."
    Write-Host "         Nothing was installed into $hc -- this is a FAILURE, not a no-op."
    exit 1
  }
  Write-Host "  installed x4 skills + agents into $hc ($($copied.Count) file(s))"
  # STATED, because it is the difference between this layout and the other two.
  # The guards are registered in a repo's .claude/settings.json, which this
  # method does not copy, and each hook is addressed as
  # $CLAUDE_PROJECT_DIR/.claude/hooks/... -- globally that resolves to whatever
  # repo the user has open, not to the toolkit. They are NOT installed here on
  # purpose: running them in every unrelated project, on the blocking hook path,
  # to guard X4 paths that are not present, is how a guard gets switched off.
  Write-Host ""
  Write-Host "  NOTE: this layout installs the SKILLS AND AGENTS ONLY."
  Write-Host "        The safety guards -- the command and file hooks, and the automatic"
  Write-Host "        backup before every edit -- are NOT installed by -Method global."
  Write-Host "        They are per-project: they live in a repo's .claude/settings.json"
  Write-Host "        and resolve their paths from that project. Use -Method in-game or"
  Write-Host "        -Method separate in a mod repo to get them there."
  # merge env into settings.json
  $sj = Join-Path $hc 'settings.json'
  $cfg = if (Test-Path -LiteralPath $sj) { Get-Content -Raw -LiteralPath $sj | ConvertFrom-Json } else { [pscustomobject]@{} }
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

# Normalised here and again after the in-arm Ask below: a destination can arrive
# either way, and a single up-front pass would miss the interactive one.
$Game    = Remove-TrailingSep $Game
$Profile = Remove-TrailingSep $Profile
$Toolkit = Remove-TrailingSep $Toolkit

switch ($Method) {
  'in-game'  {
    if (-not $Game) { throw 'in-game needs -Game' }
    $Toolkit = $Game
    Show-Target $Toolkit
    if (-not (Test-SameDir $SRC $Toolkit)) { Assert-Direction $Toolkit $GameNamed; Show-CopyPlan; Copy-Toolkit $Toolkit }
    Write-PathsEnv $Toolkit
  }
  'separate' {
    if (-not $Toolkit) { $Toolkit = $SRC }
    $Toolkit = Ask $Toolkit 'Toolkit folder' $Toolkit
    $Toolkit = Remove-TrailingSep $Toolkit
    Show-Target $Toolkit
    if (-not (Test-SameDir $SRC $Toolkit)) { Assert-Direction $Toolkit $ToolkitNamed; Show-CopyPlan; Copy-Toolkit $Toolkit }
    Write-PathsEnv $Toolkit
  }
  'global'   {
    if (-not $Toolkit) { $Toolkit = $SRC }
    Show-Target $Toolkit
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

$bash = Find-GitBash
$failed = @()
if ($bash) {
  Push-Location -LiteralPath $Toolkit
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
