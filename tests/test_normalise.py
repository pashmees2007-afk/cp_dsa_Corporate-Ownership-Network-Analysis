import unittest

from ownership.normalise import normalise_name as norm


class LegalSuffixes(unittest.TestCase):
    def test_each_plan_suffix_is_removed(self):
        for suffix in ("Ltd", "Limited", "Pvt", "Private", "LLP"):
            with self.subTest(suffix=suffix):
                self.assertEqual(norm(f"Acme {suffix}"), "acme")

    def test_stacked_suffixes_are_all_removed(self):
        self.assertEqual(norm("TATA SONS PRIVATE LIMITED"), "tata sons")
        self.assertEqual(norm("Birla Group Holdings Pvt. Limited"), "birla group holdings")
        self.assertEqual(norm("Tata Sons Pvt. Ltd."), "tata sons")

    def test_suffix_word_inside_name_is_kept(self):
        self.assertEqual(norm("XYZ Private Equity Fund"), "xyz private equity fund")
        self.assertEqual(norm("Limited Brands Holdings"), "limited brands holdings")

    def test_name_of_only_suffixes_is_not_emptied(self):
        self.assertEqual(norm("Private Limited"), "private limited")


class CaseAndPunctuation(unittest.TestCase):
    def test_case_folding(self):
        self.assertEqual(norm("GRASIM INDUSTRIES LIMITED"), norm("Grasim Industries Ltd"))

    def test_punctuation_becomes_space(self):
        self.assertEqual(norm("HDFC Trustee Company Ltd./HDFC Large Cap Fund"),
                         "hdfc trustee company ltd hdfc large cap fund")
        self.assertEqual(norm("Hdfc Mutual Fund - Hdfc Mid-Cap Fund"),
                         "hdfc mutual fund hdfc mid cap fund")

    def test_apostrophe_is_deleted_not_spaced(self):
        self.assertEqual(norm("Arun Murugappan Children's Trust"), "arun murugappan childrens trust")

    def test_ampersand_matches_and(self):
        self.assertEqual(norm("Bandhan Large & Mid Cap Fund"), norm("Bandhan Large And Mid Cap Fund"))

    def test_bse_dollar_marker(self):
        self.assertEqual(norm("TRF Ltd-$"), "trf")

    def test_whitespace_collapsed(self):
        self.assertEqual(norm("  Tata   Steel\tLtd  "), "tata steel")

    def test_nothing_alphanumeric_gives_empty(self):
        self.assertEqual(norm("-- $ --"), "")
        self.assertEqual(norm(""), "")


class Initials(unittest.TestCase):
    def test_dotted_spaced_and_joined_initials_agree(self):
        variants = ["E.I.D.PARRY (INDIA) LTD.", "E.I.D. Parry (India) Ltd.",
                    "E.I.D.PARRY (INDIA) Limited", "EID Parry India Ltd"]
        self.assertEqual({norm(v) for v in variants}, {"eid parry india"})

    def test_spaced_initials_join(self):
        self.assertEqual(norm("M A M ARUNACHALAM"), norm("MAM Arunachalam"))

    def test_lone_initial_is_kept(self):
        self.assertEqual(norm("A. Keertika Unnamalai"), "a keertika unnamalai")
        self.assertEqual(norm("A.KEERTIKA UNNAMALAI"), "a keertika unnamalai")


class Annotations(unittest.TestCase):
    def test_formerly_note_is_dropped(self):
        self.assertEqual(
            norm("ADITYA BIRLA REAL ESTATE LIMITED (FORMERLY CENTURY TEXTILES AND INDUSTRIES LIMITED)"),
            "aditya birla real estate")

    def test_formerly_variants_agree_with_current_name(self):
        variants = ["M A MURUGAPPAN HOLDINGS LLP (Formerly M A MURUGAPPAN HOLDINGS PVT LTD)",
                    "M A MURUGAPPAN HOLDINGS LLP (Formerly, M A Murugappan Holdings Private Limited)",
                    "M A MURUGAPPAN HOLDINGS LLP (Formerly, M A Murugappan Holdings Pvt. Ltd).",
                    "M A Murugappan Holdings LLP"]
        self.assertEqual({norm(v) for v in variants}, {"ma murugappan holdings"})

    def test_unclosed_formerly_note(self):
        self.assertEqual(norm("Acme Ltd (Formerly Old Acme Pvt Ltd"), "acme")

    def test_other_parentheses_keep_their_text(self):
        self.assertEqual(norm("Tata Teleservices (Maharashtra) Ltd"), "tata teleservices maharashtra")

    def test_leading_article(self):
        self.assertEqual(norm("THE TATA POWER COMPANY LIMITED"), norm("Tata Power Company Ltd"))
        self.assertEqual(norm("The"), "the")


if __name__ == "__main__":
    unittest.main()
