import tempfile
import unittest
from datetime import date
from pathlib import Path

from ownership.ingest import IngestError, OwnershipRecord, parse_text, read_records

ROOT = Path(__file__).resolve().parent.parent
HEADER = "holder_name,held_name,stake_pct,filing_date,entity_type\n"
GOOD = "Tata Sons Private Limited,Tata Steel Ltd,31.74,2026-07-15,corporate\n"


def parse(*rows, header=HEADER):
    return parse_text(header + "".join(rows))


class WellFormed(unittest.TestCase):
    def test_minimal_row_loads(self):
        res = parse(GOOD)
        self.assertEqual((len(res.records), res.rejected, res.flagged), (1, [], []))
        rec = res.records[0]
        self.assertIsInstance(rec, OwnershipRecord)
        self.assertEqual(rec.stake_pct, 31.74)
        self.assertEqual(rec.filing_date, date(2026, 7, 15))
        self.assertEqual((rec.holder_norm, rec.held_norm), ("tata sons", "tata steel"))
        self.assertEqual(rec.line, 2)
        self.assertIsNone(rec.shares_held)

    def test_optional_columns_parsed(self):
        header = HEADER.rstrip("\n") + ",holder_role,shares_held,held_scrip_code,as_on_date,group\n"
        res = parse(GOOD.rstrip("\n") + ",Promoter,396257000,500470,2026-06-30,Tata\n", header=header)
        rec = res.records[0]
        self.assertEqual((rec.holder_role, rec.shares_held, rec.held_scrip_code, rec.as_on_date, rec.group),
                         ("Promoter", 396257000, "500470", date(2026, 6, 30), "Tata"))

    def test_empty_optional_values_become_none(self):
        header = HEADER.rstrip("\n") + ",shares_held,as_on_date\n"
        rec = parse(GOOD.rstrip("\n") + ",,\n", header=header).records[0]
        self.assertIsNone(rec.shares_held)
        self.assertIsNone(rec.as_on_date)

    def test_columns_in_any_order_and_extra_columns_ignored(self):
        res = parse("corporate,x,2026-07-15,12.5,Holder Co,Held Co\n",
                    header="entity_type,note,filing_date,stake_pct,holder_name,held_name\n")
        self.assertEqual(res.records[0].holder_name, "Holder Co")

    def test_quoted_field_with_comma(self):
        res = parse('"Acacia Partners, Lp",Tata Steel Ltd,1.2,2026-07-15,corporate\n')
        self.assertEqual(res.records[0].holder_name, "Acacia Partners, Lp")

    def test_whitespace_and_entity_type_case(self):
        rec = parse("  Tata Sons Ltd , Tata Steel Ltd , 5 , 2026-07-15 , Corporate \n").records[0]
        self.assertEqual((rec.holder_name, rec.stake_pct, rec.entity_type), ("Tata Sons Ltd", 5.0, "corporate"))

    def test_blank_lines_skipped(self):
        res = parse("\n", GOOD, ",,,,\n", GOOD.replace("31.74", "1"))
        self.assertEqual((len(res.records), len(res.rejected)), (2, 0))
        self.assertEqual([r.line for r in res.records], [3, 5])

    def test_stake_boundaries_are_valid(self):
        res = parse(GOOD.replace("31.74", "0"), GOOD.replace("31.74", "100"))
        self.assertEqual((len(res.records), res.flagged), (2, []))

    def test_byte_order_mark(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "bom.csv"
            p.write_text(HEADER + GOOD, encoding="utf-8-sig")
            self.assertEqual(len(read_records(p).records), 1)


class Malformed(unittest.TestCase):
    def assertRejected(self, row, fragment):
        res = parse(row)
        self.assertEqual(res.records, [])
        self.assertEqual(len(res.rejected), 1, res.rejected)
        issue = res.rejected[0]
        self.assertEqual((issue.kind, issue.line), ("malformed", 2))
        self.assertIn(fragment, issue.message)

    def test_too_few_fields(self):
        self.assertRejected("Tata Sons,Tata Steel,31.74,2026-07-15\n", "expected 5 fields, found 4")

    def test_too_many_fields(self):
        self.assertRejected(GOOD.rstrip("\n") + ",extra\n", "found 6")

    def test_empty_required_fields(self):
        for i, col in enumerate(("holder_name", "held_name", "stake_pct", "filing_date", "entity_type")):
            cells = GOOD.rstrip("\n").split(",")
            cells[i] = "  "
            with self.subTest(col=col):
                self.assertRejected(",".join(cells) + "\n", f"{col} is empty")

    def test_stake_not_numeric(self):
        for bad in ("abc", "31.74%", "1,5"):
            with self.subTest(bad=bad):
                self.assertRejected(f'Tata Sons,Tata Steel,"{bad}",2026-07-15,corporate\n', "stake_pct")

    def test_stake_not_finite(self):
        for bad in ("nan", "inf", "-inf"):
            with self.subTest(bad=bad):
                self.assertRejected(GOOD.replace("31.74", bad), "not a finite number")

    def test_bad_dates(self):
        for bad in ("15/07/2026", "2026-13-01", "2026-02-30", "yesterday"):
            with self.subTest(bad=bad):
                self.assertRejected(GOOD.replace("2026-07-15", bad), "filing_date")

    def test_unknown_entity_type(self):
        self.assertRejected(GOOD.replace("corporate", "company"), "entity_type")

    def test_bad_shares_held(self):
        header = HEADER.rstrip("\n") + ",shares_held\n"
        for bad in ("-5", "1.5", "lots"):
            with self.subTest(bad=bad):
                res = parse(GOOD.rstrip("\n") + f",{bad}\n", header=header)
                self.assertEqual((res.records, len(res.rejected)), ([], 1))
                self.assertIn("shares_held", res.rejected[0].message)

    def test_name_with_nothing_alphanumeric(self):
        self.assertRejected("-- $ --,Tata Steel,1,2026-07-15,corporate\n", "holder_name")

    def test_bad_rows_do_not_stop_good_ones(self):
        res = parse(GOOD, "garbage\n", GOOD.replace("31.74", "x"), GOOD.replace("Steel", "Power"))
        self.assertEqual(len(res.records), 2)
        self.assertEqual([i.line for i in res.rejected], [3, 4])
        self.assertEqual(res.rows_read, 4)

    def test_rejected_row_keeps_raw_cells(self):
        res = parse("a,b\n")
        self.assertEqual(res.rejected[0].row, ("a", "b"))

    def test_control_characters_in_name(self):
        self.assertRejected("Tata\0 Sons,Tata Steel,1,2026-07-15,corporate\n", "control character")
        self.assertRejected('Tata Sons,"Tata\x07Steel",1,2026-07-15,corporate\n', "control character")


class Flagged(unittest.TestCase):
    def test_stake_above_100(self):
        res = parse(GOOD.replace("31.74", "100.01"))
        self.assertEqual((res.records, [i.kind for i in res.flagged]), ([], ["stake_out_of_range"]))

    def test_negative_stake(self):
        res = parse(GOOD.replace("31.74", "-0.5"))
        self.assertEqual([i.kind for i in res.flagged], ["stake_out_of_range"])

    def test_self_ownership_exact(self):
        res = parse("Tata Steel Ltd,Tata Steel Ltd,1,2026-07-15,corporate\n")
        self.assertEqual((res.records, [i.kind for i in res.flagged]), ([], ["self_ownership"]))

    def test_self_ownership_after_normalising(self):
        res = parse("TATA STEEL LIMITED,Tata Steel Ltd.,1,2026-07-15,corporate\n")
        self.assertEqual([i.kind for i in res.flagged], ["self_ownership"])
        self.assertEqual(res.flagged[0].line, 2)


class FileLevel(unittest.TestCase):
    def test_empty_file(self):
        with self.assertRaisesRegex(IngestError, "empty"):
            parse_text("")

    def test_missing_required_column(self):
        with self.assertRaisesRegex(IngestError, "stake_pct"):
            parse_text("holder_name,held_name,filing_date,entity_type\n")

    def test_duplicate_column(self):
        with self.assertRaisesRegex(IngestError, "duplicate"):
            parse_text(HEADER.rstrip("\n") + ",stake_pct\n")

    def test_header_only_is_empty_result(self):
        res = parse_text(HEADER)
        self.assertEqual((res.records, res.rejected, res.flagged), ([], [], []))


class ProjectDataset(unittest.TestCase):
    """The Phase 1 deliverable must load in full."""

    def test_phase1_csv_loads_cleanly(self):
        res = read_records(ROOT / "data" / "ownership_relations.csv")
        self.assertEqual((len(res.records), res.rejected, res.flagged), (946, [], []))
        self.assertEqual(len({r.held_norm for r in res.records}), 46)
        self.assertTrue(all(0 <= r.stake_pct <= 100 for r in res.records))


if __name__ == "__main__":
    unittest.main()
