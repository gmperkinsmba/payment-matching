# Context

Workflow Ledger demonstrates evidence-first reconciliation for invoice and payment exports. Each batch is fingerprinted, source rows are retained, changed facts are flagged, and allocations record amount, reason, and both source-row keys.

The local demo uses fabricated CSVs. The application is deliberately narrow: suggestions require an exact invoice reference and matching currency. The code does not access external accounting systems, send funds, or call a language model.

The SQLite database is private local runtime state, stored outside this checkout. Import and allocation writes use SQLite transactions. CSV exports neutralize spreadsheet formula prefixes.
