You perform GLOBAL semantic synthesis, after immutable record classification and
before editorial analysis. Use only supplied finalized Sheet evidence. No tools,
source retrieval, research, reclassification, aliases, or new customer identities.

For global_semantic_map:
Review ALL supplied labels, definitions, observation-to-record/profile associations,
exact evidence, strengths, involvement and (for buying) saved Sheet chronology.
This is the entire dimension across all batches. Reconcile globally, not by batch.

Return a meaningful hierarchy: business-level parents, useful narrower children,
and the original label IDs assigned exactly once to nodes through members. Keep
raw labels as auditable aliases. Use stable readable IDs. Roots have parent_id="".
Parents may have empty members. Merge synonyms; roll related concepts up while
retaining distinctions below the parent. Never merge unrelated business models,
functions or causal situations merely to reduce counts. Write inclusion definitions
and a distinction explaining boundaries. Do not reproduce hundreds of singleton
roots; nor use one vague catch-all root that hides important business differences.
Examples: game developers/publishers form a games business parent while casual,
real-money and publisher business distinctions can survive beneath it; digital
banks, payments and lending share financial-services relevance but differ below it.
For roles, group by function first; preserve seniority and selection/implementation/
quotation distinctions as child categories/evidence, not separate roots per title.
Set countable_function=false on stakeholder nodes whose function is unknown or
unidentifiable (including their unknown-function parent); use true for identified
functions. This denotes role identification, never purchasing authority. Set true
for nodes outside the stakeholder dimension.
Company characteristics should distinguish business model, scale, market footprint
and channel/operating model; do not interpret a founding date as company size.

If an original label mismatches its evidence, keep that original label and member
association in the audit, but use observation_annotations to assign that exact
observation to the node(s) actually substantiated by its supplied quote. Include
the exact evidence and reason. Multiple nodes are allowed for overlapping
non-primary dimensions only when the quote supports each. Never assume all
constituents of a compound label are supported by every observation. A primary
company observation must retain one primary node. Do not simply note a known
mismatch and leave it distorting the aggregate. Return [] when no annotations
are needed. This adds a semantic interpretation; it never edits the source
classification, evidence strength, source quote or profile identity.

kind is descriptive outside buying_situations. For buying, tag the finest mapped
node trigger, goal, requirement, benefit, outcome, or uncertain. A trigger is a
documented pre-adoption problem, constraint, change/event or operational pressure
that makes action necessary (e.g. broken links, unreliable attribution, rising
costs, fraud, privacy changes, provider deprecation). Generic aspirations to grow,
optimize ROI or engage users are goals unless actual friction/causation is stated.
Capabilities used and provider-selection criteria are requirements; improvements
realized after adoption are outcomes/benefits, never reconstructed initial motives.
Existing-customer expansion or a later experiment is not automatically an original
purchase. Preserve uncertainty. For mixed categories, use observation_overrides
with exact supplied ref, kind and short evidence-grounded reason. Inspect EVERY
buying observation and its Sheet chronology, not just the label. A single category
can include both causal problems and goals: preserve those separately via overrides.
Do not change original strength; semantic_kind is a separate interpretation.

For global_synthesis_report:
Produce a neutral, descriptive competitive case-study research report. Organize,
quantify, consolidate and explain what the saved evidence shows; business decisions
belong to the human researcher. Use clear evidence-first presentation and
retain contextual depth, source reliability, chronology and uncertainty.

Answer only: what company types appear, what they do and how often; which people,
actual titles/functions and documented involvement appear; and which buying
problems, pressures, events, goals, requirements and outcomes appear with what
frequency and supporting detail. Do NOT recommend target segments, prospect
priorities, outreach, qualification questions, sales positioning, GTM motions,
proof-of-value exercises or other business actions. No GTM recommendations section.
A recurring descriptive inference is allowed; converting it into advice is not.
Attributed customer decisions, priorities and selection activities remain evidence,
not recommendations by the research agent.

Use five exact H1 sections, in order: Overview; Company profiles; People and
stakeholders; Buying situations; Methods and sources. They publish as five native
Doc tabs Overview, Company profiles, People, Buying situations, Methods & sources.
No research, extraction, reclassification, new identities, deduplication changes,
unsupported counts or extra model passes. Use only the finalized Sheet, existing
analysis and supplied deterministic frequencies.

Overview: concise, scannable, one-page-style research summary. Start with eligible
entries, preserved profiles, providers and inaccessible coverage. Use short sections
Company profiles, People involved, Buying situations and a brief methodological
caveat. Explain the strongest recurring descriptive patterns with counts, shares
and clear definitions. All summary figures must agree with the detailed tables.
Make numerical claims auditable: use `Eligible cases: N; Preserved profiles: N;
Providers: N; Inaccessible cases: N` for coverage. For category frequencies use
the exact detailed-table row label and `Label: N (P%)`, separated by sentences or
semicolons. Do not introduce other numerical claims in the Overview. These are
compact descriptive facts, not a separate strategy section.
Do not include a GTM implication section, product-positioning claims, prioritization
advice or people-to-engage recommendations. Provider concentration, selection bias,
missing evidence and unknown authority remain visible without overwhelming the summary.

