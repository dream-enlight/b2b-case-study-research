# Contributing

Keep changes small and evidence-preserving. This is a Codex-native descriptive research tool; do not add a hosted service, credentials, bundled customer datasets or strategy recommendations.

Use Python 3.11+ on macOS/Linux. The runtime and offline suite use only the standard library:

```sh
python3 -m pip install -r requirements.txt
python3 scripts/check_setup.py
python3 -m unittest discover -s tests -v
```

Use synthetic fixtures. Never run real research, model workers or Google publication as an incidental test. Do not edit real run state by hand or repeat finalized source work. Keep immutable receipts and source associations intact. Changes to Google contracts need an explicitly authorized integration check; offline tests alone cannot verify live account behavior.

Open an issue describing the expected/actual behavior, OS, Python and Codex versions, and a minimal fictional reproduction. Sanitize logs: remove names, source records, Google links/IDs, account details, tokens and machine paths. For a suspected secret exposure, avoid posting it publicly; contact the repository maintainer privately if a private reporting route is available.

A pull request should explain the problem, the smallest fix, relevant validation and any remaining limits. Contributions must be yours to license under this project's MIT license. External customer publications are not licensed by this repository.
