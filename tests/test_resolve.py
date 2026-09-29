import csv
import unittest
from pathlib import Path

from ownership.er_eval import PAIRS, load_pairs, score
from ownership.ingest import parse_text, read_records
from ownership.resolve import (DisjointSet, build_index, holding_entity, holding_type,
                               match_key, strip_annotations, token_match)

ROOT = Path(__file__).resolve().parent.parent
HEADER = "holder_name,held_name,stake_pct,filing_date,entity_type,holder_cin,held_cin\n"


def records(*rows):
    """rows: (holder, held, entity_type[, holder_cin[, held_cin]])"""
    lines = []
    for r in rows:
        holder, held, etype, *cins = r
        cins += [""] * (2 - len(cins))
        lines.append(f'"{holder}","{held}",1,2026-06-30,{etype},{cins[0]},{cins[1]}\n')
    res = parse_text(HEADER + "".join(lines))
    assert not res.rejected and not res.flagged, (res.rejected, res.flagged)
    return res.records


def same(index, a, b):
    return index.entity_of(a).id == index.entity_of(b).id


class Annotations(unittest.TestCase):
    def test_holder_notes_are_removed(self):
        self.assertEqual(strip_annotations(
            "Shambho Trust (M V Subbiah and S Vellayan holds shares on behalf of Trust)"), "Shambho Trust")
        self.assertEqual(strip_annotations("INVESCO INDIA FOCUSED FUND (Through Multiple Schemes)"),
                         "INVESCO INDIA FOCUSED FUND")
        self.assertEqual(strip_annotations("DSP Midcap Fund (Various Accounts)"), "DSP Midcap Fund")

    def test_unclosed_note(self):
        self.assertEqual(strip_annotations(
            "Lakshmi Ramaswamy Family Trust (A A Alagammai & Lakshmi Ramaswamy holds shares on behalf of Trust"),
            "Lakshmi Ramaswamy Family Trust")

    def test_note_glued_to_its_neighbours(self):
        self.assertEqual(strip_annotations(
            "MurugappanArunachalamChildrenTrust(SigappiArunachalam,MAMArunachalam&AM MeyyammaiareTrustees)"),
            "MurugappanArunachalamChildrenTrust")

    def test_dash_tail_note(self):
        self.assertEqual(strip_annotations(
            "M V Subramanian Family Trust - M M Venkatachalam and M V Subramanian holds shares"),
            "M V Subramanian Family Trust")
        self.assertEqual(strip_annotations("HDFC MUTUAL FUND - HDFC MID-CAP FUND"),
                         "HDFC MUTUAL FUND - HDFC MID-CAP FUND")

    def test_brackets_that_are_part_of_the_name_stay(self):
        for name in ("Tata Teleservices (Maharashtra) Ltd", "Birla Industrial Finance (India) Limited",
                     "CC II (MAURITIUS) INC", "O.P.J Financial Services (P) Ltd"):
            with self.subTest(name=name):
                self.assertEqual(strip_annotations(name), name)

    def test_acronym_in_brackets(self):
        self.assertEqual(strip_annotations("Investor Educaton and Protection Fund(IEPF)"),
                         "Investor Educaton and Protection Fund")


