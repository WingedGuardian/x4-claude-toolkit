#requires -Version 5.1
# ps_translate.ps1 -- the PowerShell FRONT-END of the Bash guard (AUDIT-2026-09-24 HK-1).
#
# stdin : one PowerShell command string (UTF-8).
# stdout: one JSON object (UTF-8):
#     {"ok": true,  "command": "<an equivalent POSIX-shell command>"}
#     {"ok": false, "reason":  "<why nothing could be translated>"}
#
# WHY A TRANSLATOR AND NOT A SECOND RULE SET. The Bash guard's rules live in ONE place --
# hook_facts.py answers every predicate, protect-bash.sh holds the policy -- and every gap
# ever found in it lived in a place where a rule had been written twice. So PowerShell
# gets no rules of its own: this script only answers "what does this command DO to the
# filesystem", in the vocabulary those rules already understand, and hook_facts.py runs
# the result through the same pass as any Bash command.
#
#     Remove-Item -Recurse <p>        ->  rm -rf '<p>'
#     gci <p> -Filter *.x | ri        ->  find '<p>' -name '*.x' -delete
#     Move-Item a b / Copy-Item a b   ->  mv 'a' 'b' / cp -r 'a' 'b'
#     Set-Content / Out-File <p>      ->  : > '<p>'        (-Append: >>)
#     Add-Content <p>                 ->  : >> '<p>'
#     Clear-Content <p>               ->  truncate -s 0 '<p>'
#     cmd > <p> / cmd >> <p>          ->  ... > '<p>' / >> '<p>'
#     [IO.File]::Delete(<p>)          ->  rm -rf '<p>'  (and Write*/Append*/Move/Copy)
#     iex '<text>'                    ->  <text>, translated in turn
#     anything else (git, python ...) ->  the command, word for word
#
# THE PARSING IS POWERSHELL'S OWN (user decision 2026-09-25): Parser::ParseInput for the
# syntax tree and StaticParameterBinder for parameter binding, so aliases (`rm`, `ri`,
# `del`), unambiguous parameter prefixes (`-fo` for -Force) and positional binding are
# resolved exactly as PowerShell resolves them. A hand-rolled tokenizer is what every
# parser defect in the Bash half came from.
#
# A value this script cannot resolve -- a variable assigned at runtime, `$_`, an
# expression -- becomes a shell VARIABLE in the output ("${NAME}"), so it reaches the
# rules exactly as an unresolvable `$X` in a Bash command does: an unknown operand is
# not proof of safety for a delete, and `$env:X4_REFERENCE` still names its root.
#
# FAILS CLOSED: a command that does not PARSE is not translated ({"ok": false}), and the
# caller asks -- the same verdict protect-bash.sh gives a Bash command `bash -n` rejects.
using namespace System.Management.Automation.Language

$ErrorActionPreference = 'Stop'

function Out-Json($obj) {
    $bytes = [Text.Encoding]::UTF8.GetBytes(($obj | ConvertTo-Json -Compress -Depth 4))
    $out = [Console]::OpenStandardOutput()
    $out.Write($bytes, 0, $bytes.Length)
    $out.Flush()
}

# Unresolved values travel as  <SOH>NAME<STX>  inside a string and become "${NAME}" in
# the output. Control bytes cannot occur in a path.
$SOH = [char]1
$STX = [char]2
function UVar([string]$name) {
    $n = $name -replace '^env:', ''
    if ($n -eq '_' -or $n -eq 'PSItem') { $n = 'PS_PIPELINE_ITEM' }
    $n = $n -replace '[^A-Za-z0-9_]', '_'
    if ($n -notmatch '^[A-Za-z_]') { $n = 'PS_' + $n }
    return "$SOH$n$STX"
}

# Bash-quote one word, rendering unresolved parts as "${NAME}".
#
# Written the way a person would type it into Bash, NOT maximally quoted -- and that is
# a correctness requirement, not style. Several rules read the segment with QUOTED text
# blanked (a name inside a string literal is a mention, not an invocation), so
# `'uv' 'run' 'python' 'gates/corpus_sweep.py'` hid a foreground long job that
# `uv run python gates/corpus_sweep.py` reveals. Likewise a python payload containing
# apostrophes goes out in DOUBLE quotes, as it would be typed, because the durable-record
# rule looks for `open(...,'w')` in the text.
$BARE = '^[A-Za-z0-9_./:@%+=,-]+$'
function Lit([string]$p) {
    if ($p -match $BARE) { return $p }
    if (-not $p.Contains("'")) { return "'" + $p + "'" }
    if ($p -notmatch '["$`\\!]') { return '"' + $p + '"' }
    return "'" + $p.Replace("'", "'\''") + "'"
}
function Q([string]$s) {
    if ($null -eq $s) { $s = '' }
    $out = New-Object Text.StringBuilder
    $parts = $s -split "[$SOH$STX]"
    # -split on both markers alternates literal, name, literal, name ...
    for ($i = 0; $i -lt $parts.Count; $i++) {
        $p = $parts[$i]
        if ($i % 2 -eq 1) { [void]$out.Append('"${' + $p + '}"') }
        elseif ($p.Length -gt 0) { [void]$out.Append((Lit $p)) }
    }
    if ($out.Length -eq 0) { return "''" }
    return $out.ToString()
}

