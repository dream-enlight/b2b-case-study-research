For the assigned provider, discover published customer case studies about the specific competing product or business line supplied in competing_product. Apply any explicit research_scope as well. Do not expand to the vendor's other products just because the company was approved.

Comprehensively enumerate all discoverable relevant published cases. Twenty is a per-execution bound, never a provider quota. Neither a large existing inventory nor repetitive buying situations justifies deprioritization, exclusion or thematic-saturation stopping. Complete inventory only after relevant discovery paths are exhausted; preserve unfinished paths in the cursor. Do not retry saved access failures.

PDF access is limited to ONE attempt per PDF. If the first attempt fails or returns no readable text or image, stop that case immediately. Do not retry, download again, render/OCR, switch tools or browsers, look for alternate copies, or search for summaries to rescue that failed PDF. Return decision=unresolved, record=null, and the actual access limitation; then the runner moves on. This explicit user limit overrides PDF-skill fallback workflows. Reuse already saved records and failure decisions rather than reopening their PDFs.

Use the supplied, saved product_understanding as the controlling description of the target's capabilities. Do not reconstruct it or substitute assumptions based on similar terminology. Case relevance means documented use of a competing capability or workflow, not necessarily repair of an existing attribution failure. Missing numerical outcomes or procurement detail alone does not make a case irrelevant. When an approved revised product understanding supersedes older manual scope filters, use the revised understanding.

The approved competing product/business line is also a boundary: shared functionality alone does not qualify a story about another, unapproved product. For example, a story documenting only Adjust Automate's reporting or bid/budget controls does not establish use of approved Adjust Measure or deep linking. Require source evidence of the approved product or its attributable workflow; mention of a vendor or a generic KPI is insufficient. When a story covers multiple products, retain it only if the in-scope use is independently established, and distinguish the other products in the extraction.

Upgraded executions use research_worker.md: configurable 20-case review batches,
individual streaming checkpoints, saved source/failure memory, and progressive
coverage. If substantive reading occurs during discovery, return and checkpoint
the full record immediately. The contracts below remain for legacy receipt replay.

The legacy runner assigns one of two bounded Stage 2 tasks:

**discover — lightweight inventory and screening**

- Use case-study titles, product/category labels, listing summaries, and search snippets to screen candidates. Do not read individual stories substantively in this task.
- Screen at most 20 new candidates per fresh execution, counting relevant, excluded, and uncertain cases toward the same limit. Start at the supplied cursor and skip known_case_urls. A larger provider is processed through successive checkpointed pages; the limit is per task, not a cap on its total inventory.
- Return has_more=true and an advancing next_cursor identifying the next listing/page/offset when more candidates remain. Stop this execution at 20 rather than screening the rest. At the end return has_more=false and next_cursor="". Preserve a precise continuation when a listing page itself contains more than 20 candidates.
- Return the customer (where available), title, original URL, decision, scope-based reason, and the lightweight evidence for each screened candidate.
- Mark relevant when the lightweight evidence establishes the competing customer need. Mark excluded when the evidence clearly concerns another product or need; persist its reason rather than silently omitting it.
- When relevance requires reading the story, mark needs_review. Do not conduct that reading now: the runner queues one bounded review so its outcome can be committed immediately.
- Follow product-specific listings and focused searches. Avoid exhaustive exploration of unrelated business lines, translated duplicates, or broad vendor archives. Do not impose an arbitrary cap on relevant cases.
- Before falling back from JavaScript pagination to repeated searches, check the official listing for a "View all" or static archive link. For example, Adjust's listing links to https://www.adjust.com/resources/case-studies/all/ (verified through the public listing). Reverify navigation hints, use the archive as inventory evidence, skip known URLs, and screen at most 20 new candidates rather than the whole archive in one execution.

**review_case — substantive reading and immediate extraction**

- Read only the assigned uncertain case. Use the saved competing_product, research_scope, and screening_evidence.
- If saved_record contains a complete earlier extraction, reuse it. Resolve relevance from the saved evidence wherever possible; do not repeat profile, people or buying-situation research. A relevant decision may return record=null when saved_record is already complete; the runner retains that record unchanged.
- If relevant, extract the COMPLETE Stage 3 record during this same reading, following the supplied extraction requirements. Return decision=relevant and the record. Do not leave profile, people, or buying-situation research for a second reading; explicitly distinguish facts unavailable in the source.
- If irrelevant, return decision=excluded, record=null, and the source-supported reason. Do not extract or publish an irrelevant case.
- If access limitations prevent a relevance decision, return decision=unresolved, record=null, and the actual limitation. Do not equate unavailable evidence with irrelevance.

Python saves each discovery page and continuation, and each returned review and full record, before another fresh research task. Substantive reviews remain one case per execution. It retains local records when no Google Sheet exists and synchronizes them through the existing Workspace bridge when available. Workers do not write files or connected apps themselves. Do not reopen completed cases or conduct frequency/ICP analysis in Stage 2.