class CapacityRules(unittest.TestCase):
    def check(self, raw, name, kind, rule):
        h = holding_entity(raw)
        self.assertEqual((h.name, h.kind, h.rule), (name, kind, rule))

    def test_behalf_of_named_trust(self):
        self.check("M M MURUGAPPAN (M M Murugappan & M M Muthiah holds shares on behalf of M M Muthiah Family Trust)",
                   "M M Muthiah Family Trust", "trust", "behalf_of")

    def test_behalf_of_the_firm(self):
        self.check("SUBBIAH.M.V, ALAGAPPAN M A and M M MURUGAPPAN holds on behalf of the firm Murugappa & Sons",
                   "Murugappa & Sons", "firm", "behalf_of")

    def test_behalf_of_generic_trust_is_just_a_note(self):
        self.check("Shambho Trust (M V Subbiah and S Vellayan holds shares on behalf of Trust)",
                   "Shambho Trust", None, "as_filed")

    def test_behalf_of_a_company_is_not_a_capacity(self):
        h = holding_entity("TRUSTEE HOLDING SHARES UNDER THE SCHEME OF MERGER OF HIL/IGCL/IGFL ON BEHALF OF HINDALCO")
        self.assertEqual(h.rule, "as_filed")

    def test_partner_of(self):
        self.check("M.A.Alagappan (Holds shares in the capacity of Partner of Kadamane Estates - Firm)",
                   "Kadamane Estates", "firm", "partner_of")

    def test_trustee_of(self):
        self.check("M M VENKATACHALAM, Trustee of M V Muthiah Family Trust",
                   "M V Muthiah Family Trust", "trust", "trustee_of")
        self.check("ARUN ALAGAPPAN Trustee of M A Alagappan Grandchildren Trust (AOP)",
                   "M A Alagappan Grandchildren Trust", "trust", "trustee_of")

    def test_karta_of_named_huf(self):
        self.check("M A M ARUNACHALAM - As Karta of M A Murugappan HUF", "M A Murugappan HUF", "huf", "karta_of")
        self.check("M M MURUGAPPAN As a karta of M M Muthiah HUF", "M M Muthiah HUF", "huf", "karta_of")

    def test_huf_name_first(self):
        self.check("M A Murugappan HUF rep. by M A M Arunachalam, Karta", "M A Murugappan HUF", "huf", "huf")
        self.check("DWARAKNATH REDDY HUF (P DWARAKNATH REDDY)", "DWARAKNATH REDDY HUF", "huf", "huf")

    def test_karta_capacity_without_huf_name(self):
        for raw in ("M A M ARUNACHALAM (in the capacity of Karta of HUF)",
                    "M A M ARUNACHALAM (in the capacity as Kartha of HUF)"):
            with self.subTest(raw=raw):
                self.check(raw, "M A M ARUNACHALAM HUF", "huf", "karta_capacity")

    def test_plain_names(self):
        self.check("Tata Sons Private Limited", "Tata Sons Private Limited", None, "as_filed")
        self.check("M V SUBBIAH", "M V SUBBIAH", None, "as_filed")

    def test_holding_type(self):
        self.assertEqual(holding_type("corporate", holding_entity("X Y HUF")), "individual")
        self.assertEqual(holding_type("individual", holding_entity("A B, Trustee of C D Trust")), "corporate")
        self.assertEqual(holding_type("individual", holding_entity("A B")), "individual")


class MatchKey(unittest.TestCase):
    def test_honorifics(self):
        self.assertEqual(match_key("Smt. Neerja Birla"), "neerja birla")
        self.assertEqual(match_key("MR.KUMARMANGALAM BIRLA"), "kumarmangalam birla")

    def test_company_form_words(self):
        self.assertEqual(match_key("Thai Rayon Public Co. Ltd."), match_key("Thai Rayon Public Company Limited"))
        self.assertEqual(match_key("PILANI INVESTMENT AND INDUSTRIES CORPORATION LIMITED"),
                         "pilani investment and industries")
        self.assertEqual(match_key("NPS TRUST- A/C"), "nps trust")

    def test_fly_abbreviation(self):
        self.assertEqual(match_key("M M Venkatachalam Fly Trust"), match_key("M M Venkatachalam Family Trust"))

    def test_never_empty(self):
        self.assertEqual(match_key("Company Limited"), "company")
        self.assertEqual(match_key("Mr"), "mr")


class TokenMatch(unittest.TestCase):
    def test_spelling_variants(self):
        for a, b in [("governement of singapore", "government of singapore"),
                     ("vikram holding", "vikram holdings"),
                     ("vedhika meyyammai arunachalam", "vedika meyyammai arunachalam"),
                     ("investor educaton and protection fund", "investor education and protection fund")]:
            with self.subTest(a=a):
                self.assertTrue(token_match(a, b))

    def test_spacing_variants(self):
        self.assertTrue(token_match("lakshmi chocka lingam", "lakshmi chockalingam"))
        self.assertTrue(token_match("murugappanarunachalamchildrentrust", "murugappan arunachalam children trust"))

    def test_different_entities_with_similar_names(self):
        for a, b in [("quant mutual fund quant mid cap fund", "quant mutual fund quant small cap fund"),
                     ("kotak mahindra trustee co ltd ac kotak nifty 100", "kotak mahindra trustee co ltd ac kotak nifty chem"),
                     ("sbi nifty 50 etf", "sbi nifty 500 etf"),
                     ("mv muthiah family trust", "mm muthiah family trust"),
                     ("ma alagappan holdings", "ma murugappan holdings"),
                     ("deeptha reddy", "neetha reddy"),
                     ("tata teleservices", "tata teleservices maharashtra"),
                     ("pi opportunities aif v", "pi opportunities fund i")]:
            with self.subTest(a=a):
                self.assertFalse(token_match(a, b))

    def test_at_most_half_the_tokens_differ(self):
        self.assertFalse(token_match("aaaaa bbbbb", "aaaab bbbbc"))
        self.assertTrue(token_match("aaaaa bbbbb", "aaaaa bbbbc"))


