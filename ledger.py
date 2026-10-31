"""Synthetic-first CSV reconciliation ledger. All runtime state stays local."""
from __future__ import annotations
import csv
import hashlib
import io
import json
import os
import re
import sqlite3
import sys
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)).resolve()
RUNTIME = Path(os.environ.get("WORKFLOW_LEDGER_HOME", Path.home() / ".workflow-ledger")).expanduser().resolve()
RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(RUNTIME, 0o700)
DB_PATH = RUNTIME / "ledger.sqlite"
MAX_CSV_BYTES = 1_000_000
MAX_ROWS = 5_000

FIELDS = {
    "invoice": {
        "record_id": ("invoice id", "invoice number", "invoice_id", "id"),
        "amount": ("amount", "invoice amount", "total"),
        "currency": ("currency", "ccy"),
        "date": ("issue date", "date", "invoice date"),
    },
    "payment": {
        "record_id": ("payment id", "payment number", "payment_id", "id"),
        "invoice_ref": ("invoice id", "invoice number", "invoice_id"),
        "amount": ("paid amount", "amount", "payment amount"),
        "currency": ("currency", "ccy"),
        "date": ("posted date", "date", "payment date"),
    },
}
REQUIRED = {"invoice": ("record_id", "amount", "currency"), "payment": ("record_id", "amount", "currency")}

def db_connect(path=DB_PATH):
    c = sqlite3.connect(path, timeout=5)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    return c

