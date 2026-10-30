# Codex app operating loop

Use the already-connected Google Drive plugin. No OAuth files, service accounts,
Google API keys, model API keys or separate paid APIs are part of this project.
The app is the Google Workspace adapter. Fresh `codex exec` workers do research
and analysis, never Workspace publication.

## New-run execution policy

New company runs select only the first 30 distinct entries in each provider's
primary customer-story listing, in natural listing order. Irrelevant and failed
entries consume slots; never replace them or inspect publication dates. Stop at
30 or verified listing exhaustion. No extra case searches or alternate archives.
The historical exhaustive-coverage descriptions below remain for replay only.
`enable-listing-boundary RUN` backs up an unfinished historical run and enables
the same boundary without changing saved decisions, extractions or Workspace IDs.
It does not resume research. Listing-only recovery witnesses natural order before
unfinished cases become eligible. Never substitute historical discovery order.
Observed titles and positions establish listing slots independently of hrefs.
Unresolved destination URLs remain null, consume slots, and never enter source
screening/extraction queues or Sheet rows. Do not associate tentative old links. A bounded candidate check may establish a
content-confirmed source association from a saved excerpt/full text; preserve the
listing href as unverified and checkpoint the association separately. Use saved
links first, using the normal source/time budgets and at most one focused query
and two candidate-source accesses per assigned card. No two-access provider cap.
Listing captures preserve witnessed redirects/canonical URLs and their evidence.
Fresh runs require witnessed pagination/Load More/offset continuation. A blocked
control or repeated page closes incomplete coverage with a specific limitation,
never invented exhaustion. Incomplete coverage is carried into report Methods.
An exhausted six-card listing closes at six without replacement discovery.
All prior completed records remain publishable, including records outside the
new boundary. An unavailable or unverifiable listing pauses with a specific error.
Final worker responses use compact completed_ids for streamed records; Python
materializes replay caches from verified checkpoints. Actual CLI source-access
events (including batched open_page/find_in_page/other views) enforce the existing
source budget, with durable completed prefixes retained at bounded yields.

New company runs use taxonomy-first analysis. Historical runs retain their saved
policy and receipts; do not migrate or rerun Linkrunner as part of implementation.
Metadata discovery defaults to 100 candidates; uncertain deep review and extraction
remain up to 20 cases. Clearly relevant metadata goes straight to extraction.
Actual assigned-case plus capture bytes, observed source-access attempts and wall
time independently bound research. Completed prefixes survive budget yields;
unfinished cases get fresh assignments. Quota/error pauses never auto-retry.

Inventory receives listing/search metadata and product scope. Deep workers receive
only assigned cases, captures and known failures. Successful captures are not
silently truncated. Known failed assigned sources resolve locally; linked failed
URLs remain in a durable failure index and must never be reopened. No PDF rescue.

New Sheets contain exactly the five established columns and complete accessible
cases only. Inaccessible records stay in extracted.json and inaccessible_audit.json.
Accumulate groups of 100 complete rows (then flush the remainder), retain destination
preflight/collision checks, verify each changed range, and perform one final whole-grid
consistency check. Sheet reads request values/validation rather than unused cell formats.
Creation identity, uncertain-write recovery and native Doc structure checks still apply.
No normal PDF export, repeated cosmetic inspection or extra model verifier is required.

Production outputs use one five-column `Case studies` spreadsheet tab and five
native document tabs: Overview, Company profiles, People, Buying situations,
Methods & sources. The first tab is a concise one-page-style descriptive research summary, covering
Company profiles, People involved, Buying situations and a methodological caveat.
New Doc files and the displayed Overview use `[Company] | Working ICP`, without
internal run IDs. Overview category frequencies use native bullets under clear
headings with short paragraphs; the four detailed tabs retain complete analysis.
Reports contain no target-prioritization, outreach, positioning or sales advice. After
native report verification, the runner moves the four detailed sections into native
tabs, verifies their text/tables, and only then trims the original tab to Overview.
This deterministic presentation step does not rerun synthesis. Routine production
file creation, updates and verification are authorized by competitor approval;
temporary debugging/testing restrictions do not revoke that authorization.
For an already completed report, `organize-doc RUN --readback FILE` can reuse an
actual saved native Doc readback and drives the normal Workspace begin/tool/ack
loop. It reuses the same Doc and Sheet IDs and launches no research/model workers.