class UnionFind(unittest.TestCase):
    def test_union_and_find(self):
        ds = DisjointSet()
        for x in "abcd":
            ds.add(x)
        self.assertTrue(ds.union("a", "b"))
        self.assertTrue(ds.union("c", "d"))
        self.assertFalse(ds.union("b", "a"))
        self.assertTrue(ds.union("a", "d"))
        self.assertEqual(len({ds.find(x) for x in "abcd"}), 1)

    def test_conflicting_cins_are_never_joined(self):
        ds = DisjointSet()
        ds.add("a", "U1")
        ds.add("b", "U2")
        ds.add("c")
        self.assertTrue(ds.union("a", "c"))
        self.assertFalse(ds.union("c", "b"))
        self.assertNotEqual(ds.find("a"), ds.find("b"))


class BuildIndex(unittest.TestCase):
    def test_exact_capacity_and_type_separation(self):
        idx = build_index(records(
            ("M V SUBBIAH, trustee of Shambho Trust", "Acme Ltd", "corporate"),
            ("Shambho Trust (M V Subbiah and S Vellayan hold shares)", "Acme Ltd", "corporate"),
            ("M V SUBBIAH", "Acme Ltd", "individual"),
            ("M V Subbiah HUF (M V Subbiah holds shares in the capacity of Karta)", "Acme Ltd", "individual"),
        ))
        self.assertTrue(same(idx, "M V SUBBIAH, trustee of Shambho Trust",
                             "Shambho Trust (M V Subbiah and S Vellayan hold shares)"))
        self.assertFalse(same(idx, "M V SUBBIAH", "M V SUBBIAH, trustee of Shambho Trust"))
        self.assertFalse(same(idx, "M V SUBBIAH", "M V Subbiah HUF (M V Subbiah holds shares in the capacity of Karta)"))
        self.assertEqual(idx.entity_of("M V SUBBIAH, trustee of Shambho Trust").name, "Shambho Trust")
        self.assertEqual(len(idx), 4)     # trust, person, HUF, Acme

    def test_listed_company_keeps_bse_name(self):
        idx = build_index(records(("TATA SONS PRIVATE LIMITED", "Tata Steel Ltd", "corporate"),
                                  ("TATA STEEL LIMITED", "Tata Power Company Ltd", "corporate")))
        e = idx.entity_of("TATA STEEL LIMITED")
        self.assertEqual((e.name, e.listed), ("Tata Steel Ltd", True))

    def test_truncation_needs_a_unique_mid_word_completion(self):
        idx = build_index(records(
            ("NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA MUL", "Acme Ltd", "corporate"),
            ("Nippon Life India Trustee Ltd-A/C Nippon India Multi Cap Fund", "Acme Ltd", "corporate"),
            ("AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL F", "Acme Ltd", "corporate"),
            ("AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL FUND", "Acme Ltd", "corporate"),
            ("AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL FUND A/C AXIS MIDCAP FUND", "Acme Ltd", "corporate"),
            ("Tata Teleservices Ltd", "Acme Ltd", "corporate"),
            ("Tata Teleservices (Maharashtra) Ltd", "Acme Ltd", "corporate"),
        ))
        self.assertTrue(same(idx, "NIPPON LIFE INDIA TRUSTEE LTD-A/C NIPPON INDIA MUL",
                             "Nippon Life India Trustee Ltd-A/C Nippon India Multi Cap Fund"))
        self.assertFalse(same(idx, "AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL F",       # two completions
                              "AXIS MUTUAL FUND TRUSTEE LIMITED A/C AXIS MUTUAL FUND"))
        self.assertFalse(same(idx, "Tata Teleservices Ltd", "Tata Teleservices (Maharashtra) Ltd"))  # whole word

    def test_fuzzy_merge_and_its_ablation(self):
        rows = records(("Governement of Singapore", "Acme Ltd", "corporate"),
                       ("Government Of Singapore", "Acme Ltd", "corporate"))
        self.assertTrue(same(build_index(rows), "Governement of Singapore", "Government Of Singapore"))
        self.assertFalse(same(build_index(rows, fuzzy=False), "Governement of Singapore", "Government Of Singapore"))

    def test_cin_is_authoritative(self):
        idx = build_index(records(
            ("Old Name Holdings Pvt Ltd", "Acme Ltd", "corporate", "U65990MH1999PTC000001"),
            ("New Name Investments Ltd", "Acme Ltd", "corporate", "U65990MH1999PTC000001"),
            ("Vikram Holding Pvt Ltd", "Acme Ltd", "corporate", "U11111MH2000PTC000002"),
            ("Vikram Holdings Pvt Ltd", "Acme Ltd", "corporate", "U22222MH2000PTC000003"),
        ))
        self.assertTrue(same(idx, "Old Name Holdings Pvt Ltd", "New Name Investments Ltd"))     # same CIN
        self.assertFalse(same(idx, "Vikram Holding Pvt Ltd", "Vikram Holdings Pvt Ltd"))        # CINs differ
        self.assertEqual(idx.entity_of("New Name Investments Ltd").cin, "U65990MH1999PTC000001")

    def test_lookup(self):
        idx = build_index(records(("Tata Sons Private Limited", "Tata Steel Ltd", "corporate"),
                                  ("Tata Sons Pvt Ltd", "Tata Power Company Ltd", "corporate")))
        self.assertEqual(idx.lookup("tata sons")[0].name, "Tata Sons Private Limited")
        self.assertEqual({e.name for e in idx.lookup("Tata")},
                         {"Tata Sons Private Limited", "Tata Steel Ltd", "Tata Power Company Ltd"})
        self.assertEqual(idx.lookup("tata stel")[0].name, "Tata Steel Ltd")
        self.assertEqual(idx.lookup("zzzzzzzz"), [])

    def test_unknown_name(self):
        idx = build_index(records(("A B", "Acme Ltd", "individual")))
        with self.assertRaises(KeyError):
            idx.entity_of("nobody")


