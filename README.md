# Workflow Ledger

A local tool to reconcile invoice and payment CSV evidence. It previews column maps. Source IDs and amount text stay strings. It keeps import batches unchanged and flags changed source facts. It stores reviewed payment allocations with reasons and links to source rows.

## Run

Python 3.10 or newer is enough. The server and ledger use only the standard library.

```sh
python3 server.py
```

Open `http://127.0.0.1:8334`. The app seeds fabricated invoices and payment rows on first launch. Runtime data lives in `~/.workflow-ledger/ledger.sqlite`; set `WORKFLOW_LEDGER_HOME` to choose another local runtime directory. Stop the server with Ctrl+C.

## What it enforces

- Preview CSV files and map fields before import. Source IDs and amount text stay strings.
- Amounts use fixed-point notation with limits. Up to 18 digits can appear before the decimal and six after it. Exponential notation is rejected.
- Each payload gets a SHA-256 fingerprint and a deterministic batch identity. Replaying the same source, mapping, and payload has no effect.
- Batch imports are atomic. A malformed row prevents the full batch from being committed.
- Changed facts remain visible as conflicts when the source, type, and record ID match.
- Conflicting rows need a person to review the source. There is no automatic conflict-resolution action.
- Repeated identical facts stay visible for audit. They cannot add allocation capacity.
- Allocations need a reason, matching currency, and enough payment and invoice balance. Splits are supported.
- CSV exports are deterministic. Formula-like spreadsheet cells start with an apostrophe.

## Scope

This synthetic demo is not a payment processor or accounting system. It does not contact banks or send payments. It does not use a model to infer matches. Suggestions need an exact invoice reference and matching currency. They never change balances until a person records an allocation. The app has no authentication. The server binds to loopback and checks request tokens and origins for local changes. Do not expose it to a network or import sensitive data.