Stages 4–7 build a compact global taxonomy from ALL frozen Sheet evidence, using
bounded record-linked hierarchical synthesis where needed. Mapping uses fresh
workers with 60 cases by default and a fixed taxonomy, with Other and Unknown in
every dimension. Checkpoint groups remain up to five, validating only submitted
records and quotes; a cached immutable database index avoids rereading and expanding
all historical receipts for each ACK. A full classification audit runs once after
mapping. One focused global Other review adds supported themes and remaps only
Other observations through a derived overlay. Code computes unique-profile unions,
exclusive company groups, overlaps and provider/strength distributions. One editorial
report is generated and its sections supply Stages 4–7; no discarded category essays
or subsequent whole-taxonomy model reconciliation in this path.

Configuration (operator commands; users can simply request changes in chat):
- `recover-urls RUN` starts a backed-up local-only pass over existing unresolved
  listing slots. It reuses saved URL candidates and existing evidence validators,
  preserves completed records, respects known failures and normal review budgets,
  and holds published Sheet/Doc identities and analysis unchanged. `run RUN`
  continues bounded assignments; the terminal phase is `url_recovery_complete`.
  Publication of recovered evidence requires a later explicit instruction.
- Listing captures establish `observed_slots` independently of case checkpoints.
  Case results may arrive out of order; missing earlier decisions still block
  cursor advancement, and completion requires every witnessed selected slot to
  have a recorded decision or unresolved state. Captures alone never screen cases.
  Individual case reconciliation never completes a discovery job. Only the
  validated bounded-unit commit does so. For unfinished listings, replay current
  saved responses before new work; then rotate providers with saved unfinished
  slots by their existing coverage turns. An old job status cannot close a provider
  whose listing universe remains unfinished, and completed providers stay closed.
  A saved blocked listing capture with no witnessed cards may close scheduling as
  inaccessible/incomplete coverage, with unknown catalog size and explicit source
  evidence. It never establishes an exhausted or empty catalog. No case rows or
  screening decisions are manufactured; the limitation flows into report Methods.
- `recover-listing-events RUN` backs up and replays saved streamed events from the
  specific consecutive-prefix validation failure through current validators. It
  performs no research, preserves the pause and completed records, and records
  replay provenance. An explicitly authorized Resume then completes missing work.
- `narrow-approval RUN --remove 'Provider A;Provider B'` corrects an approval during
  early Stage 2 only when removed providers have no saved research/discovery
  checkpoints and Workspace publication has not started. It backs up the run,
  records the correction and preserves any pause. Resume remains a separate,
  explicitly authorized recovery. Providers with saved work require universe reconciliation.
- `configure-research RUN --discovery-batch-size 100 --review-batch-size 20`
- `configure-research RUN --max-source-attempts 60 --max-execution-seconds 1200 --max-context-bytes 180000`
- `configure-analysis RUN --batch-size 60 --max-input-bytes 180000 --taxonomy-input-bytes 180000 --taxonomy-max-categories 60`
- `configure-publication RUN --batch-size 100` (finish any pending write first)
- `metrics RUN` prints stage executions, model elapsed time, observed wall spans,
  work-type record counts, available token/cache counters, source accesses/repeated
  references, failures, checkpoints, planned/dispatched Workspace operations and
  human interventions. Missing token counters remain null, never invented zeroes.

The older compact/global-revision descriptions below document legacy compatibility;
the new-run policy above governs fresh runs. Exact begin/tool/ack recovery is unchanged.

1. Run `python3 runner.py app '<user message>'` from this project. Use proper shell
   quoting, or pass an argument array. This resolves/creates the run, approves the
   saved competitor names, or resumes existing checkpoints. Remember `APP RUN` ID.
2. If it stops at `awaiting_approval`, show the saved landscape table and sources,
   plus the researched product understanding, then wait for the user's competitor
   selection. For a revision, read `landscape_revision.proposal` from the checkpoint;
   the active landscape still represents the previous approved universe.
3. If a Workspace action is pending, use
   `python3 runner.py workspace RUN show`. This is the authoritative current action;
   request files are historical copies. Discover the named Google Drive connector
   tool if necessary. Never use a paid API, browser login workaround or fictional
   response in its place.