class ProjectDataset(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = read_records(ROOT / "data" / "ownership_relations.csv").records
        cls.index = build_index(cls.records)

    def test_every_name_resolves(self):
        for r in self.records:
            self.index.entity_of(r.holder_name)
            self.assertTrue(self.index.entity_of(r.held_name).listed)
        self.assertEqual(sum(e.listed for e in self.index.entities), 46)

    def test_ids_are_unique_and_every_variant_is_listed_once(self):
        ids = [e.id for e in self.index.entities]
        self.assertEqual(len(ids), len(set(ids)))
        variants = [v for e in self.index.entities for v in e.variants]
        self.assertEqual(len(variants), len(set(variants)))

    def test_known_resolutions(self):
        trust = self.index.entity_of("M M MURUGAPPAN, Trustee of M M Muthiah Family Trust")
        self.assertEqual(trust.name, "M M Muthiah Family Trust")
        self.assertEqual(len(trust.variants), 6)
        self.assertTrue(same(self.index, "THE INDIAN HOTELS COMPANY LIMITED", "Indian Hotels Company Ltd"))
        self.assertFalse(same(self.index, "Tata Motors Ltd", "Tata Motors Passenger Vehicles Ltd"))

    def test_entity_index_file_matches(self):
        with open(ROOT / "data" / "entity_index.csv", newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), self.index.stats["name_variants"])
        for row in rows:
            self.assertEqual(self.index.entity_of(row["name_variant"], row["filed_type"]).id, row["entity_id"])


class ValidationPairs(unittest.TestCase):
    def test_labelled_file(self):
        pairs = load_pairs(PAIRS)
        self.assertEqual(len(pairs), 100)
        self.assertEqual({p["band"] for p in pairs}, {"<0.25", "0.25-0.5", "0.5-0.75", ">=0.75"})

    def test_full_method_scores(self):
        s = score(load_pairs(PAIRS), build_index(read_records(ROOT / "data" / "ownership_relations.csv").records))
        self.assertEqual((s["tp"], s["fp"], s["fn"]), (24, 0, 2))


if __name__ == "__main__":
    unittest.main()
