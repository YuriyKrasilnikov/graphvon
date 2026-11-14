# The Graphvon method

Graphvon connects a required outcome to an approach, an actual change, evidence
and a scoped acceptance decision. This guide explains how those pieces relate.
It is readable on its own; use the linked sources for the rules and operating
instructions that apply to a particular task.

## Find the outcome and its sources

Start with the original goal and applicable accepted changes. Identify the
behavior, quality and operational constraints, relevant architectural
conditions, acceptance criteria and unresolved questions. A constraint shared
by several parts must hold for their combined result, not just for each part
in isolation.

The current Issue states the required result. When work is split, identify the
part a child carries, the conditions it shares with its parent and what remains
elsewhere. A completed child can be useful without completing the parent.
Check the Issue against its governing sources in both directions: account for
applicable obligations, and justify additions without presenting a proposed
solution as an original requirement. The [Issue guidance](../CONTRIBUTING.md#issues)
and [Change form](../.github/ISSUE_TEMPLATE/change.yml) define the project
entry point.

## Explain the approach before changing source

A Draft PR describes how the result will be achieved: scope, relationships,
alternatives, risks, implementation steps and distinguishing verification.
Compare its proposed effects with the Issue and applicable conditions. Trace
each obligation to its treatment or explicit remainder, and trace each
proposed effect back to its justification. A necessary implementation detail
need not have been named in the original request, but a new requirement needs
an applicable basis.

Obtain applicable independent review of the requirement, approach and assigned
scope before dependent implementation. The
[PR guidance](../CONTRIBUTING.md#pull-requests),
[PR template](../.github/pull_request_template.md) and
[start-work procedure](../.agents/skills/graphvon-start-work/SKILL.md) own the
details. The procedure also covers admission, recovery and what to do when a
source read or prior operation is uncertain. A private assessment may support
the decision; public descriptions should convey the result and necessary
limitations without requiring private records.

```text
Goal and governing sources
          ↓
Issue and remaining obligations → Draft approach and review → Actual change
          ↑                            ↑                         ↓
          └──── affected reassessment ─┴── Scoped acceptance ← Evidence
```

The arrows describe relationships, not a fixed catalogue of artifacts. A change
can require a return to an earlier decision; it does not automatically erase
unaffected evidence.

## Inspect evidence and accept its supported scope

Identify the actual change and its revision. Keep a planned check separate from
an execution, an observation separate from its interpretation, and a supplied
judgment separate from the facts it assesses. Preserve the original subject and
conditions of an observation when considering its current applicability. A
relocated evidence reference needs a continuity judgment; matching text alone
does not silently make it the original evidence.

Assess the applicable criteria and shared conditions against the actual result.
Record what the evidence supports, its limits and the remaining work. A passing
check, merged PR or accepted component does not by itself establish acceptance
of a broader outcome. If an observation is unavailable, retain that unknown
instead of treating it as a passing result.

## Reassess what changed

Follow the affected relationships and preserve still-applicable conclusions.
An upstream change calls for checking its immediate dependent judgment; if that
judgment remains valid under the changed input, do not assume every downstream
result changed merely because it is reachable.

| Change | Reassessment starting point |
| --- | --- |
| Goal, constraint or accepted requirement | Check the affected Issue and shared conditions, then follow any changed obligations into the approach and evidence. |
| Proposed approach or assigned scope | Check its correspondence, effects, review and readiness for the affected work. |
| Actual change or evidence subject | Check correspondence and whether the original observations still apply to the result. |
| Tool, environment or publication route | Check the observations and limits that depend on that route; retain unobserved behavior as unknown. |
| Acceptance criterion or decision | Reassess the affected claim and remainder against applicable evidence and shared conditions. |

## Find the authoritative instructions

| Reader task | Source |
| --- | --- |
| Find a current requirement and its remainder | The applicable Issues and accepted changes |
| Prepare and assess an Issue | [Contributing: Issues](../CONTRIBUTING.md#issues) and the [Change form](../.github/ISSUE_TEMPLATE/change.yml) |
| Describe and assess a Draft | [Contributing: Pull requests](../CONTRIBUTING.md#pull-requests) and the [PR template](../.github/pull_request_template.md) |
| Begin or resume source work | [Start-work skill](../.agents/skills/graphvon-start-work/SKILL.md) |
| Install and operate the toolkit | [README](../README.md#one-time-installation-and-project-setup) |
| Understand the relationships across these artifacts | This guide, identified by its repository path and Git revision |

The guide explains these sources; it does not replace their rules. Git history
versions the guide. A Wiki page derived from it is a reader view, not another
rule authority.

## Use checks within their boundaries

The [README](../README.md) describes installation, inputs and supported
environments. Choose a check for the actual task:

- [`graphvon-preflight`](../README.md#daily-launch-and-continuation) observes
  native sources and supports the declared native patch route. The hook covers
  its documented local path profile, not arbitrary writers. Runtime
  termination, timeout or malformed hook output can allow a patch to proceed;
  a snapshot is neither atomic nor a semantic review.
- [`graphvon-issue`](../README.md#checking-an-issue-proposal) checks declared
  sources, form and supplied assessment bindings. Its separate publication
  operations have their own documented lifecycle.
- [`graphvon-draft`](../README.md#checking-a-draft-plan) checks a plan's
  references, supplied judgments and observed native Issue and PR context. A
  matching context is not an independent judgment or permission to implement.
- [`graphvon-evidence`](../README.md#checking-evidence-against-a-committed-change)
  relates retained plan inputs, an explicit committed change, selected
  observations and a scoped claim. It distinguishes original evidence from
  current applicability and an acceptance decision. Exit 0 means it produced
  a report, which can be partial; supplied judgments and mechanical consistency
  do not establish semantic truth or acceptance.
- [`graphvon-push`](../README.md#checking-git-push-privacy) inspects declared literals
  in supported Git pushes from an explicitly adopted checkout. It does not
  judge meaning, cover other publication transports or establish historical
  cleanup. A standalone scan does not establish installed-hook coverage.

These are bounded local capabilities, not a claim that every action is
intercepted or that a hosted check performs semantic acceptance.

## A bounded public example

[Issue #11](https://github.com/YuriyKrasilnikov/graphvon/issues/11) requested
inspection of supported Git pushes for declared private literals while
preserving legitimate publication. [PR #12](https://github.com/YuriyKrasilnikov/graphvon/pull/12)
describes the selected local pre-push approach and reports controlled permitted
and refused cases, installation checks and a useful push through the installed
route. It was merged into the project.

That public record supports a bounded example of the Git route and its
reported evidence. It also states that semantic review, other transports and
historical cleanup remain separate. Neither the merge nor a clean literal scan
establishes those broader results.

## Wiki and updates

The repository guide remains usable independently of the Wiki. A Wiki entry,
when published, is a manually maintained view derived from an identified
accepted documentation revision. Its source revision and links should let a
reader distinguish that pinned view from current documentation. Update
canonical sources first, then assess affected Wiki content. Publication
requires observing existing content and an available editing route, reviewing
the exact outgoing content and links, and reading back the rendered result.
No automatic synchronization or Wiki availability is implied.