# ------------------------------------------------------------------ values
$script:Assign = @{}      # variable name (lower) -> string[] ; $null = ambiguous
$script:Tables = @{}      # variable name (lower) -> literal hashtable (key -> value AST); $null = ambiguous
$script:AssignAst = @{}   # variable name (lower) -> the one assigned AST; $null = ambiguous

# WHAT COULD NOT BE RESOLVED. A write or delete whose TARGET this script cannot name --
# an unresolvable splat, a method on an unknown object, Invoke-Expression of computed
# text -- is reported here rather than dropped, and the hook ASKS on it. Dropping it was
# the review finding: a construct the translator did not model reached NO rule, which is
# a narrowing step reporting success (AUDIT-2026-09-24 HK-1 follow-up).
$script:Unknown = New-Object Collections.Generic.List[string]
function Unknown([string]$why) { if (-not $script:Unknown.Contains($why)) { $script:Unknown.Add($why) } }
$script:Depth = 0

function Flatten($ast) {
    # An expression we do not evaluate: keep what it NAMES. `Join-Path $env:X4_REFERENCE
    # 'libraries'` becomes "${X4_REFERENCE}/libraries", which is what it means.
    $bits = @()
    foreach ($n in $ast.FindAll({ param($x) $x -is [StringConstantExpressionAst] -or $x -is [VariableExpressionAst] }, $true)) {
        if ($n -is [StringConstantExpressionAst]) {
            if ($n.Parent -is [CommandAst] -and $n.Parent.CommandElements[0] -eq $n) { continue }   # a command NAME
            $bits += $n.Value
        } else { $bits += (VarValue $n) | Select-Object -First 1 }
    }
    if ($bits.Count -eq 0) { return @(UVar 'PS_EXPR') }
    return @(($bits -join '/'))
}

function VarValue([VariableExpressionAst]$v) {
    $name = $v.VariablePath.UserPath
    $key = $name.ToLowerInvariant()
    if ($key -eq 'home') { return @(UVar 'HOME') }
    if ($key -eq 'null' -or $key -eq 'true' -or $key -eq 'false') { return @('') }
    if ($script:Assign.ContainsKey($key) -and $null -ne $script:Assign[$key]) { return $script:Assign[$key] }
    return @(UVar $name)
}

function Vals($ast) {
    if ($null -eq $ast) { return @() }
    if ($ast -is [StringConstantExpressionAst]) { return @($ast.Value) }
    if ($ast -is [ConstantExpressionAst]) { return @([string]$ast.Value) }
    if ($ast -is [VariableExpressionAst]) { return VarValue $ast }
    if ($ast -is [ExpandableStringExpressionAst]) {
        $s = $ast.Value
        foreach ($n in $ast.NestedExpressions) {
            $rep = if ($n -is [VariableExpressionAst]) { (VarValue $n) | Select-Object -First 1 } else { (Flatten $n) | Select-Object -First 1 }
            # NestedExpressions carry their own source text; the Value holds it verbatim.
            $s = $s.Replace($n.Extent.Text, [string]$rep)
        }
        return @($s)
    }
    if ($ast -is [ArrayLiteralAst]) { $r = @(); foreach ($e in $ast.Elements) { $r += Vals $e }; return $r }
    if ($ast -is [CommandExpressionAst]) { return Vals $ast.Expression }
    if ($ast -is [ParenExpressionAst] -or $ast -is [ArrayExpressionAst]) {
        $inner = if ($ast -is [ParenExpressionAst]) { $ast.Pipeline } else { $ast.SubExpression }
        if ($inner -is [PipelineAst] -and $inner.PipelineElements.Count -eq 1 -and $inner.PipelineElements[0] -is [CommandExpressionAst]) {
            return Vals $inner.PipelineElements[0].Expression
        }
        return Flatten $ast
    }
    if ($ast -is [BinaryExpressionAst] -and $ast.Operator -eq [TokenKind]::Plus) {
        $l = @(Vals $ast.Left); $r = @(Vals $ast.Right)
        if ($l.Count -eq 1 -and $r.Count -eq 1) { return @($l[0] + $r[0]) }
    }
    return Flatten $ast
}

# ------------------------------------------------------------------ commands
$ALIASES = @{
    'rm' = 'remove-item'; 'del' = 'remove-item'; 'erase' = 'remove-item'; 'ri' = 'remove-item'
    'rd' = 'remove-item'; 'rmdir' = 'remove-item'
    'mv' = 'move-item'; 'move' = 'move-item'; 'mi' = 'move-item'
    'cp' = 'copy-item'; 'copy' = 'copy-item'; 'cpi' = 'copy-item'
    'ren' = 'rename-item'; 'rni' = 'rename-item'
    'sc' = 'set-content'; 'ac' = 'add-content'; 'clc' = 'clear-content'; 'ni' = 'new-item'
    'md' = 'new-item'; 'mkdir' = 'new-item'
    'cd' = 'set-location'; 'sl' = 'set-location'; 'chdir' = 'set-location'; 'pushd' = 'push-location'
    'gci' = 'get-childitem'; 'ls' = 'get-childitem'; 'dir' = 'get-childitem'; 'gi' = 'get-item'
    'sls' = 'select-string'; 'iex' = 'invoke-expression'; 'saps' = 'start-process'; 'start' = 'start-process'
    'tee' = 'tee-object'; 'where' = 'where-object'; '?' = 'where-object'; '%' = 'foreach-object'
    'foreach' = 'foreach-object'; 'select' = 'select-object'; 'sort' = 'sort-object'
}

