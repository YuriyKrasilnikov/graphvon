# Graphvon

Graphvon connects a source-edit assignment to its current requirement, proposed
method and applicable independent review. One repository-local skill guides the
semantic decision; a narrow Codex hook checks the declared native patch route.

The procedure is defined in
[graphvon-start-work](.agents/skills/graphvon-start-work/SKILL.md).
Requirements and the proposed implementation remain in the project's GitHub
Issues and PR descriptions.

## Install and launch

The initial profile uses Python 3.11 or later, Git, authenticated GitHub CLI
read access, and local Codex hooks. The runtime probe exercised Codex CLI
0.167.1. The Python package has no third-party runtime dependencies.

From this checkout in a Bash terminal, choose a virtual environment location
and install the console command:

```bash
read -r -p 'Virtual environment directory: ' GRAPHVON_ENV
python3 -m venv "$GRAPHVON_ENV"
. "$GRAPHVON_ENV/bin/activate"
python -m pip install .
graphvon-preflight --help
```

Keep the environment and private assignment records out of tracked content.
The package installs `graphvon-preflight`; the skill and `.codex/hooks.json`
are discovered from this checkout.

Follow the skill to prepare an admitted assignment. Then supply its absolute
record location through the launch environment, without putting the value in
tracked configuration or a command argument:

```bash
read -r -p 'Absolute private context file: ' GRAPHVON_CONTEXT
export GRAPHVON_CONTEXT
codex
```

The launching process must provide both the installed command on `PATH` and
`GRAPHVON_CONTEXT`. Restart by running `codex` again from this project terminal
and verify the actual new session's discovery and private context delivery.

Inspect the skill's discovery in the new session and invoke
`$graphvon-start-work`. Review project trust and the exact hook through Codex's
normal trust flow and `/hooks`; confirm that the hook is enabled and trusted.
Do not bypass trust. The supplied hook matches only `apply_patch`, uses a
10-second outer timeout, and invokes the installed command. The adapter shares
a 6-second internal deadline across its dependent checks.

## Private context and source observation

The version-1 context schema and its validation are canonical in
[contracts.py](src/graphvon/contracts.py). The skill explains who provisions
the record and when its source basis must be reconsidered. The locator is an
absolute path supplied only through `GRAPHVON_CONTEXT`; there is no implicit
record discovery.

For an implementation assignment, obtain the public basis with the read-only
command below, replacing the repository and native numbers with the actual
task:

```bash
graphvon-preflight snapshot --repository example/project --issue 2 --pull 4
```

Capture the JSON privately as the context's `implementation.basis`. The
snapshot reads public sources and grants no authority or review approval.
Use `graphvon.sources.load_context` to validate a completed context before
launch. Preparation uses the same context structure with its own admission
source and omits `implementation` entirely.

## Recover after an interrupted or restarted session

Follow the canonical skill's
[release and reconciliation procedure](.agents/skills/graphvon-start-work/SKILL.md#release-and-reconcile-the-assignment).
The steps below help inspect the evidence; they do not grant a new assignment.

1. Identify the surviving assignment through the explicit launch context and
   its admission references. Match each attempted patch to its tool result.
   Keep that projection unchanged while any result is outstanding. A lost
   response, timeout or error does not establish that no files changed.
2. Inspect the actual checkout effects. Use `git status --short` and
   `git diff` as starting points, then inspect the complete attempted path set:
   untracked additions, updates, deletions, both move endpoints, replacement
   targets and new parent directories. Native patch failure can leave partial
   effects; a diff alone omits untracked contents. Preserve the original call,
   result and observed effects in the coordinator's private evidence before
   cleanup or retry.
3. If completion or ownership remains unknown, withhold dependent writes and
   report the unresolved operation to the coordinator. Continue read-only
   reconciliation. Do not replay the patch, replace the projection or release
   a competing assignment to make the uncertainty disappear.
4. Once every operation has settled, the coordinator reconciles completion or
   explicit abandonment and preserves the evidence before retiring that
   generation. For remaining implementation work, read the current Issue,
   Draft description and public discussions with the snapshot command above
   and follow the
   skill's [implementation basis checks](.agents/skills/graphvon-start-work/SKILL.md#establish-the-implementation-basis)
   before releasing a fresh generation. Reuse applicable review only with a
   stated basis; source-read failure means unknown state.
   Separately admitted preparation follows the skill's
   [effect classification](.agents/skills/graphvon-start-work/SKILL.md#classify-the-intended-effect)
   using its own governing instruction, effect and exact paths. It does not
   require an implementation Issue, Draft PR, public-source snapshot or
   implementation review.
5. Launch again from the project terminal using the installation instructions
   above. Verify skill discovery, the exact enabled and trusted hook, and
   delivery of the intended private context in the new session. Reconcile a
   surviving unstarted assignment against current sources before continuing;
   its presence alone does not authorize a write.

A handled denial holds the affected write for reassessment. An absent,
disabled, untrusted or failed control also withholds guarded work. Preserve
the observed outcome and let the coordinator resolve the prerequisite; do not
switch writers or change the assignment to force a retry. The hook does not
enforce exclusive ownership, retirement or recovery ordering: those remain
coordinator responsibilities under the skill.

## Limits and checks

The guard checks the complete supported patch before allowing it. Its initial
profile covers local POSIX paths and refuses links, special files, undeclared
replacements and unsupported patch forms. Assignment ownership prevents
concurrent filesystem mutation; the hook provides no operating-system lock
or per-agent task binding.

Healthy denial and allow behavior were observed in the native runtime probe.
Malformed hook output, handler termination and timeout allowed the patch to
continue after runtime failure notices. These remain uncovered fail-open
conditions. The hook does not control arbitrary writers or make GitHub reads
atomic. Product integration, restart use and adoption require their own
observed checks.

Run the module checks without an installation or live mutation:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src python3 -m unittest discover -s tests
```

Module checks do not establish native hook discovery, trust, restart behavior
or semantic acceptance. Graphvon is distributed under the [MIT license](LICENSE).
