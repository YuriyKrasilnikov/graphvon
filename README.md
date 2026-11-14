# Graphvon

Graphvon connects a source-edit assignment to its current requirement, proposed
method and applicable independent review. One repository-local skill guides the
semantic decision; a narrow Codex hook checks the declared native patch route.

The procedure is defined in
[graphvon-start-work](.agents/skills/graphvon-start-work/SKILL.md).
Requirements and the proposed implementation remain in the project's GitHub
Issues and PR descriptions.

The read-only Issue proposal checker uses the repository's declared rules and
native Issue Form. The [Issue contract](CONTRIBUTING.md#issues) defines the
source and semantic assessment procedure.

## One-time installation and project setup

The initial profile uses Python 3.11 or later, Git, authenticated GitHub CLI
read access, and local Codex hooks. The runtime probe exercised Codex CLI
0.167.1. The Issue proposal checker uses PyYAML to read native forms.

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

## Creating and reconciling an Issue

`graphvon-issue create` reads one JSON request from standard input. Supply an
absolute private project-basis path and proposal path, the proposal's current
`record_revision`, and publication permission bound to the assessed subject:

```json
{
  "version": 1,
  "project_basis": "/private/example/project.json",
  "proposal": "/private/example/proposal.json",
  "expected_record_revision": "revision",
  "authorization": {
    "source": "private permission reference",
    "subject_sha256": "assessed subject fingerprint",
    "effect": "create_issue"
  }
}
```

Optionally select a native parent in the proposal candidate as
`{"number": 1, "id": 123, "node_id": "I_native"}` under `native_parent`.
This selection is part of the assessed subject. The numeric `id` is the native
Issue ID, not its number. Creation checks installed sources and requires an
applicable assessment supporting preservation, publication and readiness for
`create_issue`; unresolved definition does not by itself prevent a supported
readiness judgment. The permission reference and judgments remain procedural:
their presence and fingerprints cannot establish their authority or truth.

One coordinator owns each private record. There is no concurrent-writer lock.
Settle any prior process before continuing. Intent is persisted as `prepared`;
the `sending` state is persisted and synchronized before the one native POST.
If a prepared operation survives interruption, the same request may continue
with its current revision and `"owner_settled": true`, after ownership is
settled. It repeats current source, assessment, permission and parent checks;
changed intent is refused. A `sending` outcome may have created an Issue and
must not be retried. A definite native rejection is recorded separately from
an unknown response. No created Issue is automatically closed or deleted.
After a definite rejection, a separately selected new attempt uses the current
record revision, `"owner_settled": true`, and a `rejection_resolution`
reference recording the assessment of the cause and current permission. The
previous rejection remains in the private record. This does not apply to an
uncertain send.

`graphvon-issue reconcile` takes `version`, `proposal` and
`expected_record_revision`. It performs native GETs and private record updates
only. If no response identity survived, it can also take a `candidate` with
native `number`, `id` and `node_id`, and a `resolution_evidence` reference
establishing attribution. Matching content alone does not establish that
attribution. Reconciliation retains observations and discrepancies separately;
confirmation requires matching object content and the selected native parent
when one was requested, plus persistence of that result. Source observations
and native operations are not one atomic transaction. File and directory
synchronization applies to the supported ordinary local POSIX file profile,
not every possible storage failure. A persistence error leaves its outcome
unknown: inspect the record and retain any returned native identity.

The public request contains only title, body and an optional parent ID. The
private trace, assessment and permission are never included in that payload.
Other ways to create or modify Issues are not intercepted. Confirmation of an
Issue does not establish semantic acceptance of the methodology.

## Checking Git push privacy

`graphvon-push` can inspect pushes from an explicitly adopted ordinary complete
checkout for declared private UTF-8 literals. It uses the local default
pre-push hook slot, without changing global Git configuration. The private
policy selects actual literals through substantive review; the policy does not
grant publication authority. Applying it to every destination from an adopted
checkout, including local and private remotes, is a conservative project choice.

A policy is an explicitly selected ordinary private JSON file. This example is
synthetic; replace every value with reviewed project-specific information:

```json
{
  "version": 1,
  "checkout": "/absolute/example-checkout",
  "destinations": "all",
  "owner": "example owner",
  "authority": [{"locator": "private reference", "description": "reviewed scope"}],
  "protected_literals": [{"id": "example", "value": "SYNTHETIC-PRIVATE-TOKEN",
    "owner": "example owner", "sources": [{"locator": "private reference", "description": "source"}],
    "applicability": "example scope", "retirement_condition": "reviewed retirement"}]
}
```

`graphvon-push check --policy PATH --remote-name NAME --remote-location LOCATION`
run from the checkout root reads Git's pre-push update lines from standard input. This standalone check
does not establish installation coverage. `graphvon-push install` reads a JSON
request containing `version`, absolute `checkout`, absolute `policy` and an
`intent`: `create`, `verify`, `finish_install` or `update_policy`. All intents
except `create` require `expected_installation_id`. `graphvon-push uninstall`
reads `version`, `checkout`, `expected_installation_id` and `intent` (`remove`
or `finish_removal`). These operations need their ordinary scoped authority.

The installed launcher verifies its checkout, owned binding, launcher identity
and current policy before inspecting an adopted push. Lifecycle operations
distinguish verification, completion of interrupted installation or removal,
and deliberate policy updates; foreign or modified hooks are preserved. A
different linked worktree is not silently adopted. Configured hook paths,
existing foreign hooks and unsupported repository states are refused.

The supported inspection reads the conservative new-object closure excluding
only complete old closures supplied by the push. It inspects raw commit and tag
metadata, blob bytes, tree entry names and reconstructed paths, plus destination
refs. New branches can rescan already-public history. SHA-1 and SHA-256 Git
repositories are supported; shallow, promisor, replacement and alternate object
stores are refused. It does not fetch, run filters or follow symlinks. A symlink's
stored target is inspected; external submodule and LFS contents are not.

Exit 0 means a supported scan found no literal or a linked worktree was not
adopted; the report distinguishes `checked` and `not_adopted`. Exit 1 means a
declared literal matched. Exit 2 means inspection or lifecycle was invalid,
unsupported or unavailable. Diagnostics do not print the protected values or
destination locations. A clean result is not a semantic privacy review,
publication authority, remote success or historical cleanup. The hook does not
intercept other publication routes or a push that bypasses it.

## Checking a Draft plan

`graphvon-draft check` reads a versioned JSON request from standard input. It
does not modify its private records or remote objects. Its paths must identify
explicit private files, and `mode` is `working` or `installed`:

```json
{
  "version": 1,
  "project_basis": "/private/example/draft-project.json",
  "issue_contract": "/private/example/issue-contract.json",
  "draft": "/private/example/draft.json",
  "mode": "working"
}
```

The project basis contains the Issue checker project-basis fields and a
`profiles` array. Each profile has a permitted `template` source key and
`sections`; each section has `heading`, boolean `required` and `rule_refs`.
The assessment binds the entire profile. Template headings and the declared
profile must agree; source authority and whether the profile correctly projects
the rules remain substantive assessments.

The Issue contract has `schema_version`, `artifact_id`, `record_revision`,
`repository`, `issue`, `scope`, `sources`, `conditions`, `obligations`,
`shared_constraints`, `remaining`, `unknowns` and `assessment`. Its `issue`
contains `number`, `node_id` and the native Issue `source` key. Conditions have
`id`, `statement`, `source_refs`; obligations add `condition_ids` and
`acceptance`; shared constraints add `obligation_ids` and `condition_ids`.
The optional assessment binds the Issue subject and separately records
preservation, publication, and definition and adequacy for each named action.
It also contains provenance, scope, limits and an optional superseded assessment.

The Draft record contains `schema_version`, `artifact_id`, `record_revision`,
`candidate`, `trace` and nullable `assessment`. The candidate contains
`template`, `title`, `body`, `issue` and nullable `native_pr`; native identities
use `number` and `node_id`. The trace contains `scope`, an `action` object with
`kind` (`discuss`, `publish`, or `implement`) and `description`, `source_keys`,
`conditions`, `unknowns`, `remaining`, `obligations`, `effects` and
`constraints`. Obligation rows hold `issue_obligation`, `coverage`, `plan_refs`,
`verification` and `remainder`. Effects hold `id`, `plan_refs`, `kind`,
`issue_obligations`, `source_refs` and `rationale`. Constraint rows hold
`issue_constraint`, `effect_ids`, `plan_refs`, `planning_witness`,
`planned_verification` and `remaining_conditions`.

Source references use `source` (a `project:` or `issue:` namespaced key) and a
`selector`. A selector has `kind` (`whole`, `exact`, or `markdown_section`)
and `target` (`source_text` or native `issue_body`). Exact selectors add
`start`, `end` and `text`; Markdown section selectors add `heading`. Offsets are
zero-based Unicode code-point offsets into the exact selected text. Native
Issue-body selection remains bound to the complete native Issue source and its
discussion. Draft body references contain `heading`, `start`, `end` and `text`
and select the exact unnormalized body under a unique level-two heading.

Draft assessments bind separate local and composition subjects and contain
`provenance`, `scope`, `local_preservation`, `justification`, `definition`,
`joint_constraints`, `publication`, `readiness` and `limits`. Each judgment
contains a result and reasons; readiness also names the exact action. The joint
judgment is bound to the composition subject and assesses compatibility of the
scoped contracts, conditions and shared constraints. The checker does not infer
compatibility from scope names. Matching fingerprints are not substantive
assessments or permission to act.

Readiness may contain a `native_context` receipt with `subject_sha256`,
`basis`, `provenance`, `scope`, `applicability` and `limits`. The basis retains
the normalized repository, Issue and PR identities, lifecycle, title and body,
head and base repository/ref/commit, and the complete observed discussion
fingerprint envelopes. Each envelope has `id`, `updated_at`, `submitted_at` and
`content_sha256`; its fingerprint binds the adapter's content representation,
but cannot reconstruct an earlier discussion or establish its meaning.

The receipt subject binds the exact named action, assessment scope, computed
local and composition subjects, and normalized native context. Implementation
readiness requires a supported applicable receipt and a matching open Draft.
For discussion and publication an absent receipt means candidate-only
readiness; a supplied receipt binds that action to the observed native context.
The report identifies changed context components mechanically. Changes require
an applicability decision for the affected action, not automatic invalidation
of unchanged local judgments or automatic reapproval. Reaffirmation and prior
evidence retention remain separate assessment work; the checker writes none.

The supported Markdown profile uses unique plain ATX level-two section
headings, recognizes fenced blocks and comments, and reports unsupported
headings or malformed constructs. Structural findings establish neither plan
quality nor requirement preservation. Installed mode uses observed
default-branch sources without a working-file fallback; working mode supports
review of proposed local rules and templates. Native Issue and optional PR
observations use two GET passes, not an atomic snapshot. A private candidate
does not imply an existing PR. Readiness for implementation additionally needs
a current matching open Draft and applicable named-action judgments. Reports
keep unavailable inputs, negative supplied judgments and local diagnostics
separate. Exit 0 means a report was produced, not that the plan was accepted.

## Checking an Issue proposal

Prepare a project basis and proposal record privately according to the
[Issue assessment procedure](CONTRIBUTING.md#assess-a-proposal). The project
basis is assessed independently of the individual proposal. Its sources and
permitted templates come from the declared canonical entry; selecting an
easier template in a request cannot replace that contract.

Run the installed command with a JSON request on stdin:

```bash
graphvon-issue check < /private/example/check-request.json
```

The following paths are synthetic. Replace them with explicit private
locations; do not commit the request or records.

```json
{
  "version": 1,
  "project_basis": "/private/example/project-basis.json",
  "proposal": "/private/example/proposal.json",
  "mode": "working"
}
```

`working` reads repository files from the named checkout and reports
`working_candidate`. `installed` reads repository files through authenticated
GitHub GET requests at the observed default-branch commit and reports
`installed_profile`. It does not fall back to local files when an installed
form is absent. Both modes confirm the checkout's `origin` and native GitHub
repository identity. Private local sources remain explicitly selected local
files in either mode. Sources and comments are observations, not an atomic
transaction with subsequent changes.

### Project basis format

The version-1 JSON object contains exactly these fields:

| Field | Content |
|---|---|
| `version` | `1` |
| `root` | Absolute checkout root |
| `repository` | `{ "name": "example/project", "id": "R_native_id" }` |
| `canonical_entry` | `{ "source": "rules", "fragment": "issues" }`; the source key identifies the declared repository entry |
| `sources` | Source descriptions below |
| `allowed_templates` | Source keys identifying permitted repository Issue Forms |
| `scope` | The assessed scope, such as `issue_proposal` |
| `assessment` | Assessment of this projection against its original sources |

Each source has `key`, `kind`, `location`, `sha256`, `applicability`, `basis`,
`owner` and `status`. Keys are unique. `basis` explains applicability; `owner`
and `status` retain provenance rather than grant authority. Applicability is
`required`, `not_applicable` or `unknown`; the latter two require their stated
basis. Unknown applicability keeps coverage partial. The canonical entry is
required. The selected template must also be applicable, and all required
sources must appear in the proposal's trace.

Supported source kinds are:

- `repository_file`: `location` is a repository-relative path. Working files
  must resolve inside the checkout. Installed files come from one pinned
  default-branch commit.
- `local_file`: `location` is an explicit absolute private path.
- `github_issue`: `location` is the Issue number in the bound repository.
  Its observed content includes the native identity, title, body and the
  complete normalized discussion. A PR is not accepted as this source type.

File fingerprints are SHA-256 of the UTF-8 text, preserving line endings.
`graphvon.issue_contracts.text_digest` computes them. A native Issue's text
representation is provided by `SourceReader.read`; do not substitute an Issue
number or modification timestamp for its content. Read failures and changed
fingerprints are reported separately from known non-applicability.

The project `assessment` contains `subject_sha256`, `provenance`, `scope`,
`conclusion` and `limits`. Its fingerprint is computed by
`graphvon.issue_contracts.project_subject` over the basis excluding this
assessment. `conclusion` is `supported`, `discrepancy` or `unknown`; `limits`
is a list of distinct statements. Record a supported judgment only after the
assessment actually establishes it. Computing a fingerprint or copying these
fields does not establish authority, completeness or independent review.

### Proposal format

The proposal has `schema_version: 1`, a stable `artifact_id`, a separate
`record_revision`, `candidate`, `trace` and `assessment`. Optional `operation`
and `observation` bookkeeping is neither interpreted nor changed by `check`.

The candidate contains `template` (a permitted source key), `title`, `fields`
(a mapping of form IDs to text), and `relationships` (distinct descriptions
of the intended relationships). Relationships require semantic assessment;
this checker does not create or observe native graph edges. Include necessary
public relationships in the appropriate form value so the rendered Issue is
self-contained.

The trace contains:

- `source_keys`, `scope`, `next_action` and `conditions`;
- `obligations`, each with a unique `id`, `sources`, `fields`, `coverage` and
  `rationale`; optional `decision_sources` identify accepted decisions behind
  derived obligations;
- `remaining` and `unknowns`, retaining the unfulfilled or unresolved parts.

The reference/condition/remainder lists contain distinct strings. Obligation
coverage is `covered`, `partial`, `outside` or `unknown`. The checker validates
references and keeps the supplied meaning separate from structural evidence.
It cannot discover an omitted original requirement merely from a complete
table. The source-to-trace assessment must do that work.

Set `assessment` to `null` before semantic assessment. A completed check
returns `subject_sha256` for the observed content, sources, selected contract,
trace scope and next action. After the actual assessment, retain that basis
with `provenance`, `scope`, `limits`, and four separate judgments:
`preservation`, `definition`, `readiness` and `publication`. Each judgment has
`result` and `reasons`; readiness also names its `action`, matching the trace's
`next_action`. Results are `supported`, `discrepancy`, `unknown` or
`not_assessed`. Changing bookkeeping does not change this subject; changing
relevant content or sources requires reassessing the affected judgment.

### Supported forms and output

The initial native-form profile accepts top-level `name`, `description`,
`body` and optional `title`. Body elements are `markdown` instructions or
`textarea` fields with unique IDs using ASCII letters, digits, hyphens and
underscores. Distinct IDs may have the same label. Textareas support `label`, `description`,
`placeholder`, `value`, `render` and `validations.required`. Unsupported
widgets or metadata, ambiguous YAML keys and unsafe YAML constructions are
reported rather than silently discarded. Instructions and placeholders are
not submitted content; defaults are used when a value is omitted. The
canonical entry uses an ATX Markdown heading outside fenced code blocks.
Closing fences must use the opening character with sufficient length and only
trailing spaces or tabs. A fence-like line with trailing text inside a code
block does not expose subsequent example headings as canonical sections.

The JSON report separates `structure`, `source_coverage` and
`semantic_assessment`. `matches_subject` means the supplied assessment applies
to the checked basis; the checker has not independently established its truth.
An assessment may match while declaring a discrepancy or an unresolved next
action. `consistent_with_assessed_basis` concerns the declared source set,
not completeness of all possible requirements. There is no general approval.

The complete report is private working information. `declared_trace` retains
the supplied scope, named next action, conditions, obligations and their
declared coverage, remainder and unknowns. `semantic_assessment` retains the
assessed scope and supplied results together with judgment reasons, limits,
provenance and readiness action. `source_coverage.project_assessment` retains
the project-basis assessment's scope, conclusion and limits. These are supplied
judgments, not newly established machine conclusions. If a source or form
cannot be checked, the report preserves this context with the unresolved
applicability rather than silently dropping the limits of an earlier judgment.

`public_payload` contains only the rendered title and body. It is a candidate
for assessment, not publication permission. A private note inserted into a
form value still requires the publication judgment to detect it; an allowlist
of output fields does not detect semantic leaks. The rest of the report,
including trace details, judgment reasons, source keys and assessment
fingerprints, must remain private. It must not be pasted into public
descriptions as a substitute for useful results. Private diagnostic context is
never used to fill missing public fields automatically.

Exit status `0` means a report was produced, including any negative or partial
results. Status `2` means the supported request could not be processed. The
command makes no record, repository, GitHub or runtime-configuration writes;
it does not implement `create`, `reconcile` or a new publication hook. Read the
report's separate conclusions before deciding the next permitted action.
