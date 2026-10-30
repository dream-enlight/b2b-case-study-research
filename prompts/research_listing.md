Account for up to max_cases METADATA positions from the saved cursor. The universe
is exactly the first 30 DISTINCT entries in the primary customer-story listing's
natural order, or fewer if the real listing ends. Irrelevant, inaccessible and
URL-less entries consume slots; never replace them. No date selection, invented
pagination, extra archives or case searches after selecting this prefix. A focused
official-site search may locate the primary listing if unknown.

Capture observed listing evidence before its case checkpoints, optionally in the
same envelope. Use role="listing", positions_verified=true, and ordered_entries
containing position, exact title, url and url_status for each witnessed card.
Resolved URLs require actual observed destinations. Unknown URLs remain null with
url_status="unresolved", decision="unresolved", reading_depth="lightweight" and
record=null. This preserves a slot for ordinary later resolution, not a completed
source case. No guessed URL, tentative old-case match, or extraction for a URL-less
card. Case rows include listing_position and listing_url. Use global consecutive
positions, counting duplicate visible cards only once; title equality alone does
not prove two cards are duplicates. Use actual hrefs or stable card IDs.

selected_listing_entries are compact saved positions, not work to reread.
observed_listing_slots are witnessed positions still needing checkpoints. Include
known completed sources in their natural slots without reopening/reclassifying
them. Account for earlier missing positions before advancing the cursor. Python
retains the full listing and verifies every position and source association.

For listing_contract_v2, source_capture includes continuation={"kind":
"link|load_more|offset|exhausted|blocked","target":"exact next_cursor",
"evidence":"observed control, ending or access limitation"}. Follow actual links
and Load More controls; offsets may resume within a saved page. Real exhaustion
sets listing_exhausted=true, has_more=false, next_cursor="". At 30, stop with empty
continuation. Repeated/inaccessible continuation uses kind="blocked" with the
actual limitation, listing_exhausted=false, has_more=false and matching target;
never claim the listing ended because the execution budget ended.

Screen from titles, categories and summaries. Relevant/uncertain metadata can
queue relevance/extraction work without opening every story. If substantive
reading is necessary, complete and checkpoint that case immediately, within the
separate review_batch_size limit (default 20). Return order_verified=true only
when actual natural order is witnessed; otherwise report the limitation.
