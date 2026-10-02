# codex-entry.ps1 -- the fail-closed Windows entry for the toolkit's Codex hooks.
#
#   pwsh -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "<root>\.codex\hooks\codex-entry.ps1" <event>
#     || powershell ... (same)          (hooks.json commandWindows; payload on stdin)
#
# Why a wrapper at all (MEASURED on Codex 0.160.0): a hook that crashes, exits non-zero, prints
# unparseable output or a JSON key Codex does not know is "Failed" -- and the tool call RUNS.
# Only a parsed JSON deny blocks. So every path through this file prints a JSON verdict and
# exits 0: the adapter's own answer when it is well-formed, otherwise a fail-closed deny
# (PreToolUse) or an advisory (other events) that names the cause.
#
# Why PowerShell and not bash on Windows (MEASURED): Codex runs hooks through cmd.exe, and
# when Codex is launched from PowerShell `bash` resolves to the WSL stub, which cannot run the
# guard: the hook fails and the command runs. Runs on Windows PowerShell 5.1 and pwsh 7.
#
# Test-only knobs: X4_WRAPPER_TIMEOUT_S (default 50; 25 for session_start), and
# X4_NO_PYTHON_FALLBACK=1 (use X4_PYTHON only, so a missing interpreter is really missing).
# Never logs the environment: hooks inherit all of it, secrets included (MEASURED).

$ErrorActionPreference = 'Stop'
$script:emitted = $false
$script:hookEvent = if ($args.Count -ge 1) { [string]$args[0] } else { '' }

function Write-Verdict([string]$text) {
    if ($text.Length -gt 0) { [Console]::Out.Write($text) }
    [Console]::Out.Flush()
    $script:emitted = $true
}

function Write-Fail([string]$cause) {
    # The cause goes into a JSON string literal: keep an allowlist, never escape by hand.
    $safe = [regex]::Replace([string]$cause, '[^A-Za-z0-9 ._:/()=,+-]', '?')
    if ($safe.Length -gt 300) { $safe = $safe.Substring(0, 300) }
    switch ($script:hookEvent) {
        'session_start' {
            Write-Verdict ('{"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":"X4 GUARDS NOT LIVE: the toolkit session hook failed (' + $safe + '). Tell the user the X4 guards may not be running and ask them to run x4doctor."}}')
        }
        'post_tool_use' {
            Write-Verdict ('{"hookSpecificOutput":{"hookEventName":"PostToolUse","additionalContext":"X4 VALIDATION DID NOT RUN: the toolkit hook failed (' + $safe + ')."}}')
        }
        default {
            Write-Verdict ('{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"X4 GUARD INERT: the Codex hook wrapper failed (' + $safe + '). NOTHING was checked; this is a refusal, not a verdict. Ask the user to run x4doctor."}}')
        }
    }
}

function Find-Python {
    $cands = @()
    if ($env:X4_PYTHON) { $cands += , @($env:X4_PYTHON) }
    if ($env:X4_NO_PYTHON_FALLBACK -ne '1') { $cands += , @('py', '-3'); $cands += , @('python3'); $cands += , @('python') }
    foreach ($c in $cands) {
        $cmd = Get-Command $c[0] -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($cmd) { return , (@($cmd.Source) + @($c | Select-Object -Skip 1)) }
    }
    return $null
}

function Test-Body([string]$body) {
    # Exactly the shapes Codex honours: one top-level key hookSpecificOutput; only known inner
    # keys; a permissionDecision, if any, is "deny" (Codex fails OPEN on "ask" and "allow").
    try { $o = $body | ConvertFrom-Json } catch { return 'adapter output is not JSON' }
    if ($null -eq $o -or $o -isnot [psobject]) { return 'adapter output is not a JSON object' }
    $top = @($o.PSObject.Properties | ForEach-Object { $_.Name })
    if ($top.Count -ne 1 -or $top[0] -ne 'hookSpecificOutput') { return 'adapter output has keys other than hookSpecificOutput' }
    $h = $o.hookSpecificOutput
    if ($null -eq $h -or $h -isnot [psobject]) { return 'hookSpecificOutput is not an object' }
    $allowed = @('hookEventName', 'permissionDecision', 'permissionDecisionReason', 'additionalContext')
    foreach ($p in $h.PSObject.Properties) {
        if ($allowed -notcontains $p.Name) { return 'hookSpecificOutput has an unknown key' }
    }
    $pd = $h.PSObject.Properties['permissionDecision']
    if ($pd -and $pd.Value -ne 'deny') { return 'adapter answered a permissionDecision other than deny' }
    return $null
}

try {
    $stdinStream = [Console]::OpenStandardInput()
    $ms = New-Object System.IO.MemoryStream
    $stdinStream.CopyTo($ms)
    $payload = $ms.ToArray()

    $here = Split-Path -Parent $MyInvocation.MyCommand.Path
    $adapter = Join-Path $here 'codex_adapter.py'
    if (-not (Test-Path -LiteralPath $adapter -PathType Leaf)) { Write-Fail 'codex_adapter.py is missing'; exit 0 }
    $py = Find-Python
    if (-not $py) { Write-Fail 'no Python found (set X4_PYTHON)'; exit 0 }

    $limit = 50
    if ($script:hookEvent -eq 'session_start') { $limit = 25 }
    if ($env:X4_WRAPPER_TIMEOUT_S) { $limit = [int]$env:X4_WRAPPER_TIMEOUT_S }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $py[0]
    $argList = @($py | Select-Object -Skip 1) + @($adapter, $script:hookEvent)
    # Quote only what needs it: py.exe reads its RAW command line, and a quoted "-3" is not its
    # version switch (it went on to Python as an unknown option, exit 2 -- MEASURED).
    $psi.Arguments = ($argList | ForEach-Object {
            $a = [string]$_ -replace '"', ''
            if ($a -match '\s') { '"' + $a + '"' } else { $a }
        }) -join ' '
    $psi.UseShellExecute = $false
    $psi.RedirectStandardInput = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $psi.CreateNoWindow = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    $proc.StandardInput.BaseStream.Write($payload, 0, $payload.Length)
    $proc.StandardInput.Close()
    if (-not $proc.WaitForExit($limit * 1000)) {
        try { & taskkill.exe /T /F /PID $proc.Id 2>&1 | Out-Null } catch { }
        try { $proc.Kill() } catch { }
        Write-Fail "the adapter did not answer within $limit s"
        exit 0
    }
    $proc.WaitForExit()
    $out = $outTask.Result
    if ($proc.ExitCode -ne 0) { Write-Fail "the adapter exited $($proc.ExitCode)"; exit 0 }
    $lines = @(($out -replace "`r", '').TrimEnd("`n") -split "`n")
    if ($out.Trim().Length -eq 0) { Write-Fail 'the adapter printed nothing'; exit 0 }
    if ($lines.Count -ne 1) { Write-Fail "the adapter printed $($lines.Count) lines"; exit 0 }
    if (-not $lines[0].StartsWith('X4OK')) { Write-Fail 'the adapter output lacks the X4OK prefix'; exit 0 }
    $body = $lines[0].Substring(4).Trim()
    if ($body.Length -eq 0) { Write-Verdict ''; exit 0 }
    $bad = Test-Body $body
    if ($bad) { Write-Fail $bad; exit 0 }
    Write-Verdict $body
    exit 0
}
catch {
    if (-not $script:emitted) { Write-Fail ('wrapper error: ' + $_.Exception.GetType().Name) }
    exit 0
}
finally {
    if (-not $script:emitted) { Write-Fail 'the wrapper ended without a verdict' }
}
