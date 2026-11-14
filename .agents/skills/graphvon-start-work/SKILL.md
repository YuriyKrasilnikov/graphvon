---
name: graphvon-start-work
description: Admit or resume a bounded Graphvon source-edit assignment from current requirements, the Draft PR description and applicable independent review, or provision explicitly scoped preparation. Use before releasing Graphvon implementation; read-only investigation needs no write context.
---

# Graphvon start work

Apply the [start-work contract](https://github.com/YuriyKrasilnikov/graphvon/issues/2)
within the current assignment's authority. Owner and project instructions retain
their precedence. This skill records existing authority; it grants no new
permission and does not replace independent judgment with a local approval flag.

## Classify the intended effect

Identify the governing instruction, actual intended effects and exact paths.
Read-only investigation needs no write context. Explicitly admitted proposal or
private preparation uses a `preparation` context with its own source and scope;
it does not require an implementation Issue, Draft PR or review basis.

Product implementation uses an `implementation` context. File extensions and
labels do not decide this distinction: calling a product change preparation
cannot exempt it. Hold a contradictory assignment rather than inventing missing
authority. Continue unrelated admitted work.

## Establish the implementation basis

Read the current Issue requirements, applicable accepted changes and the actual
Draft PR **description**. The description holds the proposed approach; do not
create a repository plan file. Confirm that the proposal answers the requirement
and covers the intended effect, including its prerequisites and limits.

Before releasing dependent implementation, obtain applicable independent review
of that basis and scope from someone other than the subject's author. Retain the
exact reviewed basis, conclusion, provenance and unresolved conditions. Internal
review evidence can remain private. Publish only concrete findings or decisions
needed by the PR reader. A URL, write permission, account name or approval status
alone does not establish relevance, authority or independence.

Read back the native public sources using `graphvon-preflight snapshot` as
explained in the registered checkout's `README.md`. Its JSON is an observation,
not a semantic review or grant. Preserve private review evidence separately from the
manifest of actual public discussions. Reconcile an expected public review
addition only when a meaningful public decision was actually posted.

A changed requirement, proposal, discussion or assigned effect requires the
affected admission to be reconsidered. Reuse a still-applicable review with a
stated basis instead of requesting ceremonial permission. Ordinary branch-head
movement does not itself change the reviewed design. Failed or incomplete source
reads establish unknown state, not absence of a change.

## Provision one private context

The coordinator owns the active context and generation. Use the canonical
version-1 schema in the installed `graphvon.contracts` module (source:
`src/graphvon/contracts.py` in the registered checkout), and
`graphvon.sources.load_context` to validate a completed record. Never publish an
actual private record name, locator or evidence reference in committed
configuration, descriptions, examples or public reports. One-time installation registers the
exact resolved Git checkout root and its context and working-record locators in
the private user Graphvon `config.toml`. The native startup hook supplies concise
local references; it neither reads the working record into the session nor
authorizes work. Resolve `README.md`, the skill source and other repository
references from that checkout, never relative to a shared installed skill copy.
The repository skill is canonical; a shared installation is only its projection.

A present `GRAPHVON_CONTEXT` is an explicit absolute-path override. An invalid
override never falls back to registration. With no override, only the exact
checkout registration is used; there is no parent match or record search.
Unavailable state permits read-only investigation but withholds covered writes.

Provision the common fields from the actual admission: checkout root, native
repository identity and remote, owner, fresh generation, kind, effect, exact
grants and the admission source reference/digest. Each grant names an operation
and repository-relative POSIX path. Include both move endpoints and any created
parent directories. Replacement requires an explicit replacement grant.

Use `scope_digest(kind, effect, grants)` for the scope consistency field. It binds
the declared fields to one another; it proves neither authority nor tamper
resistance. Hash the exact retained admission evidence for `admission.sha256`.

This synthetic preparation example illustrates construction. Replace its source,
repository, owner, generation, effect and grants with the actual admitted values
before creating a real context; the example is not authorization. For this
one-time provisioning operation, run from the checkout root with
`PYTHONPATH=src python3` after setting the private destination in
`GRAPHVON_CONTEXT`. This is not a daily launch requirement.

```python
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
from graphvon.contracts import Grant, context_from_dict, scope_digest

kind = "preparation"
effect = "Prepare the admitted fixture"
grants = (Grant("add", "sample.txt"),)
admission_text = "Synthetic instruction for an isolated preparation fixture."
record = {
    "version": 1,
    "kind": kind,
    "root": str(Path.cwd().resolve()),
    "repository": {"name": "example/project", "id": "R_example", "remote": "origin"},
    "owner": "assignment-owner",
    "generation": "synthetic-generation",
    "effect": effect,
    "grants": [asdict(grant) for grant in grants],
    "admission": {
        "reference": "synthetic-instruction",
        "sha256": hashlib.sha256(admission_text.encode("utf-8")).hexdigest(),
        "scope_sha256": scope_digest(kind, effect, grants),
    },
}
context_from_dict(record)
with Path(os.environ["GRAPHVON_CONTEXT"]).open("x", encoding="utf-8") as destination:
    json.dump(record, destination, indent=2)
    destination.write("\n")
```

Preparation omits `implementation`. For an implementation context, use the
actual implementation effect/grants, recompute the scope digest, and supply
`implementation.issue_number`, `pull_number`, the current `basis` from the
snapshot command, and `review`. The review contains its private reference and
SHA-256, the requirement and proposal content digests from that basis, the same
scope digest, reviewer provenance, the actual `proceed` conclusion and its
limits. Do not manufacture a conclusion to satisfy the schema. The canonical
validator rejects missing, extra or contradictory fields; structural validity
does not establish semantic admission.

## Release and reconcile the assignment

Keep only one active guarded assignment per checkout. Freeze its record from
release until every attempted patch has a known outcome. No competing handoff or
replacement may change that generation while a tool result is outstanding. The
record and hook provide no operating-system lock or per-agent task attribution;
the coordinator must prevent concurrent filesystem mutation. Parallel read-only
work and genuinely isolated preparation remain possible.

Follow the registered checkout README's one-time tool installation, private
registration and normal trust steps. Daily use is plain `codex` or
`codex resume` from the project terminal, without activation or exports.
In a fresh launch, verify that this skill is discoverable, the exact hooks are
enabled and trusted, and the startup
references and pre-tool resolver select the intended private context.
Explicit invocation can demonstrate use; it does not prove automatic selection.
Do not bypass trust or switch writers after a
failed control.

On restart or resume, inspect the surviving assignment and reconcile prior tool
results with actual filesystem effects before continuing. Record survival alone
never reauthorizes an assignment. If completion is unknown, hold dependent
writes until effects and current sources are reconciled. Retire the active
projection only after operations settle and required evidence is preserved;
release a new generation only on a current admission. Detailed recovery work
must preserve this stop boundary.

## Keep the claim bounded

For a checkout explicitly adopted for Git push inspection, use the
[publication guidance](../../../CONTRIBUTING.md#git-push-privacy) and the
documented `graphvon-push` lifecycle. A standalone check does not establish
that the installed launcher is active; other publication routes still need
their applicable review.

The hook checks the complete supported native `apply_patch` operation. Its
initial profile is local POSIX paths without links, special files or concurrent
filesystem mutation. An admitted task outside that profile requires explicit
scope reconsideration before support is extended, not a workaround writer.

Missing context denies a covered write; read-only tools are unaffected.
Handled errors deny, but runtime failure can still allow a tool to proceed if
the hook is killed, times out or returns malformed output. The control does not
intercept every writer or make source reads atomic. Known absent, disabled,
untrusted or failed control withholds the dependent guarded handoff.

Preserve the actual requirement, design-only Draft, applicable review and
implementation order. Bootstrap construction cannot be mechanically protected
by the guard being constructed. Keep source checks, procedure comparison,
native integration and meaningful real use as separate evidence. Report the
verified scope and remaining obligations; a passing module test or successful
patch does not establish acceptance of the whole task.
