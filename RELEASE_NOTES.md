# Release notes — 2026-10-30

This update makes bounded research collection, interruption recovery and worker usage easier to verify.

- New runs collect the first 30 distinct natural listing positions per approved provider. Metadata enumeration finishes before URL resolution. Exclusions and access failures consume slots; blocked navigation records incomplete coverage and releases saved work.
- Listing identity is separate from source identity. Distinct cards sharing one URL retain their positions and share one extraction; repeated stable card IDs do not create phantom missing positions. Per-position receipts and saved-output replay preserve these distinctions.
- Research workers receive a common contract plus only their assigned task, scoped product context and relevant memory. Substantive readings emit complete evidence and extraction checkpoints immediately, including combined capture-plus-case messages.
- Recovery preserves partial outcomes, replays saved outputs before requesting new work and keeps validated completed records immutable. Later valid extractions can complete pending metadata without another reading. Missing evidence remains pending rather than being invented.
- URL-less cards remain schedulable until a bounded attempt records a terminal result. The resolution prompt explicitly uses the assigned listing position.
- The read-only `usage-report` command reports available per-worker and aggregate token, cache, request-context, tool, outcome and recovery measurements. Unavailable counters stay unknown.
- Saved-evidence collection can be finalized through the bounded `finish-collected` workflow. Native document publication preserves detailed analysis while keeping the Overview concise.

Existing runs retain their saved collection policy and completed evidence. This update does not require rerunning research or classification. Google output identities, five Sheet columns and five native Doc tabs remain the output contract.

Validation: all 347 public offline tests pass. The setup check passes for 16 runtime imports, 21 prompts and the blank seed workbook. The repository includes synthetic offline regressions and portable setup checks. Live model behavior, website access and Google connector compatibility still depend on the operating environment. No research datasets, private reference documents or account logs are included.
