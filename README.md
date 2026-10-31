# Workflow Ledger

**First principle:** Preserve source evidence and record each reviewed allocation with its reason and lineage.

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

**Native Mac app**

The native wrapper runs the same local app in a macOS WebView. It starts its own loopback server on an unused port and stops it when the window closes. It does not connect to a server that is already running.

From this source folder on macOS with Python 3.12, create an isolated build environment and install the frozen desktop dependencies:

```sh
python3.12 -m venv .desktop-venv
source .desktop-venv/bin/activate
python -m pip install -r requirements-desktop.lock.txt
python build_desktop.py
python install_desktop.py
```

The guarded installer places `Workflow Ledger.app` in `~/Applications`. Open it in Finder. Use **Workflow Ledger → Quit** or press **Command-Q** to close it. The installer replaces only a copy with this app's bundle ID and owner marker, and keeps the prior copy as a backup. To uninstall, move `Workflow Ledger.app` from Applications to Trash. Local records and settings remain in `~/.workflow-ledger`.

The build does not request a Developer ID signature or notarization. macOS may ask you to confirm the locally built app the first time it opens.

**Development**

Run the browser version with `python3 server.py` at `http://127.0.0.1:8334`. Stop it with Ctrl-C. Native settings are saved as owner-only `preferences.json` beside the SQLite ledger in `~/.workflow-ledger`. When the browser version is opened after this update, it imports only the known compact and reduced-motion preferences from its existing `workflow-ledger-prefs` localStorage entry, then removes that entry. It does not read a browser profile.

Run backend and desktop policy checks with:

```sh
python3 -m unittest discover -s tests -v
```

The browser app and source code use Python's standard library. The native bundle adds the pinned pywebview, PyObjC, and PyInstaller dependencies listed in `requirements-desktop.lock.txt`; their license texts are collected into the app. The native wrapper is for macOS only. Other operating systems are not tested.
