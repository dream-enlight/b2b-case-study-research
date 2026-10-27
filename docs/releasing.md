# First public release

Review the source, license and verification notes before publishing. The prepared repository starts on `main` with no commits or remote; it does not inherit a development Git object database. Set a public author identity before creating the first commit.

1. On GitHub, create a new **public**, empty repository named `b2b-case-study-research`. Do not initialize it with a README, license or `.gitignore`.
2. Open a terminal in this release repository, or ask Codex to execute the following after you explicitly authorize publication. Replace all three identity/account placeholders:

```sh
git config --local user.name "YOUR_PUBLIC_AUTHOR_NAME"
git config --local user.email "YOUR_PUBLIC_OR_GITHUB_NOREPLY_EMAIL"
git add .
git diff --cached --check
git diff --cached --stat
git commit -m "Initial public release"
git remote add origin "https://github.com/YOUR_GITHUB_USERNAME/b2b-case-study-research.git"
git push -u origin main
```

Use your normal GitHub authentication; never put a token in the remote URL or source files. Do not copy the parent project's `.git`, research data or verification logs. The blank seed workbook is intentionally included; generated research workbooks and reports are not.

The runtime was checked offline with fictional cases and simulated tool results. Before a real run, confirm Codex worker configuration and the required native Google tool capabilities in your own environment. Publication of this repository does not publish any research results.
