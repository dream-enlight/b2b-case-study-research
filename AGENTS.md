# B2B competitive case-study research

## Codex app operator

When the user asks to operate research, translate these messages automatically:

- `Research [company] — [website]` -> `python3 runner.py app '<exact message>'`
- `Approve these competitors: ...` -> the same `app` command; use `--id` from this
  chat when multiple runs await approval.
- `Resume [company]` -> the same `app` command. This explicitly authorizes one
  bounded recovery attempt, including a quota retry; stop again if still limited.
- `Rerun Stage 1 for [company]` -> the same `app` command, using this chat's run ID.
  It backs up the existing run and creates a separate proposal. Stop for renewed
  approval; do not resume case-study research or change the active dataset yet.

Pass messages as properly shell-quoted arguments. Never interpolate untrusted
message text as shell code. Do not ask the user to run terminal commands.

Read `APP_WORKFLOW.md` before the first operation. Continue its loop automatically
after approval through Stage 7, including Workspace actions and task-cap stops.
Stop only for competitor approval, quota/error, a required clarification, or verified
completion. Never ask for separate instructions to start the next approved stage.

Competitor approval authorizes routine production creation, updates and verification
of the required native Google Sheet and Doc. Temporary restrictions imposed for
debugging/testing apply to those activities; they do not revoke the approved
production workflow unless the user explicitly says so.

The output template is a single five-column `Case studies` Sheet tab and a native
Google Doc with these five tabs, in order: `Overview`, `Company profiles`, `People`,
`Buying situations`, `Methods & sources`. Keep the Overview concise enough for one
page and the detailed findings in the other tabs. Native tabs are not merely body
headings. Preserve complete analysis, counts, caveats, source associations and
tables; organize the saved report without another model call. Do not add provider
tabs to the spreadsheet by default.

This is a descriptive competitive case-study research system, not a strategy
recommendation system. It organizes, quantifies, consolidates and explains saved
evidence; the human researcher independently develops GTM hypotheses afterward.
Reports answer what companies occur and what they do, which people/titles/functions
and involvement appear, and which problems, events, goals and requirements recur.
They do not recommend target segments, commercial priorities, outreach, sales
questions, positioning, GTM motions or proof-of-value exercises. Attributed customer
decisions are source observations, not advice by the agent.

Overview uses concise one-page-style sections Company profiles, People involved,
Buying situations and a brief methodological caveat. Do not add GTM implications.
Company profiles retain the complete exclusive table: Company type; What it sells /
does; Count; Share, including Other and Unknown with reconciled denominators.
Explain actual businesses, integration contexts, meaningful differences and provider
concentration without converting patterns into recommendations.
People tables contain actual functions/titles and reproducible profile counts;
evaluation, selection, implementation, operation, testimonials and authorship remain
separate. Generic builder descriptions are not formal job titles. Missing functions
and purchasing authority stay unknown rather than inferred. Buying situations keep
problems/pressures/triggers, goals/context, requirements and outcomes separate,
with chronology, customer examples and caveats. Methods describe provider coverage,
profiles versus entries, deduplication, overlap, ambiguous identities, source bias,
missing evidence and what the dataset can and cannot establish. No strategy section.
Preserve useful analytical depth and source references; no arbitrary simplification
or word-count targets. Do not rerun classification or research for framing edits.

The operator may drive the runner through all authorized stages. The following
bounded-worker rules apply to fresh executions receiving a stage assignment.

## Bounded research / analysis workers

Read the stage prompt assigned by the orchestrator; do not independently progress to another stage.

