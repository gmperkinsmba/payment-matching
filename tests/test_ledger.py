import csv
import io
import tempfile
import unittest
from pathlib import Path
from ledger import export_csv, import_csv, initialize, ledger_state, preview_csv, record_allocation

INVOICES="Invoice ID,Amount,Currency\n000042,40.00,USD\n000043,30.00,USD\n"
PAYMENTS="Payment ID,Invoice ID,Paid Amount,Currency\nPAY-001,,70.00,USD\n"

class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/"ledger.sqlite"
        initialize(self.db)
    def tearDown(self): self.tmp.cleanup()

    def test_preview_keeps_ids_and_decimal_lexemes_as_strings(self):
        p=preview_csv(INVOICES,"invoice")
        self.assertEqual(p["sample"][0]["record_id"],"000042")
        self.assertIsInstance(p["sample"][0]["record_id"],str)
        self.assertEqual(p["sample"][0]["amount_text"],"40.00")
        self.assertIsInstance(p["sample"][0]["amount_text"],str)

    def test_duplicate_headers_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"unique"):
            preview_csv("Invoice ID,Amount,Amount,Currency\n000042,1.00,2.00,USD\n","invoice")

    def test_short_csv_rows_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"fewer columns"):
            preview_csv("Invoice ID,Amount,Currency\n000042,1.00\n","invoice")

    def test_amount_lexeme_has_bounded_fixed_point_scale(self):
        for invalid in ("1e99999","0.0000001","1000000000000000000","１２.００"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError,"fixed-point"):
                preview_csv(f"Invoice ID,Amount,Currency\nI-1,{invalid},USD\n","invoice")

    def test_max_supported_amount_splits_and_recombines_exactly(self):
        invoice="Invoice ID,Amount,Currency\nI-1,999999999999999999.999999,USD\n"
        payments="Payment ID,Invoice ID,Paid Amount,Currency\nP-1,I-1,500000000000000000.000001,USD\nP-2,I-1,499999999999999999.999998,USD\n"
        import_csv(invoice,"invoice","billing",path=self.db)
        import_csv(payments,"payment","bank",path=self.db)
        state=ledger_state(self.db); target=state["invoices"][0]
        for payment in state["payments"]:
            record_allocation(payment["row_key"],target["row_key"],payment["amount_text"],"Exact remittance split",path=self.db)
        final=ledger_state(self.db)
        self.assertEqual(final["invoices"][0]["allocated_text"],"999999999999999999.999999")
        self.assertEqual(final["invoices"][0]["remaining_text"],"0.000000")

    def test_payload_fingerprint_and_batch_replay_do_not_change_state(self):
        first=import_csv(INVOICES,"invoice","billing",path=self.db)
        before=ledger_state(self.db)
        replay=import_csv(INVOICES,"invoice","billing",path=self.db)
        after=ledger_state(self.db)
        self.assertEqual(first["status"],"imported")
        self.assertEqual(len(first["batch_id"]),64)
        self.assertEqual(replay["status"],"duplicate")
        self.assertEqual(before["counts"],after["counts"])
        self.assertEqual(len(before["invoices"]),2)

    def test_malformed_late_row_rolls_back_whole_batch(self):
        bad="Invoice ID,Amount,Currency\n000042,40.00,USD\n000043,broken,USD\n"
        with self.assertRaises(ValueError): import_csv(bad,"invoice","billing",path=self.db)
        state=ledger_state(self.db)
        self.assertEqual(state["counts"]["batches"],0)
        self.assertEqual(state["invoices"],[])

    def test_conflicting_same_source_facts_remain_visible(self):
        import_csv(PAYMENTS,"payment","bank",path=self.db)
        revised="Payment ID,Invoice ID,Paid Amount,Currency\nPAY-001,,71.00,USD\n"
        import_csv(revised,"payment","bank",path=self.db)
        state=ledger_state(self.db)
        rows=[p for p in state["payments"] if p["record_id"]=="PAY-001"]
        self.assertEqual(sorted(r["amount_text"] for r in rows),["70.00","71.00"])
        self.assertTrue(all(r["conflict"] for r in rows))
        self.assertEqual(len(state["conflicts"]),1)

    def test_identical_fact_in_later_batch_is_marked_and_not_allocatable(self):
        invoice="Invoice ID,Amount,Currency\n000042,40.00,USD\n"
        payment="Payment ID,Invoice ID,Paid Amount,Currency\nPAY-001,000042,40.00,USD\n"
        import_csv(invoice,"invoice","billing",path=self.db)
        import_csv(payment,"payment","bank",path=self.db)
        # A new payload fingerprint preserves the second evidence row without doubling capacity.
        import_csv("Payment ID,Invoice ID,Paid Amount,Currency\nPAY-001,000042,40.00,USD\n\n", "payment", "bank", path=self.db)
        state=ledger_state(self.db)
        duplicated=[p for p in state["payments"] if p["record_id"]=="PAY-001"]
        self.assertEqual(len(duplicated),2)
        self.assertEqual(sum(bool(p["duplicate_fact"]) for p in duplicated),1)
        duplicate=next(p for p in duplicated if p["duplicate_fact"])
        with self.assertRaisesRegex(ValueError,"Duplicate source facts"):
            record_allocation(duplicate["row_key"],state["invoices"][0]["row_key"],"1.00","Avoid duplicate capacity",path=self.db)

    def test_payment_can_split_and_reason_and_lineage_are_recorded(self):
        import_csv(INVOICES,"invoice","billing",path=self.db)
        import_csv(PAYMENTS,"payment","bank",path=self.db)
        state=ledger_state(self.db)
        payment=state["payments"][0]
        a,b=state["invoices"]
        first=record_allocation(payment["row_key"],a["row_key"],"40.00","Invoice 42 first share",path=self.db)
        second=record_allocation(payment["row_key"],b["row_key"],"30.00","Invoice 43 remainder",path=self.db)
        final=ledger_state(self.db)
        self.assertEqual([first["status"],second["status"]],["allocated","allocated"])
        self.assertEqual(len(final["allocations"]),2)
        self.assertEqual(final["payments"][0]["remaining_text"],"0.00")
        self.assertEqual(final["allocations"][0]["reason"],"Invoice 42 first share")
        self.assertEqual(final["allocations"][0]["payment_row"],payment["row_key"])
        self.assertEqual(final["allocations"][0]["invoice_row"],a["row_key"])

    def test_overallocation_rejects_without_recording(self):
        import_csv(INVOICES,"invoice","billing",path=self.db)
        import_csv(PAYMENTS,"payment","bank",path=self.db)
        state=ledger_state(self.db); payment=state["payments"][0]; invoice=state["invoices"][0]
        with self.assertRaisesRegex(ValueError,"invoice"):
            record_allocation(payment["row_key"],invoice["row_key"],"40.01","Over by one cent",path=self.db)
        self.assertEqual(ledger_state(self.db)["allocations"],[])

    def test_currency_mismatch_is_rejected(self):
        invoices="Invoice ID,Amount,Currency\n000042,40.00,EUR\n"
        import_csv(invoices,"invoice","billing",path=self.db);import_csv(PAYMENTS,"payment","bank",path=self.db)
        state=ledger_state(self.db)
        with self.assertRaisesRegex(ValueError,"currencies"):
            record_allocation(state["payments"][0]["row_key"],state["invoices"][0]["row_key"],"1.00","Currency check",path=self.db)

    def test_csv_export_neutralizes_formula_cells_and_is_reproducible(self):
        invoices="Invoice ID,Amount,Currency\n000042,40.00,USD\n"
        payments="Payment ID,Invoice ID,Paid Amount,Currency,Description\n=2+3,000042,1.20,USD,=HYPERLINK(x)\n"
        import_csv(invoices,"invoice","billing",path=self.db)
        import_csv(payments,"payment","bank",path=self.db)
        s=ledger_state(self.db)
        record_allocation(s["payments"][0]["row_key"],s["invoices"][0]["row_key"],"1.00","  =HYPERLINK(x)",path=self.db)
        one=export_csv(self.db); two=export_csv(self.db)
        self.assertEqual(one,two)
        rows=list(csv.DictReader(io.StringIO(one)))
        payment=next(r for r in rows if r["kind"]=="payment")
        self.assertEqual(payment["source_record_id"],"'=2+3")
        self.assertNotEqual(payment["source_record_id"],"=2+3")
        self.assertEqual(payment["amount"],"1.20")
        self.assertIn("batch_id",payment)
        allocation=next(r for r in rows if r["kind"]=="allocation")
        self.assertEqual(allocation["resolution_reason"],"'=HYPERLINK(x)")

if __name__=="__main__": unittest.main()
