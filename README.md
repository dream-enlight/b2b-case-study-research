# B2B Case Study Research

A Codex-native research agent that turns published customer case studies into an evidence database and a descriptive competitive research report.

For researchers who want to understand which companies use competing products, who appears in their customer stories, and which problems, workflows and requirements recur. Start with any B2B company and its website; competitors and categories come from the research rather than a bundled dataset.

## Start in Codex

1. Clone this repository and open its folder as a project in Codex.
2. Make Python 3.11 or newer and an authenticated Codex CLI available on your PATH. The runner starts bounded `codex exec` workers. See the official [Codex CLI setup guide](https://developers.openai.com/codex/cli/). Supported runtime: macOS or Linux. Native Windows is unsupported; WSL has not been verified.
3. Connect Google Drive, Sheets and Docs tools in the Codex environment operating this project. Your Google account needs permission to create, read and update the output files. Read [Google tool requirements](docs/google_tools.md) before starting: tool availability and compatibility vary by environment.
4. Ask Codex: “Check this project's setup and run its offline tests.” There are no third-party Python packages to install and no project API keys or `.env` file to configure. Codex can run `python3 scripts/check_setup.py` and the tests below. Install or authenticate the external Codex CLI separately if needed.
5. Enter the following, replacing both placeholders:

```text
Research [Company Name] — [Company Website]
```

Replace the website placeholder with a full `https://` URL and remove the square brackets. Use an em dash between the name and URL. Codex researches the target's product and proposes relevant competitors. Review the proposal, then reply:

```text
Approve these competitors: [competitor name]; [competitor name]
OR
Just approve in natural language
```

After approval, Codex continues the saved workflow through research, classification and verified publication. You do not need to launch each stage. Keep the Codex operator session available to execute queued Google tool operations. If a quota, permission or tool error stops the run, address the cause and use `Resume [Company Name]` for one bounded recovery attempt. Do not start another run to recover interrupted work.

## What you receive

- **One native Google Sheet**, with a single `Case studies` tab and five columns: Case-study source; Customer company; People involved; Company profile; Buying situation.
- **One native Google Doc**, with five real tabs: Overview; Company profiles; People; Buying situations; Methods & sources.

The Sheet preserves complete accessible source evidence. Inaccessible records and their limitations remain in the local audit. The report contains exclusive company-type frequencies, overlapping stakeholder functions and buying situations, concrete examples, provider concentration, denominators and evidence limitations. Documented product use stays separate from purchase requirements and outcomes. Titles support function counts; testimonial or implementation participation does not establish a job function or purchasing authority.

This is descriptive research. The agent does not recommend target segments, positioning, outreach or sales strategy. See the [output contract](docs/output_contract.md).

## Workflow and architecture

1. Research the target's capabilities and shared customer need; propose competing products for human approval.
2. Discover and screen published cases across approved providers, saving decisions and continuation checkpoints.
3. Extract assigned evidence once and synchronize verified five-column Sheet rows.
4. Freeze the complete evidence database; build one global taxonomy, using bounded hierarchical synthesis for large inputs.
5. Classify batches against compact fixed category definitions, review Other observations once, and compute profile unions and frequencies in Python.
6. Synthesize the report, validate its counts and evidence associations, and publish/verify the native Doc tabs.

`runner.py` owns state and recovery; `research.py` handles research memory; the analysis/taxonomy modules handle saved evidence; `report_roles.py` and `report_quality.py` derive and validate report counts; `workspace.py` and `document_tabs.py` coordinate Google operations performed by the Codex operator. `AGENTS.md` supplies the operator contract; [APP_WORKFLOW.md](APP_WORKFLOW.md) describes the execution loop. No web app, backend or custom OAuth service is included.

## Usage, cost and limitations

Research and analysis use your configured Codex model and account limits. Work varies with provider inventories, source accessibility and evidence volume; there is no fixed price or guaranteed completion time. The account must support the worker CLI configuration. `python3 runner.py metrics RUN_ID` reports executions, timing and available token/cache counters; unavailable counters stay unknown. Google services have their own permissions and quotas. No separate model-grading agent is part of the normal workflow.

Published customer stories are selected marketing evidence, not a representative market sample. Missing buying reasons and authority remain unknown; post-deployment usage does not prove an original selection reason. A failed PDF is not retried or rescued. Taxonomy and source interpretation can still be wrong; review the evidence and report before relying on findings. Large inventories can take substantial time and account usage.

## Offline checks and local data

```sh
python3 -m pip install -r requirements.txt
python3 scripts/check_setup.py
python3 -m unittest discover -s tests -p test_release_smoke.py -v
# Full offline regression suite:
python3 -m unittest discover -s tests -v
```

Tests use fictional data, fake worker responses and simulated Google readbacks. They do not call models, research websites or publish files. Live account/connector compatibility must be checked in the user's environment; offline success does not verify it.

`runs/` and backups are created as needed and ignored by Git. `RESEARCH_RUNS_DIR` optionally selects a different local run directory; normally leave it unset. Never commit generated evidence, tool responses or credentials. No previous research runs or private reference documents are required.

## License and contributions

Released under [MIT](LICENSE). External services and source publications retain their own terms; see [third-party notices](THIRD_PARTY_NOTICES.md). For fixes or issues, read [CONTRIBUTING.md](CONTRIBUTING.md). Share a synthetic reproduction and sanitized error details, never private customer evidence, Google file links or account tokens.