4. Before executing the exact tool and `arguments`, call
   `python3 runner.py workspace RUN begin --request-id REQUEST_ID`.
   Execute it once. Save the COMPLETE actual tool result as JSON in
   `runs/RUN/workspace/REQUEST_ID.tool.json`, then call
   `python3 runner.py workspace RUN ack --request-id REQUEST_ID --response FILE`.
   Use a file-writing tool or correctly quoted data; never put JSON into a shell
   command through unescaped interpolation. Do not summarize/retype a readback.
   The runner validates native MIME, identity, values, table/heading structure and
   checksums. It schedules independent readback after writes.
5. Run `python3 runner.py run RUN` and repeat steps 3–5 until complete. A task cap
   means start another bounded runner invocation automatically, not ask the user
   for another instruction. Wait/poll the existing shell session; never launch a
   second process for the same run. Keep the user informed during long executions.
6. At `complete`, show the saved verified native Sheet and Doc links and evidence
   limitations. Nothing is complete until the Doc content/structure readback passes.

## Recovery and exact stop rules

- Only on an explicit user decision to end research early, use
  `finish-collected RUN --reason 'user decision' [--recovery-file FILE]`.
  This backs up the run, validates collected records against committed receipts,
  preserves discovery/exhaustion checkpoints, and records partial coverage.
  The optional JSON list identifies already-observed cards by provider/position,
  a saved candidate URL (or null), and exact saved evidence path/quote references.
  It fits one existing review batch and permits at most one fresh recovery call;
  interrupted work reuses receipts and leaves unfinished cards unresolved.
  Continue `run` and the normal Workspace loop. The runner builds exact batches,
  uses the existing Sheet identity and frozen-Sheet checks, and supplies the
  partial-coverage disclosure to report synthesis. Future discovery policy is
  unchanged. Quota and integrity failures still stop immediately.

- Efficiency upgrades do not resume research: `upgrade-efficiency RUN` creates a
  backup, imports saved evidence/tool failures, and preserves phase, scope, jobs,
  inventories and records. `coverage RUN` is a read-only next-work proposal.
  New runs use the upgraded policy by default; old receipts remain replayable.
- Review batches default to 20 cases with independent case receipts emitted before
  the next reading. A partial batch preserves all validated cases. Use
  `configure-research RUN --review-batch-size N --reason 'observed constraint'`
  to change the size; reducing it requires a recorded execution constraint.
  Coverage rotates approved providers without using completed volume or repeated
  themes as priority penalties. Exhaust discoverable relevant accessible cases;
  no provider quotas or saturation stopping. Persist completeness and extraction
  counts, including unresolved/inaccessible cases. Analysis separately evaluates
  raw frequency, evidence strength, provider concentration and descriptive interpretation
  without silently changing observations, weighting or denominators.
  A legacy unpaginated inventory without a saved exhaustion checkpoint receives
  a discovery continuation, preserving every known URL, decision and extraction.
  It checks only for additional cases under the approved product scope.
- `publish-saved RUN` drives only the existing Workspace bridge while research
  stays paused. Repeat it and the normal Workspace begin/tool/ack loop until it
  reports verification. It initializes a single native Sheet when no identity is
  present, preserves a recorded identity, writes deterministic chunks, and reads
  the entire allocated grid back in bounded ranges to detect extra rows. It does
  not run workers, advance stages, or clear the research pause. Do not run `run`
  or `app Resume` during a publication-only instruction.

- `Rerun Stage 1 for Company` preserves a ZIP backup with a checksum manifest and
  runs only a new product-understanding/competitor proposal. Existing research and
  Sheet identity remain active until renewed approval. Stage 1 must not establish
  the ICP, buying situations or stakeholders. Product understanding is checksummed
  and passed into every fresh Stage 2/3 execution.
- Approval of a revised universe first reconciles saved case evidence in bounded,
  tool-free batches. It reuses relevant records unchanged, keeps recoverable prior
  data, preserves completed provider discovery and cursors, and invalidates affected
  analysis/report snapshots. Parent-vendor naming changes reuse existing provider
  keys only when the product label and supporting source host both match; a shared
  corporate domain alone cannot merge separate business lines.
  Uncertain relevance alone goes back to one-case review;
  an existing full extraction is reused. When a Sheet exists, execute the scheduled
  native backup, metadata verification, full-grid backup/readbacks and fixed-address
  compaction against that same Sheet ID. Conflicting edits halt without overwrite;
  lost write responses recover through preflight reads. No new research starts until
  reconciliation and synchronization finish. Without a Sheet, records remain local
  and sync at normal initialization. The prior narrow manual scope is superseded by
  the newly approved product understanding, while its history remains backed up.