def initialize(path=DB_PATH):
    c = db_connect(path)
    c.executescript("""
    CREATE TABLE IF NOT EXISTS batches(
      batch_id TEXT PRIMARY KEY, source_name TEXT NOT NULL, record_type TEXT NOT NULL,
      payload_fingerprint TEXT NOT NULL, mapping_json TEXT NOT NULL, row_count INTEGER NOT NULL,
      received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS source_rows(
      row_key TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(batch_id),
      row_number TEXT NOT NULL, record_type TEXT NOT NULL, source_name TEXT NOT NULL,
      record_id TEXT NOT NULL, invoice_ref TEXT, amount_text TEXT NOT NULL, currency TEXT NOT NULL,
      date_text TEXT, raw_json TEXT NOT NULL, normalized_json TEXT NOT NULL, duplicate_of TEXT,
      UNIQUE(batch_id,row_number)
    );
    CREATE INDEX IF NOT EXISTS source_identity_idx ON source_rows(source_name,record_type,record_id);
    CREATE TABLE IF NOT EXISTS source_conflicts(
      conflict_id TEXT PRIMARY KEY, left_row TEXT NOT NULL REFERENCES source_rows(row_key),
      right_row TEXT NOT NULL REFERENCES source_rows(row_key), reason TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS allocations(
      allocation_id TEXT PRIMARY KEY, payment_row TEXT NOT NULL REFERENCES source_rows(row_key),
      invoice_row TEXT NOT NULL REFERENCES source_rows(row_key), amount_text TEXT NOT NULL,
      reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    columns={r[1] for r in c.execute("PRAGMA table_info(source_rows)")}
    if "duplicate_of" not in columns:
        c.execute("ALTER TABLE source_rows ADD COLUMN duplicate_of TEXT")
    c.commit(); c.close()
    os.chmod(path, 0o600)

def parse_amount(value: str) -> Decimal:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Amount is required")
    lexeme=value.strip()
    if not re.fullmatch(r"[0-9]{1,18}(?:\.[0-9]{1,6})?",lexeme):
        raise ValueError("Amount must use fixed-point notation with at most 18 integer and 6 fractional digits")
    try: amount = Decimal(value.strip())
    except InvalidOperation as exc: raise ValueError("Amount must be a decimal string") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("Amount must be a finite value greater than zero")
    return amount

def _default_mapping(headers, record_type):
    normalized = {h.strip().lower().replace("_", " "): h for h in headers}
    found = {}
    for field, aliases in FIELDS[record_type].items():
        for alias in aliases:
            if alias in normalized:
                found[field] = normalized[alias]
                break
    return found

def parse_csv_text(text: str, record_type: str, mapping=None):
    if record_type not in FIELDS: raise ValueError("Record type must be invoice or payment")
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV must be under 1 MB")
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        headers = reader.fieldnames or []
        if not headers or len(headers) > 100: raise ValueError("CSV needs a header row with at most 100 columns")
        if len(set(headers)) != len(headers): raise ValueError("CSV column names must be unique")
        chosen = _default_mapping(headers, record_type) if mapping is None else mapping
        if not isinstance(chosen, dict): raise ValueError("Mapping must be an object")
        missing = [field for field in REQUIRED[record_type] if chosen.get(field) not in headers]
        if missing: raise ValueError("Map required fields to CSV columns: " + ", ".join(missing))
        for field, header in chosen.items():
            if field not in FIELDS[record_type] or header not in headers:
                raise ValueError("Mapping refers to an unknown field or CSV column")
        rows = []
        for number, raw in enumerate(reader, start=2):
            if number > MAX_ROWS + 1: raise ValueError(f"CSV exceeds {MAX_ROWS} data rows")
            if None in raw: raise ValueError(f"Row {number} has more columns than the header")
            if any(value is None for value in raw.values()): raise ValueError(f"Row {number} has fewer columns than the header")
            record_id = raw[chosen["record_id"]]
            amount_text = raw[chosen["amount"]]
            if not record_id or record_id.strip()!=record_id: raise ValueError(f"Row {number} needs a record ID without surrounding whitespace")
            parse_amount(amount_text)
            currency = raw[chosen["currency"]].strip().upper()
            if not re.fullmatch(r"[A-Z]{3}",currency): raise ValueError(f"Row {number} has an invalid ASCII currency code")
            invoice_ref = raw[chosen["invoice_ref"]] if record_type == "payment" and chosen.get("invoice_ref") else ""
            rows.append({
                "row_number": str(number), "record_type": record_type, "record_id": record_id,
                "invoice_ref": invoice_ref, "amount_text": amount_text,
                "currency": currency, "date_text": raw.get(chosen.get("date", ""), ""),
                "raw": raw,
            })
        if not rows: raise ValueError("CSV has no data rows")
        return {"headers": headers, "mapping": chosen, "rows": rows}
    except csv.Error as exc: raise ValueError("CSV could not be parsed") from exc

def preview_csv(text, record_type, mapping=None):
    parsed = parse_csv_text(text, record_type, mapping)
    return {
        "headers": parsed["headers"], "mapping": parsed["mapping"],
        "fields": list(FIELDS[record_type]), "record_type": record_type,
        "row_count": len(parsed["rows"]),
        "sample": [{k: r[k] for k in ("row_number", "record_id", "invoice_ref", "amount_text", "currency", "date_text")} for r in parsed["rows"][:8]],
    }

def import_csv(text: str, record_type: str, source_name: str, mapping=None, path=DB_PATH):
    if not isinstance(source_name, str) or not source_name.strip() or len(source_name) > 120:
        raise ValueError("Source name must be 1 to 120 characters")
    parsed = parse_csv_text(text, record_type, mapping)
    mapping_json = json.dumps(parsed["mapping"], sort_keys=True, separators=(",", ":"))
    payload_fingerprint = hashlib.sha256(text.encode("utf-8")).hexdigest()
    batch_id = hashlib.sha256((source_name.strip() + "\0" + record_type + "\0" + mapping_json + "\0" + payload_fingerprint).encode()).hexdigest()
    c = db_connect(path)
    try:
        c.execute("BEGIN IMMEDIATE")
        if c.execute("SELECT 1 FROM batches WHERE batch_id=?", (batch_id,)).fetchone():
            c.rollback()
            return {"status": "duplicate", "batch_id": batch_id, "row_count": 0, "message": "This exact source batch was already imported. No rows changed."}
        c.execute("INSERT INTO batches(batch_id,source_name,record_type,payload_fingerprint,mapping_json,row_count) VALUES(?,?,?,?,?,?)",
                  (batch_id, source_name.strip(), record_type, payload_fingerprint, mapping_json, len(parsed["rows"])))
        new_rows = []
        for record in parsed["rows"]:
            normalized = {k: record[k] for k in ("record_id", "invoice_ref", "amount_text", "currency", "date_text")}
            normalized_json = json.dumps(normalized, sort_keys=True, separators=(",", ":"))
            row_key = hashlib.sha256((batch_id + "\0" + record["row_number"]).encode()).hexdigest()
            prior = c.execute("SELECT row_key,normalized_json FROM source_rows WHERE source_name=? AND record_type=? AND record_id=? AND row_key<>?",
                              (source_name.strip(), record_type, record["record_id"], row_key)).fetchall()
            duplicate_of=next((old["row_key"] for old in prior if old["normalized_json"]==normalized_json),None)
            c.execute("""INSERT INTO source_rows(row_key,batch_id,row_number,record_type,source_name,record_id,invoice_ref,amount_text,currency,date_text,raw_json,normalized_json,duplicate_of)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (row_key,batch_id,record["row_number"],record_type,source_name.strip(),record["record_id"],record["invoice_ref"],record["amount_text"],record["currency"],record["date_text"],json.dumps(record["raw"],ensure_ascii=False,sort_keys=True),normalized_json,duplicate_of))
            new_rows.append((row_key, record))
            for old in prior:
                if old["normalized_json"] != normalized_json:
                    pair = sorted((old["row_key"], row_key))
                    conflict_id = hashlib.sha256((pair[0] + "\0" + pair[1]).encode()).hexdigest()
                    c.execute("INSERT OR IGNORE INTO source_conflicts(conflict_id,left_row,right_row,reason) VALUES(?,?,?,?)",
                              (conflict_id,pair[0],pair[1],"Same source record ID has different imported facts"))
        c.commit()
        return {"status": "imported", "batch_id": batch_id, "row_count": len(new_rows),
                "conflict_count": c.execute("SELECT COUNT(DISTINCT sc.conflict_id) FROM source_conflicts sc JOIN source_rows sr ON sr.row_key IN (sc.left_row,sc.right_row) WHERE sr.batch_id=?", (batch_id,)).fetchone()[0]}
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def _amount_sum(rows, key):
    with localcontext() as ctx:
        ctx.prec=40
        total = Decimal("0")
        for row in rows: total += Decimal(row[key])
        return total

