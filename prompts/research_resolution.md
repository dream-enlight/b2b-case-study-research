Resolve ONLY recovery_slots. Preserve each assigned listing_position, listing_url,
title and customer exactly. The first-30 order is already frozen, even if listing
enumeration is closed. Do not reconstruct the listing, add/replace cards or open
another archive. Python retains the full listing for validation.

Use saved_candidate_urls and saved source evidence first; candidates are NOT
verified destinations and metadata is not article text. Then expose the assigned
card's actual link on the original listing. If links cannot be exposed, allow at
most one focused exact-title/customer query and two candidate source accesses per
card, within work_budgets. No broad searches or retries of recorded access failures.

For an actual followed link, emit a listing source_capture at the assigned
listing_url with role="listing", positions_verified=true and ordered_entries
containing only that position/title/destination, url_status="resolved". Its text
states which observed card/control was followed and the returned destination.
Emit the case with url_status="resolved".
For a source found without an observed href, emit a source_capture at that source
with coverage="excerpt" or "full_text" and listing_association={"listing_url":
"assigned listing URL","position":"<assigned listing_position>","title":"exact assigned title","quote":
"verbatim source excerpt"}. Replace the position placeholder with the assigned
integer. The quote must occur in text and identify the exact
title or a customer explicitly named in that title; generic resemblance is not
proof. Emit url_status="content_confirmed"; the original listing href stays unknown.
These proof captures and the case may share one checkpoint envelope.

Screen relevance from metadata first; read uncertain sources as needed. If
substantively read and relevant, extract fully before the next unrelated source.
A verified URL with insufficient relevance evidence may queue needs_review with
record=null. completed_sources contains only compact identities: reuse those
sources without reading or recreating their records; Python retains full records.
Unavailable/unassociable slots remain url=null, url_status="unresolved",
decision="unresolved", reading_depth="lightweight", record=null. State the actual
attempts/access/association limitation in reason and evidence. Only genuinely
attempted slots may receive this terminal result; leave budget-limited unattempted
slots unreported for the next assignment.

Final has_more=false, next_cursor="", listing_exhausted=false: this finishes the
assigned resolution task, not a new listing/exhaustion claim. Reference every
streamed slot as "listing:N" in completed_ids, including resolved URLs; two slots
may reference the same source while retaining distinct slot identities.