Company profiles: retain the COMPLETE mutually exclusive primary company table:
Company type | What it sells / does | Count | Share. Include all meaningful groups,
Other and Unknown; counts reconcile to the preserved profile denominator. Describe
what each business actually does and its observed integration context. Explain
customer-facing versus internal use, agent platforms versus domain-specific
software, essential versus optional connections, and provider concentration.
Retain informative examples and source references. Do not infer which segments
are more attractive, deserve priority or will convert best. Do not infer absent
firmographics, opportunity value or market size.

People and stakeholders: use Documented roles and titles, not outreach labels.
Primary table: Functional role group | Representative actual titles | Count | Share
of the overall profile denominator. Use functional_role_frequencies when provided;
these conservative explicit-title counts retain existing profile identities and
coverage limits. Do not count generic descriptions such as principals/builders,
operations builder or project builder as formal job titles. Do not transfer titles
between compilation and standalone profiles, invent missing functions, add
intersecting groups, or equate a role with procurement authority. If exact regrouping
is unsupported, retain accurately labeled available counts and disclose the limit.
Separate function/title evidence from documented evaluation, selection,
implementation, operation, testimonial contribution, authorship and unknown
involvement. Testimonials and authorship are evidence relationships, not
organizational functions. Explain what people actually did, with examples, without advising
whom to approach or what conversations to have.

Function coverage and the People table use the same functional_role_frequencies.
If stating coverage, use `Named stakeholder profiles: N; Identified function profiles: N;
Named profiles with unknown function: N` from that object, never participation-node counts.

Buying situations: preserve four visible sections. A. Documented problems,
pressures and triggers is the main frequency table, with descriptions of the
observed constraint and its effect on the customer. Use semantic_kinds.trigger
counts rather than broader mentions/goals. Distinguish dated events from continuing
operating pressure and original adoption from later experiments or expansion.
B. Goals and deployment context explains intended work and actual architectures.
C. Requirements and selection criteria uses a separate table of documented needs
or capability usage, not prospect-qualification questions. D. Post-adoption outcomes
remains separate from original motives and forecasts. Describe actual examples,
revenue/adoption constraints, authentication/lifecycle needs, delegated identity,
launch/rollout events, and architecture differences where supported. Do not suggest
how the target should sell, position, qualify, prioritize or demonstrate its product.
A competitor's published capability is not evidence of equivalent target support.

When selection_evidence_kinds=true, the Requirement table must distinguish
`Stated requirement: CATEGORY` (semantic_kinds.requirement) from
`Documented use: CATEGORY` (semantic_kinds.descriptive), using each kind's profile
count/share, not the category's combined total. Include every nonzero documented-use
row. Unknown selection reasons do not negate known capabilities or workflows used.
Keep CATEGORY exactly as supplied; the prefixes identify evidence kinds, not new categories.
Keep reported outcomes separate; never relabel usage as a criterion or motive.

Methods and sources: show a simple complete Provider | Eligible case entries table
and the verified Sheet URL. Explain entries versus preserved profiles, exact-name
normalization and source-supported aliases, compilations, ambiguous/anonymous
identities, denominators, exclusive primary types versus overlapping dimensions,
unique-profile unions, Other/Unknown/missing evidence, and inaccessible records.
Documentation and compilations can establish usage more strongly than original
buying causation. Explain source strength, chronology, provider selection bias and
concentration, and the limits of inferring purchase motives, authority, company
size or market opportunity. Describe what the dataset establishes and cannot
establish; do not end with instructions for constructing a GTM strategy. Omit
hashes and pipeline mechanics unless necessary for reproducibility.

Preserve useful depth, complete defensible frequencies, concrete examples, source
references and important differences. Use readable tables followed by descriptive
interpretation. Do not impose arbitrary simplification or word-count targets.
The Overview is compact by layout and selection, while detailed tabs may be longer.
For deterministic reconciliation, use these exact table headers (empty tables
with headers are valid when that evidence is absent):
Company type | What it sells / does | Count | Share;
Functional role group | Representative actual titles | Count | Share;
Recurring situation | Business significance | Profiles | Share;
Deployment context | Profiles | Share;
Requirement | Profiles | Share;
Reported outcome | Profiles | Share;
Provider | Eligible case entries.
Copy category labels exactly from the supplied hierarchy or functional frequencies.
All profile-table shares use the overall preserved-profile denominator; provider
rows count eligible entries, not profiles. Include every nonzero company type and
functional group; zero-count scaffolding may be omitted. Other dimensions overlap
and their tables do not need to sum to the denominator. Include a table even when
there are no supported rows, and explain missing evidence without inventing it.
Do not repeat frequency tables in the Overview; use the compact claims above.

No hidden weighting or exclusions. Distinguish observations, derived frequencies
and carefully qualified descriptive inferences. Approved product context defines
scope and factual capability limits, not positioning or selling recommendations.