function Canon([string]$name) {
    if (-not $name) { return '' }
    $n = [IO.Path]::GetFileName($name.Replace('\', '/')).ToLowerInvariant()
    if ($n -like '*.exe') { $n = $n.Substring(0, $n.Length - 4) }
    if ($ALIASES.ContainsKey($n)) { return $ALIASES[$n] }
    return $n
}

# A SPLAT (`Remove-Item @p`) is invisible to StaticParameterBinder: it binds nothing, so the
# delete had no path and reached no rule. A literal hashtable assigned in the same command
# is read here as if its keys were written as parameters. $script:SplatFor pins the table
# to the binding of the command that carries the splat, so an upstream Get-ChildItem bound
# in Scan-Upstream never reads the downstream command's splat.
$script:SplatNow = @{}
$script:SplatFor = $null
$SPLAT_ALIASES = @{ 'pspath' = 'literalpath'; 'lp' = 'literalpath'; 'fullname' = 'literalpath' }
function Bound($binding, [string[]]$names) {
    if ($null -ne $binding) {
        foreach ($n in $names) {
            if ($binding.BoundParameters.ContainsKey($n)) { return $binding.BoundParameters[$n] }
        }
    }
    if ($null -ne $script:SplatFor -and [object]::ReferenceEquals($binding, $script:SplatFor)) {
        foreach ($n in $names) {
            $want = $n.ToLowerInvariant()
            foreach ($k in $script:SplatNow.Keys) {
                $kk = if ($SPLAT_ALIASES.ContainsKey($k)) { $SPLAT_ALIASES[$k] } else { $k }
                if ($kk -eq $want) { return [pscustomobject]@{ Value = $script:SplatNow[$k]; ConstantValue = $null } }
            }
        }
    }
    return $null
}
function BVals($binding, [string[]]$names) {
    $b = Bound $binding $names
    if ($null -eq $b) { return @() }
    if ($null -ne $b.Value) { return @(Vals $b.Value) }
    if ($null -ne $b.ConstantValue) { return @([string]$b.ConstantValue) }
    return @()
}
function IsSet($binding, [string]$name) {
    $b = Bound $binding @($name)
    if ($null -eq $b) { return $false }
    if ($b.ConstantValue -is [bool]) { return $b.ConstantValue }
    if ($b.Value -is [VariableExpressionAst] -and $b.Value.VariablePath.UserPath -eq 'false') { return $false }
    return $true
}

$SOURCES = @('get-childitem', 'get-item')
$NARROWERS = @('where-object', 'select-object', 'select-string')

# What arrives on this command's pipeline input: $null (nothing), or
# @{known; paths; filter; recurse; narrowed; children}.
function Upstream([CommandAst]$c) {
    $node = $c
    while ($true) {
        $pipe = $node.Parent
        if ($pipe -is [PipelineAst]) {
            $idx = [array]::IndexOf(@($pipe.PipelineElements), $node)
            if ($idx -gt 0) { return (Scan-Upstream $pipe $idx) }
        }
        # Not fed directly. Inside a script block handed to ForEach-Object/Where-Object,
        # `$_` is THAT command's pipeline item, so look upstream of it instead.
        $outer = $node.Parent
        while ($null -ne $outer -and $outer -isnot [CommandAst]) { $outer = $outer.Parent }
        if ($null -eq $outer) { return $null }
        if ((Canon $outer.GetCommandName()) -notin @('foreach-object', 'where-object')) { return $null }
        $node = $outer
    }
}

function Scan-Upstream([PipelineAst]$pipe, [int]$idx) {
    $narrowed = $false
    for ($i = $idx - 1; $i -ge 0; $i--) {
        $e = $pipe.PipelineElements[$i]
        if ($e -isnot [CommandAst]) { break }
        $cn = Canon $e.GetCommandName()
        if ($NARROWERS -contains $cn) { $narrowed = $true; continue }
        if ($cn -eq 'sort-object' -or $cn -eq 'foreach-object') { continue }
        if ($SOURCES -contains $cn) {
            $b = $null
            try { $b = [StaticParameterBinder]::BindCommand($e, $true) } catch { $b = $null }
            $p = @(BVals $b @('Path', 'LiteralPath'))
            if ($p.Count -eq 0) { $p = @('.') }
            $f = @(BVals $b @('Filter', 'Include')) | Select-Object -First 1
            return @{ known = $true; paths = $p; filter = $f; narrowed = $narrowed
                      recurse = (IsSet $b 'Recurse'); children = ($cn -eq 'get-childitem') }
        }
        break
    }
    return @{ known = $false }
}

function IsPipelineItem($ast) {
    if ($null -eq $ast) { return $false }
    foreach ($v in $ast.FindAll({ param($x) $x -is [VariableExpressionAst] }, $true)) {
        if (@('_', 'psitem') -contains $v.VariablePath.UserPath.ToLowerInvariant()) { return $true }
    }
    return $false
}

# The paths a destructive cmdlet acts on, seeing through the pipeline where it must.
# Returns @{paths; scoped} -- `scoped` = only SOME entries under each path (a filter).
function Targets([CommandAst]$c, $binding, [string[]]$names) {
    $b = Bound $binding $names
    $viaItem = ($null -ne $b) -and (IsPipelineItem $b.Value)
    if ($null -ne $b -and -not $viaItem) { return @{ paths = @(BVals $binding $names); scoped = $false } }
    $up = Upstream $c
    if ($null -eq $up) {
        # A writing cmdlet with NO resolvable target is not a no-op to the guard: it is
        # an UNKNOWN target (a splat, a runtime-only value), and the hook asks.
        Unknown "$($c.GetCommandName()): no target path could be resolved"
        return @{ paths = @(); scoped = $false }
    }
    if (-not $up.known) { return @{ paths = @(UVar 'PS_PIPELINE_INPUT'); scoped = $false } }
    $pat = $up.filter
    if (-not $pat -and $up.narrowed) { $pat = 'PS_FILTERED' }
    $paths = $up.paths
    # Get-ChildItem yields the entries UNDER each path, never the path itself, so an
    # unfiltered `gci <p> | Remove-Item` is `rm -rf <p>/<each child>` -- judged the way
    # the Bash rules already judge a delete of something inside <p>.
    if (-not $pat -and $up.children) {
        $paths = @($paths | ForEach-Object { $_.TrimEnd('/', '\') + '/' + (UVar 'PS_CHILD') })
    }
    return @{ paths = $paths; scoped = [bool]$pat; filter = $pat; recurse = $up.recurse }
}

function Words([string[]]$ws) { return (($ws | ForEach-Object { Q $_ }) -join ' ') }

function Redirs([CommandBaseAst]$c) {
    $r = ''
    foreach ($x in $c.Redirections) {
        if ($x -isnot [FileRedirectionAst]) { continue }
        $loc = $x.Location
        if ($loc -is [VariableExpressionAst] -and $loc.VariablePath.UserPath -eq 'null') { continue }
        $t = @(Vals $loc) | Select-Object -First 1
        $op = if ($x.Append) { '>>' } else { '>' }
        $r += " $op " + (Q $t)
    }
    return $r
}

$WRITERS = @('remove-item', 'move-item', 'copy-item', 'rename-item', 'set-content', 'out-file',
             'export-csv', 'export-clixml', 'tee-object', 'add-content', 'clear-content', 'new-item')

function Translate-Command([CommandAst]$c) {
    $lines = New-Object Collections.Generic.List[string]
    $raw = $c.GetCommandName()
    if ($null -eq $raw) {
        $first = $c.CommandElements[0]
        if ($first -is [ScriptBlockExpressionAst]) { return $lines }   # its body is walked on its own
        $raw = @(Vals $first) | Select-Object -First 1
    }
    $name = Canon $raw
    $binding = $null
    try { $binding = [StaticParameterBinder]::BindCommand($c, $true) } catch { $binding = $null }
    if ($null -eq $binding) { $binding = [pscustomobject]@{ BoundParameters = @{} } }
    $red = Redirs $c
    # Splats on this command: a literal hashtable is resolved; anything else leaves the
    # parameters UNKNOWN.
    $script:SplatNow = @{}; $script:SplatFor = $binding
    $splatUnknown = ''
    foreach ($e in $c.CommandElements) {
        if ($e -is [VariableExpressionAst] -and $e.Splatted) {
            $key = $e.VariablePath.UserPath.ToLowerInvariant()
            if ($script:Tables.ContainsKey($key) -and $null -ne $script:Tables[$key]) {
                foreach ($k in $script:Tables[$key].Keys) { $script:SplatNow[$k] = $script:Tables[$key][$k] }
            } else { $splatUnknown = $e.VariablePath.UserPath }
        }
    }
    if ($WRITERS -contains $name) {
        if ($splatUnknown) { Unknown "$raw @${splatUnknown}: splatted parameters that cannot be resolved" }
    }
    switch ($name) {
        'remove-item' {
            $t = Targets $c $binding @('Path', 'LiteralPath')
            $pat = @(BVals $binding @('Filter', 'Include')) | Select-Object -First 1
            if ($pat -and $pat -ne '*' -and $pat -ne '*.*') { $t.scoped = $true; $t.filter = $pat }
            foreach ($p in $t.paths) {
                if ($t.scoped) { $lines.Add("find $(Q $p) -name $(Q $t.filter) -delete$red") }
                else { $lines.Add("rm -rf $(Q $p)$red") }
            }
            return $lines
        }
        { $_ -in 'move-item', 'copy-item' } {
            $t = Targets $c $binding @('Path', 'LiteralPath')
            $dst = @(BVals $binding @('Destination')) | Select-Object -First 1
            if (-not $dst) { $dst = '.' }
            $verb = if ($name -eq 'move-item') { 'mv' } else { 'cp -r' }
            if ($t.paths.Count) { $lines.Add("$verb $(Words $t.paths) $(Q $dst)$red") }
            return $lines
        }
        'rename-item' {
            $t = Targets $c $binding @('Path', 'LiteralPath')
            $nn = @(BVals $binding @('NewName')) | Select-Object -First 1
            foreach ($p in $t.paths) {
                $dst = $nn
                if ($nn -and $nn -notmatch '[/\\]') {
                    $cut = [Math]::Max($p.LastIndexOf('/'), $p.LastIndexOf('\'))
                    $dst = if ($cut -ge 0) { $p.Substring(0, $cut + 1) + $nn } else { $nn }
                }
                $lines.Add("mv $(Q $p) $(Q $dst)$red")
            }
            return $lines
        }
        { $_ -in 'set-content', 'out-file', 'export-csv', 'export-clixml', 'tee-object', 'add-content' } {
            $t = Targets $c $binding @('Path', 'LiteralPath', 'FilePath')
            $op = if ($name -eq 'add-content' -or (IsSet $binding 'Append')) { '>>' } else { '>' }
            foreach ($p in $t.paths) { $lines.Add(": $op $(Q $p)$red") }
            return $lines
        }
        'clear-content' {
            $t = Targets $c $binding @('Path', 'LiteralPath')
            foreach ($p in $t.paths) { $lines.Add("truncate -s 0 $(Q $p)$red") }
            return $lines
        }
        'new-item' {
            $paths = @(BVals $binding @('Path'))
            if ($paths.Count -eq 0) { $paths = @('.') }
            $nm = @(BVals $binding @('Name')) | Select-Object -First 1
            $type = (@(BVals $binding @('ItemType')) | Select-Object -First 1)
            $isDir = ([IO.Path]::GetFileName($raw.Replace('\', '/')).ToLowerInvariant() -in 'md', 'mkdir') -or ($type -and $type.ToLowerInvariant() -eq 'directory')
            foreach ($p in $paths) {
                $full = if ($nm) { $p.TrimEnd('/', '\') + '/' + $nm } else { $p }
                if ($isDir) { $lines.Add("mkdir -p $(Q $full)$red") }
                elseif (IsSet $binding 'Force') { $lines.Add(": > $(Q $full)$red") }
                else { $lines.Add(": >> $(Q $full)$red") }
            }
            return $lines
        }
        { $_ -in 'set-location', 'push-location' } {
            $p = @(BVals $binding @('Path', 'LiteralPath')) | Select-Object -First 1
            if ($p) { $lines.Add("cd $(Q $p)") }
            return $lines
        }
        'select-string' {
            $pat = @(BVals $binding @('Pattern')) | Select-Object -First 1
            $paths = @(BVals $binding @('Path', 'LiteralPath'))
            $flag = ''
            if ($paths.Count -eq 0) {
                $up = Upstream $c
                if ($null -ne $up -and $up.known) { $paths = $up.paths; if ($up.recurse) { $flag = ' -r' } }
            }
            $lines.Add("grep$flag -e $(Q $pat) $(Words $paths)$red")
            return $lines
        }
        'invoke-expression' {
            $txt = @(BVals $binding @('Command')) | Select-Object -First 1
            if ($txt -and $txt -notmatch "[$SOH$STX]" -and $script:Depth -lt 4) {
                $script:Depth++
                try { foreach ($l in (Translate-Text $txt)) { $lines.Add($l) } } finally { $script:Depth-- }
            }
            return $lines
        }
        'start-process' {
            $fp = @(BVals $binding @('FilePath')) | Select-Object -First 1
            $al = @(BVals $binding @('ArgumentList'))
            # Start-Process JOINS its argument list into one command line.
            $words = @($fp)
            foreach ($m in [regex]::Matches(($al -join ' '), '"([^"]*)"|(\S+)')) {
                $words += if ($m.Groups[1].Success) { $m.Groups[1].Value } else { $m.Groups[2].Value }
            }
            if ($fp) { $lines.Add((Words $words) + $red) }
            return $lines
        }
    }
    # Anything else -- a native program (git, python, bash -c, cmd /c, pwsh -c) or a
    # harmless cmdlet -- goes through WORD FOR WORD, so the Bash rule set sees it exactly
    # as it would have seen it typed into Bash.
    $w = New-Object Collections.Generic.List[string]
    $w.Add((Q $raw))
    for ($i = 1; $i -lt $c.CommandElements.Count; $i++) {
        $e = $c.CommandElements[$i]
        if ($e -is [CommandParameterAst]) {
            # A parameter name is an identifier, so it goes out BARE: a quoted '-A' is an
            # operand to the rules, not a flag, and `git add -A` must still read as one.
            $pn = '-' + $e.ParameterName
            $w.Add($(if ($pn -match '^-[A-Za-z0-9_?-]+$') { $pn } else { Q $pn }))
            if ($null -ne $e.Argument) { foreach ($v in (Vals $e.Argument)) { $w.Add((Q $v)) } }
        } else { foreach ($v in (Vals $e)) { $w.Add((Q $v)) } }
    }
    $lines.Add(($w -join ' ') + $red)
    return $lines
}

# ------------------------------------------------------------------ methods
# File-system METHODS, static and instance (AUDIT-2026-09-24 HK-1 review item 2). Only
# [IO.File]/[IO.Directory] statics were mapped, so `(Get-Item <p>).Delete()`, a
# `$_.Delete()` over gci output, [FileInfo]/[DirectoryInfo] instances, `[Directory]` under
# `using namespace System.IO` and VisualBasic's FileSystem reached no rule.
#
# Types are matched on the LAST segment of their name, so a `using namespace` spelling and
# the full one agree. A static on any OTHER type is not a file operation -- `[string]::Copy`
# and `[array]::Copy` are ordinary.
$FILE_STATIC_TAILS = @('file', 'directory', 'filesystem')
$FILE_OBJECT_TAILS = @('fileinfo', 'directoryinfo', 'filesysteminfo')
#: Instance members that are a file operation on ANY receiver we cannot identify: an
#: unresolved receiver with one of these is UNKNOWN (ask), never "not a file".
$STRONG_MEMBERS = @('delete', 'moveto', 'encrypt', 'decrypt', 'create', 'createtext',
                    'appendtext', 'openwrite', 'createsubdirectory', 'setaccesscontrol')
#: Members that are ALSO ordinary on strings/arrays/streams ('abc'.Replace, $a.CopyTo):
#: a file operation only when the receiver is identified as a file object.
$AMBIG_MEMBERS = @('copyto', 'replace', 'open')

function TypeTail($typeName) {
    $n = [string]$typeName
    return $n.Split('.')[-1].ToLowerInvariant()
}

function MemberName($m) { return ($m.Member.Extent.Text).Trim("'", '"').ToLowerInvariant() }

function FirstVal($ast) { return @(Vals $ast) | Select-Object -First 1 }

function IsResolved([string]$v) { return ($null -ne $v) -and ($v -notmatch "[$SOH$STX]") }

# What a receiver IS: @{ kind = 'file'; paths; filter } | @{ kind = 'notfile' } |
# @{ kind = 'unknown' }.
function Resolve-FileObject($e, [int]$depth = 0) {
    if ($depth -gt 6 -or $null -eq $e) { return @{ kind = 'unknown' } }
    if ($e -is [StringConstantExpressionAst] -or $e -is [ExpandableStringExpressionAst] -or
        $e -is [ConstantExpressionAst] -or $e -is [ArrayLiteralAst] -or $e -is [HashtableAst]) {
        return @{ kind = 'notfile' }
    }
    if ($e -is [ParenExpressionAst] -or $e -is [SubExpressionAst]) {
        $p = if ($e -is [ParenExpressionAst]) { $e.Pipeline } else { $e.SubExpression }
        if ($p -is [StatementBlockAst] -and $p.Statements.Count -eq 1) { $p = $p.Statements[0] }
        if ($p -is [PipelineAst] -and $p.PipelineElements.Count -ge 1) {
            $last = $p.PipelineElements[$p.PipelineElements.Count - 1]
            if ($last -is [CommandExpressionAst] -and $p.PipelineElements.Count -eq 1) {
                return Resolve-FileObject $last.Expression ($depth + 1)
            }
            if ($last -is [CommandAst]) { return Resolve-Producer $last $p ($depth + 1) }
        }
        return @{ kind = 'unknown' }
    }
    if ($e -is [ConvertExpressionAst]) {
        if ($FILE_OBJECT_TAILS -contains (TypeTail $e.Type.TypeName.FullName)) {
            $v = FirstVal $e.Child
            return @{ kind = 'file'; paths = @($v) }
        }
        return Resolve-FileObject $e.Child ($depth + 1)
    }
    if ($e -is [InvokeMemberExpressionAst] -and $e.Static -and $e.Expression -is [TypeExpressionAst] -and
        (MemberName $e) -eq 'new' -and $FILE_OBJECT_TAILS -contains (TypeTail $e.Expression.TypeName.FullName)) {
        if ($e.Arguments.Count -ge 1) { return @{ kind = 'file'; paths = @(FirstVal $e.Arguments[0]) } }
        return @{ kind = 'unknown' }
    }
    if ($e -is [VariableExpressionAst]) {
        $n = $e.VariablePath.UserPath.ToLowerInvariant()
        if ($n -eq '_' -or $n -eq 'psitem') {
            # The pipeline item of the ForEach-Object/Where-Object this sits in.
            $outer = $e.Parent
            while ($null -ne $outer -and $outer -isnot [CommandAst]) { $outer = $outer.Parent }
            if ($null -eq $outer) { return @{ kind = 'unknown' } }
            $up = Upstream $outer
            if ($null -eq $up) {
                $pipe = $outer.Parent
                if ($pipe -is [PipelineAst]) {
                    $idx = [array]::IndexOf(@($pipe.PipelineElements), $outer)
                    if ($idx -gt 0) { $up = Scan-Upstream $pipe $idx }
                }
            }
            if ($null -eq $up -or -not $up.known) { return @{ kind = 'unknown' } }
            return (FromSource $up)
        }
        if ($script:AssignAst.ContainsKey($n) -and $null -ne $script:AssignAst[$n]) {
            return Resolve-FileObject $script:AssignAst[$n] ($depth + 1)
        }
        return @{ kind = 'unknown' }
    }
    if ($e -is [CommandExpressionAst]) { return Resolve-FileObject $e.Expression ($depth + 1) }
    if ($e -is [PipelineAst]) {
        $last = $e.PipelineElements[$e.PipelineElements.Count - 1]
        if ($last -is [CommandAst]) { return Resolve-Producer $last $e ($depth + 1) }
        if ($last -is [CommandExpressionAst]) { return Resolve-FileObject $last.Expression ($depth + 1) }
    }
    return @{ kind = 'unknown' }
}

# The objects a Get-Item/Get-ChildItem/New-Object at the end of a pipeline produce.
function Resolve-Producer([CommandAst]$cmd, $pipe, [int]$depth) {
    $cn = Canon $cmd.GetCommandName()
    $b = $null
    try { $b = [StaticParameterBinder]::BindCommand($cmd, $true) } catch { $b = $null }
    if ($SOURCES -contains $cn) {
        if ($null -eq $b) { return @{ kind = 'unknown' } }
        $p = @(BVals $b @('Path', 'LiteralPath'))
        if ($p.Count -eq 0) { $p = @('.') }
        $f = @(BVals $b @('Filter', 'Include')) | Select-Object -First 1
        return (FromSource @{ known = $true; paths = $p; filter = $f; children = ($cn -eq 'get-childitem') })
    }
    if ($NARROWERS -contains $cn -or $cn -eq 'sort-object') {
        $idx = [array]::IndexOf(@($pipe.PipelineElements), $cmd)
        if ($idx -gt 0) {
            $up = Scan-Upstream $pipe $idx
            if ($null -ne $up -and $up.known) {
                $r = FromSource $up
                if (-not $r.filter) { $r.filter = 'PS_FILTERED' }
                return $r
            }
        }
        return @{ kind = 'unknown' }
    }
    if ($cn -eq 'new-object' -and $null -ne $b) {
        $t = @(BVals $b @('TypeName')) | Select-Object -First 1
        if ($t -and $FILE_OBJECT_TAILS -contains (TypeTail $t)) {
            $al = @(BVals $b @('ArgumentList'))
            if ($al.Count -ge 1) { return @{ kind = 'file'; paths = @($al[0]) } }
            return @{ kind = 'unknown' }
        }
        if ($t) { return @{ kind = 'notfile' } }
    }
    return @{ kind = 'unknown' }
}

function FromSource($up) {
    $paths = $up.paths
    $filter = $up.filter
    if (-not $filter -and $up.narrowed) { $filter = 'PS_FILTERED' }
    if (-not $filter -and $up.children) {
        $paths = @($paths | ForEach-Object { $_.TrimEnd('/', '\') + '/' + (UVar 'PS_CHILD') })
    }
    return @{ kind = 'file'; paths = $paths; filter = $filter }
}

function MemberLines([string]$member, $paths, [string]$filter, $args2) {
    $out = @()
    foreach ($p in $paths) {
        if (-not (IsResolved $p) -and $p -notmatch 'PS_CHILD') {
            Unknown ".${member}() on an object whose path cannot be resolved"
            continue
        }
        switch -regex ($member) {
            '^delete$' {
                if ($filter) { $out += "find $(Q $p) -name $(Q $filter) -delete" } else { $out += "rm -rf $(Q $p)" }
            }
            '^(moveto|replace)$' {
                $d = $args2 | Select-Object -First 1
                if (IsResolved $d) { $out += "mv $(Q $p) $(Q $d)" } else { Unknown ".${member}() to a destination that cannot be resolved" }
            }
            '^copyto$' {
                $d = $args2 | Select-Object -First 1
                if (IsResolved $d) { $out += "cp -r $(Q $p) $(Q $d)" } else { Unknown ".${member}() to a destination that cannot be resolved" }
            }
            '^(create|createtext|openwrite|open)$' { $out += ": > $(Q $p)" }
            '^(appendtext|encrypt|decrypt|setaccesscontrol)$' { $out += ": >> $(Q $p)" }
            '^createsubdirectory$' {
                $d = $args2 | Select-Object -First 1
                $out += ": >> $(Q ($p.TrimEnd('/', '\') + '/' + $d))"
            }
        }
    }
    return $out
}

function Translate-Member([InvokeMemberExpressionAst]$m) {
    $member = MemberName $m
    $a = @(); foreach ($x in $m.Arguments) { $a += FirstVal $x }
    if ($m.Static) {
        if ($m.Expression -isnot [TypeExpressionAst]) { return @() }
        if ($FILE_STATIC_TAILS -notcontains (TypeTail $m.Expression.TypeName.FullName)) { return @() }
        $kind = switch -regex ($member) {
            '^(delete|deletefile|deletedirectory)$' { 'rm' ; break }
            '^(write|create|openwrite)'              { 'trunc' ; break }
            '^append'                                { 'append' ; break }
            '^(encrypt|decrypt|setattributes|setlastwritetime|setcreationtime|setlastaccesstime|setaccesscontrol)' { 'append' ; break }
            '^(move|movefile|movedirectory)$'        { 'mv' ; break }
            '^replace$'                              { 'replace' ; break }
            '^(copy|copyfile|copydirectory)$'        { 'cp' ; break }
            default                                  { '' }
        }
        if (-not $kind) { return @() }
        $need = if ($kind -in 'mv', 'cp', 'replace') { 2 } else { 1 }
        if ($a.Count -lt $need -or -not (IsResolved $a[0]) -or ($need -eq 2 -and -not (IsResolved $a[1]))) {
            Unknown "[$($m.Expression.TypeName.FullName)]::$($m.Member.Extent.Text)() on a path that cannot be resolved"
            return @()
        }
        switch ($kind) {
            'rm'      { return @("rm -rf $(Q $a[0])") }
            'trunc'   { return @(": > $(Q $a[0])") }
            'append'  { return @(": >> $(Q $a[0])") }
            'mv'      { return @("mv $(Q $a[0]) $(Q $a[1])") }
            'cp'      { return @("cp -r $(Q $a[0]) $(Q $a[1])") }
            # File.Replace(source, destination, backup): destination is overwritten by source
            'replace' { return @("mv $(Q $a[0]) $(Q $a[1])") }
        }
        return @()
    }
    $strong = $STRONG_MEMBERS -contains $member
    $ambig = $AMBIG_MEMBERS -contains $member
    if (-not ($strong -or $ambig)) { return @() }
    $obj = Resolve-FileObject $m.Expression
    if ($obj.kind -eq 'file') { return @(MemberLines $member $obj.paths $obj.filter $a) }
    if ($obj.kind -eq 'unknown' -and $strong) {
        Unknown "$($m.Extent.Text): a file-system method on an object the guard cannot identify"
    }
    return @()
}

function Collect-Assignments($ast) {
    foreach ($as in $ast.FindAll({ param($x) $x -is [AssignmentStatementAst] }, $true)) {
        if ($as.Left -isnot [VariableExpressionAst] -or $as.Operator -ne [TokenKind]::Equals) { continue }
        $key = $as.Left.VariablePath.UserPath.ToLowerInvariant()
        $val = $null
        if ($as.Right -is [CommandExpressionAst]) { $val = @(Vals $as.Right.Expression) }
        # A literal hashtable, for splatting: key -> value AST. Anything else assigned to
        # the same name makes it ambiguous ($null), never "the last one wins".
        $tbl = $null
        if ($as.Right -is [CommandExpressionAst] -and $as.Right.Expression -is [HashtableAst]) {
            $tbl = @{}
            foreach ($kv in $as.Right.Expression.KeyValuePairs) {
                $kn = @(Vals $kv.Item1) | Select-Object -First 1
                $v = $kv.Item2
                if ($v -is [PipelineAst] -and $v.PipelineElements.Count -eq 1 -and $v.PipelineElements[0] -is [CommandExpressionAst]) {
                    $v = $v.PipelineElements[0].Expression
                }
                if ($kn) { $tbl[$kn.ToLowerInvariant()] = $v }
            }
        }
        if ($script:AssignAst.ContainsKey($key)) { $script:AssignAst[$key] = $null }
        else { $script:AssignAst[$key] = $as.Right }
        if ($script:Tables.ContainsKey($key)) { $script:Tables[$key] = $null }
        else { $script:Tables[$key] = $tbl }
        if ($script:Assign.ContainsKey($key)) {
            $old = $script:Assign[$key]
            if ($null -eq $old -or $null -eq $val -or (($old -join "`n") -ne ($val -join "`n"))) { $script:Assign[$key] = $null }
        } else { $script:Assign[$key] = $val }
    }
}

function Translate-Text([string]$src) {
    $toks = $null; $errs = $null
    $ast = [Parser]::ParseInput($src, [ref]$toks, [ref]$errs)
    if ($errs.Count -gt 0) {
        $msg = ($errs | Select-Object -First 3 | ForEach-Object { $_.Message }) -join ' | '
        throw [FormatException]::new("does not parse as PowerShell: $msg")
    }
    Collect-Assignments $ast
    $out = New-Object Collections.Generic.List[string]
    $nodes = $ast.FindAll({ param($x) $x -is [CommandAst] -or $x -is [InvokeMemberExpressionAst] }, $true)
    foreach ($n in ($nodes | Sort-Object { $_.Extent.StartOffset })) {
        $got = if ($n -is [CommandAst]) { Translate-Command $n } else { Translate-Member $n }
        foreach ($l in $got) { if ($l) { $out.Add($l) } }
    }
    # A redirect on a bare expression (`'x' > <p>`) has no CommandAst to ride on.
    foreach ($e in $ast.FindAll({ param($x) $x -is [CommandExpressionAst] -and $x.Redirections.Count -gt 0 }, $true)) {
        $r = Redirs $e
        if ($r) { $out.Add(':' + $r) }
    }
    return $out
}

try {
    $stdin = [Console]::OpenStandardInput()
    $ms = New-Object IO.MemoryStream
    $stdin.CopyTo($ms)
    $src = [Text.Encoding]::UTF8.GetString($ms.ToArray())
    if ($src.Length -gt 0 -and $src[0] -eq [char]0xFEFF) { $src = $src.Substring(1) }
    $lines = Translate-Text $src
    Out-Json @{ ok = $true; command = ($lines -join "`n"); unknown = @($script:Unknown) }
} catch [FormatException] {
    Out-Json @{ ok = $false; reason = $_.Exception.Message }
} catch {
    Out-Json @{ ok = $false; reason = ("the translator failed: " + $_.Exception.Message) }
}
exit 0
