Checkpoint protocol: emit a plain JSON COMMENTARY/agent message directly. Python
consumes item.completed agent_message events; --output-schema constrains the FINAL
response only. No tool call, placeholder print, artificial continuation or ACK is
needed. In particular, never use functions.exec/text/notify to print checkpoints
or strings such as "Checkpoint prepared" or whitespace. Continue with real work
or return the final receipt after emitting the checkpoint.

Prefer one envelope per completed case, combining faithful evidence and its result:
{"source_captures":[{"url":"original source URL","coverage":"excerpt",
"text":"faithful evidence"}],"CHECKPOINT_KEY":{...complete row...}}
Use CHECKPOINT_KEY for this assignment. Emit captures in dependency order (listing proof
before case source if needed); Python saves and validates all captures before the
case. If further reading of the same case is needed, emit its source-only evidence
before that access. Legacy {"source_capture":{...}} remains accepted.

Capture coverage is full_text|excerpt|summary|metadata|failed, faithful to the
actual content. Prefer excerpts sufficient for all record fields. Preserve original
URL; add resolved_url/resolved_url_evidence or canonical_url/canonical_url_evidence
only for witnessed equivalence. A snippet is not full text. A failed capture states
the actual limitation. Keep source text sufficient to validate every association.

Completed full rows are emitted once. The final response uses completed_ids for
already streamed rows, with cases/results/records containing only unstreamed rows.
Use assigned IDs for review/extraction. First-30 discovery and resolution use
"listing:N" for every position, including resolved/shared source URLs. Historical
discovery without listing slots uses exact source URLs. Source-case
identity is provider plus normalized URL, not customer name. Preserve multiple
customer associations on one source without creating another record for that URL.
Never omit completed IDs, fabricate receipts or change an emitted complete record.