def ledger_state(path=DB_PATH):
    c=db_connect(path)
    batches=[dict(r) for r in c.execute("SELECT batch_id,source_name,record_type,payload_fingerprint,row_count,received_at FROM batches ORDER BY received_at,batch_id")]
    rows=[dict(r) for r in c.execute("SELECT * FROM source_rows ORDER BY record_type,record_id,batch_id,row_number")]
    allocations=[dict(r) for r in c.execute("SELECT * FROM allocations ORDER BY allocation_id")]
    conflicts=[dict(r) for r in c.execute("SELECT * FROM source_conflicts ORDER BY conflict_id")]
    conflict_rows={k for x in conflicts for k in (x["left_row"],x["right_row"])}
    alloc_by_payment={}; alloc_by_invoice={}
    for a in allocations:
        alloc_by_payment.setdefault(a["payment_row"],[]).append(a)
        alloc_by_invoice.setdefault(a["invoice_row"],[]).append(a)
    invoices=[r for r in rows if r["record_type"]=="invoice"]
    payments=[r for r in rows if r["record_type"]=="payment"]
    by_key={r["row_key"]:r for r in rows}
    for i in invoices:
        used=_amount_sum(alloc_by_invoice.get(i["row_key"],[]),"amount_text")
        with localcontext() as ctx:
            ctx.prec=40
            i["allocated_text"]=str(used); i["remaining_text"]=str(Decimal(i["amount_text"])-used)
        i["conflict"]=i["row_key"] in conflict_rows
        i["duplicate_fact"]=bool(i["duplicate_of"])
    for p in payments:
        used=_amount_sum(alloc_by_payment.get(p["row_key"],[]),"amount_text")
        with localcontext() as ctx:
            ctx.prec=40
            p["allocated_text"]=str(used); p["remaining_text"]=str(Decimal(p["amount_text"])-used)
        p["conflict"]=p["row_key"] in conflict_rows
        p["duplicate_fact"]=bool(p["duplicate_of"])
        matches=[i for i in invoices if i["record_id"]==p["invoice_ref"] and i["currency"]==p["currency"] and not i["conflict"] and not i["duplicate_fact"] and Decimal(i["remaining_text"])>0] if p["invoice_ref"] else []
        p["suggested_invoice_row"]=matches[0]["row_key"] if len(matches)==1 else ""
        p["suggested_amount"]=str(min(Decimal(p["remaining_text"]),Decimal(matches[0]["remaining_text"]))) if len(matches)==1 else ""
        p["allocations"]=[{**a,"invoice_id":by_key[a["invoice_row"]]["record_id"]} for a in alloc_by_payment.get(p["row_key"],[])]
    c.close()
    return {"batches":batches,"invoices":invoices,"payments":payments,"allocations":allocations,"conflicts":conflicts,"counts":{"batches":len(batches),"invoices":len(invoices),"payments":len(payments),"conflicts":len(conflicts),"allocations":len(allocations)}}