- Treat published case studies as evidence. Never invent companies, source URLs, buying reasons, or decision-making authority.
- Stage 1 researches and saves the target's product workflow, capabilities, evidence and uncertainties before evaluating direct product substitutes. Do not establish the ICP, buying situations or stakeholders in Stage 1. Every fresh Stage 2/3 task receives this saved product understanding.
- Preserve the specific competing product/business line and shared customer need saved during Stage 1. Company approval never makes unrelated product stories relevant.
- Stage 2 discovery primarily screens titles, categories and summaries. Persist relevant, excluded (with reason), and needs-review decisions. If substantive reading occurs, extract the complete relevant record during that reading and emit its case checkpoint immediately; never defer a completed reading to another worker.
- Upgraded workers review 20 assigned cases per execution by default. Emit each case result immediately before reading the next case; Python validates and persists individual records and decisions. Interrupted batches resume only unfinished cases. Batch size is configurable through `configure-research`; reductions require a documented actual execution constraint, never an automatic arbitrary reduction. Metadata discovery has an independent configurable budget (100 new candidates by default), with a precise saved continuation. This never authorizes 100 deep reads. Actual case-plus-capture byte constraints may bound an assignment; persist the measured reason without silently reducing the configured review default.
- Use supplied evidence memory, source captures, product scope and known tool failures across fresh executions. Ordinary JSON research workers receive a concise writing contract and schema in an isolated execution with web search; do not reload private reference files, spreadsheet skills, unrelated project material, browsers or shell networking. Metadata is not full source text, and missing legacy fields must not be invented.
- Collection rotates approved providers without penalizing publication volume or repetitive buying situations. Collect all discoverable relevant accessible cases; no total limits, provider quotas or thematic-saturation stopping. Contribution notes describe observations, never eligibility. Track inventory completion, extraction and access limitations per provider.
- Stages 4–6 distinguish raw frequency, evidence strength, provider concentration and descriptive interpretation. Preserve valid observations and denominators; clearly label analytical judgments without silent exclusions or weighting. Stage 7 carries those distinctions into the overview.
- Large finalized datasets use bounded shared record classification for Stages 4–6, with individual immutable receipts and complete-dataset frequency aggregation in code. Use only verified Sheet cells; never sample, truncate records, reconstruct source research or infer aliases/authority. Named profiles merge only on normalized names or Sheet-supported aliases; anonymous labels remain separate. Buying situations and stakeholder roles may overlap; primary company categories are exclusive. Python verifies every eligible record and profile denominator before narrative synthesis.
- Completed records and screening decisions are durable checkpoints. Never repeat completed discovery or extraction to adopt a newer prompt/schema. Stage 3 receives only relevant cases that lack an extraction. New runs accumulate up to 100 complete accessible records per Workspace group and flush the final remainder, with fixed row addresses and readback, preserving the native Sheet identity. Inaccessible records remain local.
- On approval of a revised universe, the runner reconciles saved evidence in batches of at most 20 without web research. It retains unchanged relevant records, archives exclusions, invalidates affected downstream analyses, and reconciles the same Sheet after a native backup and independent readbacks. Never replace that Sheet or manually edit checkpoint state.
- When the user explicitly requests a provider redo during discovery, use `runner.py redo-provider RUN --provider NAME` before resuming. This archives that provider's earlier decisions and isolates new worker caches. Do not edit run state manually or redo other completed providers.
- A verified scope error found before batching/publication may be corrected through `exclude-case RUN --case-id ID --reason '<source-supported reason>'`. This archives the previous decision and extraction, preserves other work and quota pauses, and removes only that case from active data. Never edit real run JSON manually. A generic shared feature in an unapproved business line does not establish use of the approved product.
- The public output contract is `docs/output_contract.md`; no private reference files or previous run data are required.
- During Stages 1–3, web research is allowed. After Stage 3, use only the finalized case-study database and completed analyses, with no additional web research.
- The runner owns checkpoint state and batching. Do not edit `runs/*/state.json`, add unassigned cases, or alter previously finalized records.
- Output exactly the requested structured JSON; the runner validates it and saves it.
- Compact analysis assignments additionally use only the assigned local
  `analysis_checkpoint.save_records` tool for validated incremental persistence,
  before returning the final ID receipt. This tool cannot modify source Sheet rows.
- A usage limit, unavailable connected app, or inaccessible material must be reported, not bypassed by fictional data.
- Try each PDF only once. If that attempt fails or yields no readable text/image, immediately persist an unresolved Stage 2 decision or inaccessible Stage 3 record and move on. Do not retry, switch tools/browsers, render/OCR, search summaries or find alternate copies for that failed PDF. This user limit overrides PDF-skill fallback workflows; previously saved records and access failures remain checkpoints.

## Project maintenance

Implementation and tests may edit code, documentation and synthetic fixtures.
Never edit real `runs/*/state.json` manually or modify original source evidence. The runner
owns state transitions. Run `python3 -m unittest discover -s tests -v` after changes.

## Global analysis synthesis

New runs build a coherent taxonomy from the entire finalized dataset BEFORE
mapping individual records. Large evidence sets use bounded hierarchical synthesis
with record-linked intermediate checkpoints. Map 60 cases per execution by default
using compact fixed category IDs/definitions. Allow meaningful Other observations
with specific descriptions and Unknown/insufficient evidence in every dimension.
Review Other globally once and remap only affected observations through a separate
overlay; preserve original receipts. Never grow a registry during normal mapping
or run a second full analysis that will be discarded.

Keep original descriptions, quotes and record associations in the local audit.
Compute frequencies from unique profile unions in code; primary company types
are exclusive, situations and roles overlap. Separate causal pressures, goals,
requirements, context, benefits, outcomes and uncertainty. Full source/classification
integrity is audited once at completion; individual checkpoints validate new work
and exact evidence associations. The reader-facing report selects useful patterns,
compact frequencies, job-title examples, provider concentration and descriptive interpretation.

Historical analysis/revision paths remain replayable. Existing report revisions use
`synthesize-analysis` and `publish-synthesis`; never rerun research or original
classifications to adopt the new architecture. Run offline tests after code changes,
not normal research batches. Quota exhaustion stops immediately without retry or
an assumed reset time; completed checkpoints remain durable.

## Public setup and portability

Before the first real run, verify Python 3.11+, an authenticated `codex` CLI, and the compatible native Google tools described in `docs/google_tools.md`. Run `python3 scripts/check_setup.py` and the offline tests when asked to check setup. There are no third-party Python dependencies or project API keys. Do not invoke real workers or connected Google tools for offline tests. Do not treat the placeholder Research command in the README as an execution request.

Use macOS/Linux; native Windows is unsupported. Runtime directories are created by the runner; no saved runs or private reference documents are prerequisites. Do not infer connector compatibility from a generic Google connection. Stop clearly if required tools or credentials are unavailable; never invent an adapter or result.
