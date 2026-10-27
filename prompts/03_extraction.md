Using the approved case-study inventory, research each case study and populate a single Google Sheet using the five-column output contract in docs/output_contract.md.

Upgraded workers use the concise research_worker.md quality contract and supplied
schema instead of opening local references or spreadsheet skills. Use saved source
captures and known failures first. The default batch size is 20, configurable by
the runner; emit an individual extraction checkpoint immediately after each case.
Interrupted batches retain completed cases and receive only unfinished URLs.

PDF access is limited to ONE attempt per PDF. If the first attempt fails or returns no readable text or image, stop that case immediately, return status=inaccessible with the actual limitation in note, and continue with the next assigned case. Do not retry, download again, render/OCR, switch tools or browsers, look for alternate copies, or search for summaries to rescue that failed PDF. This explicit user limit overrides PDF-skill fallback workflows. Do not fabricate the unavailable fields or retry previously saved failures.

The runner assigns only relevant cases that do not already have a complete or inaccessible extraction. Stage 2 may already have extracted a case while resolving relevance; those records are final and must not be researched again. Apply the supplied competing_products and any research_scope, focusing buying situations on the competing product rather than the vendor's broader portfolio.

Use the supplied, saved product_understanding to interpret the target's capabilities and competitive overlap. Do not research or reconstruct the target product again, and do not turn its product description into assumed ICP, buying-situation or stakeholder findings. Those findings must come from case-study evidence.

**Extract five fields per case study:**

1. **Case-study source:** Provider name and original source URL.
2. **Customer company:** Name of the company featured in the case.
3. **People involved:** Names, titles and relevant involvement of individuals mentioned. Distinguish documented buying/evaluation involvement from people merely quoted. Do not assume someone was a decision-maker without evidence.
4. **Company profile:** A concise description of what the customer company does, its product or service, and its relevant business context.
5. **Buying situation:** A detailed, self-contained account of why the company needed the solution. Capture the existing approach, problems, business consequences, triggers, requirements, alternatives considered and reasons for choosing the provider wherever the source establishes them.

**Research quality:**

Extract every relevant accessible assigned case, even for heavily represented providers or repetitive buying situations. Preserve all valid observations. Do not apply provider quotas or thematic-saturation stopping rules; judgments about GTM importance belong to analysis, not collection. Reuse recorded failures without repeating unsuccessful access.

The database must contain enough information to support later ICP and buying-situation analysis without reopening the case-study links.

Preserve meaningful details and distinctions. Separate the original buying situation from results achieved after implementation. Do not invent missing facts or infer decision-making authority from job titles. Where important information is unavailable, make that clear.

Preserve self-contained source evidence using the five columns listed above; no private reference file is required.

**Execution:**

- Process cases in batches, generally one provider at a time. Combine smaller providers when the batch remains around 20 cases or fewer.
- Read the case-study content and extract its information in the same batch. Avoid unnecessary rereading.
- Process exactly the assigned unprocessed URLs. Do not revisit saved Stage 2 extractions, completed Stage 3 records, or excluded cases.
- Append each completed batch to the **same Google Sheet**, without duplicating existing records.
- Save progress after each batch so interrupted work can resume.
- Flag inaccessible or unresolved cases rather than silently dropping them.

Once all inventoried cases are processed and the database is checked for completeness, finalize the Google Sheet.

Do not conduct frequency analysis or generate the ICP report in this stage.
