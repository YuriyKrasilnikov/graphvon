# Contributing

## Issues

This section is the authoritative entry for Graphvon's Issue proposal rules.
The supported template is [Change](.github/ISSUE_TEMPLATE/change.yml).
The form defines its input fields; this section defines their purpose and use.

An Issue states the requested outcome, applicable conditions and constraints,
acceptance criteria, necessary relationships and unresolved questions. Start
from the original request and accepted changes. An implementation proposal
belongs in a Draft PR description and does not itself change the requirement.

The required sources for a proposal are this section, its selected form, the
original request and accepted clarifications, and any applicable existing
requirements or architectural constraints. A child Issue also identifies the
part transferred from its parent, the remaining obligations and shared
conditions. Catalogues and recommendations are not adopted requirements merely
because they were consulted. Unknown applicability remains an open question.

Keep one canonical source for each rule. The assessed project basis records
which sources apply, their revisions and the permitted template choices. It is
a checked projection, not a second authority. Assess that projection against
its original sources before using it. A proposal's author cannot narrow the
mandatory source set by choosing different request parameters. Accepted changes
to the governing rules require reassessment of the affected basis.

### Assess a proposal

Keep the source trace and working assessments private. For each obligation,
identify its source, conditions, coverage in the proposal and any remainder.
Check the trace against the original material, including requirements that may
have been lost while constructing the trace itself. For each proposed addition,
establish why it is needed and whether it changes an obligation. A derived
component requirement retains the accepted decision, authority and scope that
justify it. A description of an architecture is not automatically such a
decision. Necessary implementation detail is not a new user requirement solely
because the original request did not name the individual operation.

Assess these questions separately:

- Does the proposal preserve the applicable source requirements?
- Is the requested behavior sufficiently defined in the assessed area?
- Is it ready for the named next action under the remaining conditions?

An accurate restatement can still be insufficient for choosing a solution.
A clearly identified unresolved question may be appropriate for discussion
while holding dependent implementation. Partial coverage preserves the parent
obligation; it does not establish completion. Check common constraints on the
combined result, not only each part separately.

A substantive assessment uses the original requirements and the candidate,
independently of the author's explanation where that explanation could narrow
the question. Retain the assessed content, source revisions, scope, conditions,
provenance and limitations. Record preservation, definition, readiness and
publication judgments separately. A link or approval flag is insufficient.

Before publication, inspect the exact outgoing title, body and relationships.
Public material is in English and must be understandable without private
session history. Do not include private source locations, working notes,
internal priorities, assignments or assessment metadata. Examine meaning as
well as literal identifiers: a paraphrased internal instruction can still be
an inappropriate public requirement. A legitimate accepted product requirement
must remain understandable rather than being removed because it resembles an
internal term.

### Executable check

`graphvon-issue check` checks the declared sources, supported form and binding
of a supplied assessment. It does not perform the semantic assessment above,
grant publication authority, create an Issue or update the stored proposal.
The separate create and reconcile operations use the assessed proposal and
private operation record as described in the README. A supported result is
not a semantic assessment or independent evidence of publication authority.
Its current form profile supports `markdown` instructions and `textarea`
fields. Unsupported form elements are reported explicitly.

Read the [checker instructions](README.md#checking-an-issue-proposal) for the
input contract, source modes and interpretation of its output. A complete
report can contain an unresolved or negative judgment. Neither filled fields
nor matching fingerprints establish that the requested result is correct.
