# Graphvon

Graphvon connects a source-edit assignment to its current requirement, proposed
method and applicable independent review. One repository-local skill guides the
semantic decision; a narrow Codex hook checks the declared native patch route.

The procedure is defined in
[graphvon-start-work](.agents/skills/graphvon-start-work/SKILL.md).
Requirements and the proposed implementation remain in the project's GitHub
Issues and PR descriptions.

## One-time installation and project setup

The initial profile uses Python 3.11 or later, Git, authenticated GitHub CLI
read access, and local Codex hooks. The runtime probe exercised Codex CLI
0.167.1. The Python package has no third-party runtime dependencies.

From the reviewed checkout in a Bash terminal, install the console command
using the standard user tool environment:

```bash
uv tool install .
graphvon-preflight --help
```

If the tool directory is not on your normal `PATH`, use `uv tool update-shell`
once and open a new terminal before checking the command. To refresh an existing
installation after reviewing a new candidate, use `uv tool install --force .`.
This installs a snapshot; source edits do not update the installed guard.

The repository owns the canonical skill. Install its shared projection once
and refresh it from that source when the reviewed skill changes:

```bash
mkdir -p "$HOME/.agents/skills/graphvon-start-work"
cp .agents/skills/graphvon-start-work/SKILL.md "$HOME/.agents/skills/graphvon-start-work/SKILL.md"
```

Do not edit the installed projection as a second source. Its documentation
references resolve from the bound checkout or installed Python package, not
from the shared skill directory. The project hooks remain in
`.codex/hooks.json`; do not install them globally. Shared tool and skill
availability alone does not activate project hooks in unrelated repositories.

Follow the skill to provision an admitted context and identify the canonical
private working record. Register their absolute locators under the exact
resolved Git worktree root in the user's private
`$XDG_CONFIG_HOME/graphvon/config.toml`, defaulting to
`~/.config/graphvon/config.toml` when `XDG_CONFIG_HOME` is unset or empty.
An explicitly set configuration directory must be absolute. Create that file
privately outside tracked content; preserve any other checkout registrations.
This synthetic example documents the complete version-1 installation schema:

```toml
version = 1

[projects."/absolute/resolved/checkout"]
context = "/private/example/assignment.json"
working_record = "/private/example/working.md"
```

Replace these synthetic values with the actual private locations. The key is
the resolved `git rev-parse --show-toplevel` result from the intended checkout.
Each worktree has its own key, even when it shares a Git common directory.
Unknown fields, malformed TOML, invalid field types, non-regular configuration
files and non-absolute locators are refused. This registration is installation
metadata, not a task registry or an admission. The coordinator still owns the
context, generation and reconciliation of unfinished operations.

Inspect the skill's discovery in the new session and invoke
`$graphvon-start-work`. Review project trust and the exact hooks through Codex's
normal trust flow and `/hooks`; confirm that both exact hooks are enabled and
trusted. Do not bypass trust. `PreToolUse` matches only `apply_patch` and invokes
`graphvon-preflight`. `SessionStart` invokes `graphvon-preflight session-start`
for `startup`, `resume`, `clear`, `compact` and `fork`. Each uses a 10-second
outer timeout and a 6-second internal read budget.

## Daily launch and continuation

After one-time setup, use the ordinary commands from the project terminal:

```bash
codex
codex resume
```

No activation, export, wrapper or replacement launcher is required. The native
startup handler resolves the effective working directory's Git worktree root
and validates its context's root before offering concise private context,
working-record and canonical skill references to the local session. It does
not inject record contents, validate the working record's contents, rotate a
generation or authorize work. Read the referenced state and reconcile prior
operations and current admission before continuing writes.

Missing or invalid state produces an informative startup message; read-only
investigation remains possible. The pre-tool handler independently resolves
the same binding and retains its context, checkout, patch and source checks.
It denies covered writes when those checks cannot be completed. No ancestor,
prefix, Git common-directory or implicit record search selects another entry.
Test fresh startup, resume and compaction in the actual runtime after installing
and trusting a changed hook; module tests alone do not establish that behavior.

## Private context and source observation

The version-1 context schema and its validation are canonical in
[contracts.py](src/graphvon/contracts.py). The skill explains who provisions
the record and when its source basis must be reconsidered. The shared resolver
in [installation.py](src/graphvon/installation.py) reads the explicit checkout
registration described above. A present `GRAPHVON_CONTEXT` overrides it for
deliberately configured launches. An empty, relative, unreadable, malformed or
wrong-checkout override is refused without falling back to registration. A
valid override is independent of user configuration and therefore supplies no
registered working-record reference. Keep actual locator values out of public
examples, command arguments, committed configuration and reports.

For an implementation assignment, obtain the public basis with the read-only
command below, replacing the repository and native numbers with the actual
task:

```bash
graphvon-preflight snapshot --repository example/project --issue 2 --pull 4
```

Capture the JSON privately as the context's `implementation.basis`. The
snapshot reads public sources and grants no authority or review approval.
Use `graphvon.sources.load_context` to validate a completed context before
launch, using the installed package's Python environment or, from the matching
source checkout, `PYTHONPATH=src python3`. Preparation uses the same context
structure with its own admission source and omits `implementation` entirely.

## Recover after an interrupted or restarted session

Follow the canonical skill's
[release and reconciliation procedure](.agents/skills/graphvon-start-work/SKILL.md#release-and-reconcile-the-assignment).
The steps below help inspect the evidence; they do not grant a new assignment.

1. Identify the surviving assignment through the exact checkout registration
   or explicit override and its admission references. Match each attempted patch
   to its tool result. Keep that projection unchanged while any result is outstanding. A lost
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
5. Launch again with ordinary `codex` or `codex resume` from the project terminal.
   Verify skill discovery, the exact enabled and trusted hooks, and
   the intended private continuation references in the new session. Reconcile a
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
