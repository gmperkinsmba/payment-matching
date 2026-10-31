# Security

Payment Matching imports bounded CSV files into a local SQLite ledger and stores a SHA-256 import fingerprint. The server checks Host and requires an exact Origin and request token for writes. Runtime folders and database files use owner-only permissions. CSV export escapes cells that spreadsheet software could treat as formulas, and SQL uses bound parameters. Data is plaintext. SHA-256 identifies imported content; it does not encrypt the ledger or certify payment decisions.

Use made-up payment rows in reports. Use your Mac’s disk encryption to protect saved files. The native app has an ad-hoc code signature. This lets the installer check whether its files changed. It does not prove who made the app. The build is not notarized.

Report security issues through [GitHub private vulnerability reporting](https://github.com/gmperkinsmba/payment-matching/security/advisories/new).
