# The cold ADAPTING exercise (once per release)

`ADAPTING.md` tells an agent the X4 AI Assistant Toolkit does not support how to write, prove
and upstream its own adapter. The committed toy adapter
(`tools/x4validate/tests/fixtures/toy_agent/`) proves that ONE cold reading of it worked, once.
Documentation drifts from the code it describes, so once per release a NEW cold reader repeats
the exercise against the release candidate.

- **When:** once per release, before the Track 1 release review closes
  (`docs/REVIEW-SCOPE.md`, "Release exercises").
- **Who:** a fresh subagent with no conversation context, model `sonnet`. Never the session that
  wrote or edited `ADAPTING.md` -- it cannot read the document cold.
- **What it gets:** a scratch folder (outside the repo) holding ONLY a copy of `ADAPTING.md`,
  and of `TOY-AGENT.md`, `toy_agent.py` and the `payloads/` folder from
  `tools/x4validate/tests/fixtures/toy_agent/`. NOT the committed toy adapter or its profile,
  NOT the Codex adapter, NOT the engine's source. It may RUN the toolkit's
  `.claude/hooks/x4guard.py` (that is what `ADAPTING.md` tells it to do), with the path given.

## The dispatch

Fill in `<SCRATCH>` and `<TOOLKIT>` (absolute paths), then send exactly the text between the
markers:

<!-- PROMPT -->
You are an AI agent connecting a coding agent called Toy Agent to a toolkit's safety guards.
Everything you know is in two files in <SCRATCH>: ADAPTING.md (the toolkit's guide for an agent
it does not support yet) and TOY-AGENT.md (Toy Agent's own hook documentation; toy_agent.py and
payloads/ are its harness and captured payloads). Read both completely before writing anything.
The toolkit is installed at <TOOLKIT>; run its tools from there exactly as ADAPTING.md says, and
do not read any other file in it.

Write, inside <SCRATCH>, an adapter for Toy Agent (one Python script, standard library only)
and its conformance profile (one JSON file), following ADAPTING.md. Then run the conformance
check ADAPTING.md section 5(a) gives, with your profile and adapter, and iterate until it exits
0 with no GAP line. Also measure Toy Agent's fail mode (ADAPTING.md section 1) with toy_agent.py,
and run the live canary of section 5(b) through toy_agent.py.

Report: the final exit code and the summary lines conformance printed; your fail-mode table;
the canary result and its control; and EVERY place ADAPTING.md was unclear, wrong or silent --
quote the sentence, say what you had to guess, and say what you guessed. An honest list of
gaps is the most valuable part of your report.
<!-- PROMPT -->

## Pass criterion

It passes when, with the subagent's own adapter **unedited by the dispatcher**,
`x4guard conformance --profile <its profile> -- python <its adapter>` exits 0 with no GAP line, and its canary blocks the decoy while the control write succeeds.
The dispatcher re-runs that command itself; the subagent's word is not the measurement.

## What a failure means

`ADAPTING.md` is wrong, stale or silent somewhere. Fix the DOCUMENT -- never the adapter, never
the corpus -- then run one more fresh cold subagent. Every gap the subagent reported is a
finding, even on a pass: fix the document or record why not.

## The record

Write `docs/superpowers/measurements/<date>-adapting-cold-test.md`: the date, the toolkit
commit, the model, each run's conformance exit code and bucket counts, every gap the subagent
reported and what was done about it, and whether the pass criterion held unedited.