- Stage 2 carries forward the saved competing product/business line and screens
  lightweight evidence in independently budgeted pages (100 candidates by default for new runs). The runner
  checkpoints page continuations and exclusions, and queues
  uncertain stories as bounded review batches (20 by default for upgraded runs;
  individual review receipts remain compatible with old runs). A relevant review saves its complete
  Stage 3 record during that reading. Early records remain local until Sheet
  initialization, or sync to the existing Sheet before further research. Stage 3
  skips every saved extraction. Never restart a completed provider to adopt the
  updated screening schema; legacy inventories and receipts remain usable.
  An explicit user-requested provider redo is the exception: before extraction,
  use `redo-provider RUN --provider NAME`, then resume normally. It archives the
  earlier provider inventory/decisions and uses a separate cache revision without
  changing other approved providers.
- Source PDFs get exactly one access attempt. A failed attempt or no readable
  text/image ends that case immediately: Stage 2 saves unresolved with no record;
  Stage 3 saves inaccessible with the actual limitation and continues the batch.
  Do not retry, render/OCR, switch tools/browsers, find alternate copies, or search
  summaries after that PDF fails. This explicit user limit overrides PDF skills.
  Reuse completed records and saved failures across interruptions. If an older
  worker is interrupted after an observed first failure, persist it without
  reopening via `mark-pdf-failed RUN --case-id ID --reason '<observed failure>'`.
  This command is restricted to unprocessed PDFs awaiting Stage 2 review and
  preserves completed records, provider progress and the current pause state.
- If review of saved evidence exposes a clear scope error during discovery,
  before batches or Workspace publication, use `exclude-case RUN --case-id ID
  --reason '<source-supported reason>'`. This runner-owned correction archives the
  complete record and prior decision, backs up the run, and removes only that case
  from active inventory/extractions. It preserves provider progress, worker caches
  and quota pauses. Interrupted corrections replay before the next research task.
  With an existing Sheet, an unverified case may be archived only before any write
  could have occurred. Its ready preflight/unissued write is retained in history
  and withdrawn; verified or possibly written rows remain protected.
  It cannot modify a published row; use the backed-up universe reconciliation
  workflow for published datasets. Shared functionality in an unapproved business
  line alone is insufficient evidence of the approved competing product.

- On any connector quota/429 or unrecoverable error, immediately call
  `workspace RUN fail --request-id ID --reason '<actual error>'` and stop. Do not
  retry, buy credits, schedule resumption or assume a reset time. Only explicit
  usage-exhaustion evidence is a subscription quota pause. Generic HTTP 429 and
  rate-limit responses, including CLI retry warnings, pause as unknown rate limits
  for manual review, retaining the raw diagnostic; they do not establish exhausted
  allowance or a five-hour reset. Other routine retry warnings are not quota errors.
  A later explicit Resume allows one new attempt. Python stops the worker before
  a scheduled retry when a quota or unclassified rate-limit response is observed.
- If an action was dispatched and the chat/process stopped, first look for its
  saved `.response.json` or `.tool.json`. Acknowledge that real response if present.
- A dispatched **creation** may have succeeded even if its response was lost.
  Search Drive for the exact unique title in the pending request. Require exactly
  one native file match, then use `get_file_metadata` to read its ID, native MIME
  and URL. Save and acknowledge that actual metadata response. The runner then
  verifies its content. Never import/create a second file automatically. If no
  match or multiple matches exist, pause and report the uncertainty; creation
  retries require resolving the original outcome first.
- For a dispatched non-create action, after explicit Resume use `workspace RUN
  retry --request-id ID`. Reads may repeat once. An uncertain Sheet write changes
  into a preflight read of its deterministic destination. Existing exact rows are
  accepted; blank rows may be written; conflicting rows pause without overwrite.
- If the tool is unavailable, `workspace ... fail` with the exact tool name and
  error. Report the capability blocker; do not claim successful integration.
- If shell sandboxing prevents Codex CLI startup/session writes, request the
  platform's narrowly scoped execution approval. Never silently bypass sandboxing.