def record_allocation(payment_row, invoice_row, amount_text, reason, path=DB_PATH):
    if not isinstance(reason,str) or len(reason.strip())<3 or len(reason)>500: raise ValueError("Enter a resolution reason of 3 to 500 characters")
    amount=parse_amount(amount_text)
    c=db_connect(path)
    try:
        c.execute("BEGIN IMMEDIATE")
        payment=c.execute("SELECT * FROM source_rows WHERE row_key=? AND record_type='payment'",(payment_row,)).fetchone()
        invoice=c.execute("SELECT * FROM source_rows WHERE row_key=? AND record_type='invoice'",(invoice_row,)).fetchone()
        if not payment or not invoice: raise ValueError("Choose an existing payment and invoice row")
        if payment["duplicate_of"] or invoice["duplicate_of"]: raise ValueError("Duplicate source facts cannot be allocated twice")
        if payment["currency"]!=invoice["currency"]: raise ValueError("Payment and invoice currencies must match")
        conflict_keys={r[0] for r in c.execute("SELECT left_row FROM source_conflicts UNION SELECT right_row FROM source_conflicts")}
        if payment_row in conflict_keys or invoice_row in conflict_keys: raise ValueError("Review conflicting source facts manually before allocating these rows")
        allocation_id=hashlib.sha256((payment_row+"\0"+invoice_row+"\0"+amount_text.strip()+"\0"+reason.strip()).encode()).hexdigest()
        if c.execute("SELECT 1 FROM allocations WHERE allocation_id=?",(allocation_id,)).fetchone():
            c.rollback(); return {"status":"duplicate","allocation_id":allocation_id,"message":"This exact allocation was already recorded."}
        with localcontext() as ctx:
            ctx.prec=40
            pay_used=sum((Decimal(r[0]) for r in c.execute("SELECT amount_text FROM allocations WHERE payment_row=?",(payment_row,))),Decimal("0"))
            inv_used=sum((Decimal(r[0]) for r in c.execute("SELECT amount_text FROM allocations WHERE invoice_row=?",(invoice_row,))),Decimal("0"))
            if pay_used+amount>Decimal(payment["amount_text"]): raise ValueError("Allocation exceeds the payment's remaining amount")
            if inv_used+amount>Decimal(invoice["amount_text"]): raise ValueError("Allocation exceeds the invoice's remaining amount")
        c.execute("INSERT INTO allocations(allocation_id,payment_row,invoice_row,amount_text,reason) VALUES(?,?,?,?,?)",
                  (allocation_id,payment_row,invoice_row,amount_text.strip(),reason.strip()))
        c.commit()
        return {"status":"allocated","allocation_id":allocation_id,"amount_text":amount_text.strip(),"reason":reason.strip()}
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def _safe_cell(value):
    text="" if value is None else str(value)
    if text.lstrip(" \t\r\n").startswith(("=","+","-","@")): return "'"+text
    return text

def export_csv(path=DB_PATH):
    state=ledger_state(path)
    by_key={r["row_key"]:r for r in state["invoices"]+state["payments"]}
    out=io.StringIO(newline="")
    writer=csv.writer(out,lineterminator="\n")
    writer.writerow(["kind","batch_id","source_row","source_record_id","invoice_reference","amount","currency","related_invoice_id","allocation_amount","resolution_reason","conflict"])
    for row in sorted(state["invoices"]+state["payments"],key=lambda x:(x["batch_id"],int(x["row_number"]),x["record_type"])):
        writer.writerow([_safe_cell(x) for x in [row["record_type"],row["batch_id"],row["row_number"],row["record_id"],row["invoice_ref"],row["amount_text"],row["currency"],"", "", "", "yes" if row["conflict"] else "no"]])
    for a in state["allocations"]:
        payment=by_key[a["payment_row"]]; invoice=by_key[a["invoice_row"]]
        writer.writerow([_safe_cell(x) for x in ["allocation",payment["batch_id"],payment["row_number"],payment["record_id"],payment["invoice_ref"],payment["amount_text"],payment["currency"],invoice["record_id"],a["amount_text"],a["reason"],"no"]])
    return out.getvalue()

def seed_demo(path=DB_PATH):
    initialize(path)
    c=db_connect(path)
    exists=c.execute("SELECT 1 FROM batches LIMIT 1").fetchone(); c.close()
    if exists: return
    inv=(ROOT/"fixtures"/"invoices.csv").read_text()
    pay=(ROOT/"fixtures"/"payments.csv").read_text()
    revised=(ROOT/"fixtures"/"payments-revised.csv").read_text()
    import_csv(inv,"invoice","demo-invoice-export",path=path)
    import_csv(pay,"payment","demo-bank-feed",path=path)
    import_csv(revised,"payment","demo-bank-feed",path=path)

if __name__=="__main__": seed_demo()
