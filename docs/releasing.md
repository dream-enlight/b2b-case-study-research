# Publishing updates

Use this public repository checkout and its existing GitHub remote. Never copy the parent development repository’s Git objects, saved research, account logs or private reference files.

1. Fetch the remote and reconcile any newer commits before publishing; never force-push release updates.
2. Update README.md and RELEASE_NOTES.md to describe observable behavior and compatibility.
3. Run `python3 scripts/check_setup.py` and `python3 -m unittest discover -s tests -v`. Use synthetic fixtures and simulated tool results; release checks must not launch live research or write to Google Workspace.
4. Review `git status`, the staged diff and `git diff --cached --check`. Exclude credentials, generated evidence and account-specific paths. The blank seed workbook is intentionally included.
5. Commit with a public author identity and push the reviewed commit to the existing remote. Use normal GitHub authentication; never embed tokens in source or remote URLs.
6. Verify the remote branch points to the published commit. A version tag or GitHub Release is optional when explicitly requested.

Offline success does not verify a user’s live Codex authentication or Google connector capabilities. Consult docs/google_tools.md before normal operation.