- Stages 4–7 receive only `finalized_sheet.json` and completed analyses through
  their fresh execution prompt. Web search, shell, apps and user MCP configuration
  are disabled, and any observed tool activity rejects output. Never independently
  browse or expand their evidence. The immutable snapshot was read back from the
  entire native Sheet and compared with every saved record, including inaccessible
  flags. It is the analysis version even if someone later edits the live Sheet.
  Datasets larger than the analysis batch size use `analysis_pipeline.py`:
  classify every complete Sheet row in configurable bounded groups (default 20,
  60,000 UTF-8 evidence bytes plus bounded metadata), persist each classification immediately, and
  reuse it across buying/company/stakeholder analysis. No source captures or
  non-Sheet case notes enter those classifications. Persisted taxonomy partitions
  account for every emergent label; Python aggregates distinct-profile sets,
  overlap, provider concentration and evidence-strength counts. The coverage audit
  accounts for every eligible/inaccessible row and the exclusive primary-company
  denominator. Anonymous profiles and unproven aliases stay separate with a
  disclosed limitation. After record classification, semantic_synthesis.py reconciles the COMPLETE
  cross-batch vocabulary, record/profile associations and Sheet evidence into a
  hierarchical taxonomy before report generation. Original labels and evidence
  remain immutable. Python unions profile IDs at every hierarchy level and
  distinguishes causal triggers, goals, requirements, benefits, outcomes and
  uncertainty. A selective cohesive report replaces raw taxonomy dumps; the full
  hierarchy and every association remain in the local audit. Large catalogs stop
  explicitly at their independent context bound rather than silently truncating. One fresh execution per runner step preserves task caps.

## Minimal disposable integration check

`python3 runner.py smoke-init --id disposable-UNIQUE` creates one clearly synthetic
case and a pending Sheet import. Drive its Workspace loop with the fake offline
worker (`run ... --codex /absolute/project/tests/fake_codex.py`). This exercises
native import, fixed-address writes, full readback, frozen snapshot, saved analysis
handoffs and native report import/readback without researching any company. Delete
only the two exact verified disposable Google files afterward. Retain local logs
as evidence. Offline tests must never invoke connected tools.

## Compact analysis checkpoints

`configure-analysis RUN --batch-size 60` independently configures classification,
without resuming the run or changing extraction batches. Existing classifications
are immutable. Saved labels are first reconciled into a preliminary shared taxonomy.
Compact workers use only frozen Sheet rows and the local `analysis_checkpoint`
MCP `save_records` tool, in groups of at most five. Validated per-case receipts
are atomic and survive worker interruption; the final ID receipt cannot replace
checkpoints. New categories receive stable IDs and undergo final reconciliation.
No web, shell, source files or Workspace tools are enabled. Unknown 429 errors
still pause without retry or scheduled reset assumptions.

The compact worker uses only
`mcp_servers.analysis_checkpoint.tools.save_records.approval_mode="approve"`
and `enabled_tools=["save_records"]` in its invocation config. This authorizes
only the manifest-bound local checkpoint tool; the read-only worker sandbox,
disabled web/shell/Workspace tools and noninteractive approval policy remain.
A transport-versioned assignment key preserves old failed responses without
replaying their empty completion receipt after an authorization repair.


## Global semantic report revisions

`python3 runner.py synthesize-analysis RUN` backs up an existing run, reuses every
immutable classification and profile identity, reconciles five global dimensions,
and saves a new editorial report without research or changing native outputs.
Each global map is input-checksummed and durable; interrupted executions reuse
completed maps. A failed or rate-limited worker pauses with raw diagnostic evidence.
The operator then backs up both native outputs, validates the synthesis against
the complete ledger, publishes to the SAME IDs and verifies content/basic layout.
The five-column user-facing case tab contains complete cases only; inaccessible
rows remain in a local audit ledger. A checksummed publication projection links
this cleaned view to the unchanged frozen evidence database so classifications
retain their original provenance. Never rewrite immutable evidence checksums to
match a publication-only cleanup.

`publish-synthesis RUN --backups FILE --preflight FILE` validates actual native
backup receipts and a complete Sheet preflight, removes only inaccessible rows,
verifies the 467-row publication projection, and rewrites the existing native Doc
with revision guards and compact native tables. Continue its Workspace begin/tool/
ack loop; each ACK queues the next exact publication action. A lost destructive
write response must be reconciled against the native file, never blindly replayed.
After complete content/heading/table readback the runner marks the revision done.
No PDF export is needed for basic native structure verification.
