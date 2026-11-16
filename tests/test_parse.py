"""Checks the results-page parser. Runs before every fetch, so a broken parser stops the run
instead of writing bad data. Run by hand with: python -m unittest discover -s tests"""
import json
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import fetch_results as fr  # noqa: E402

# Shaped like a real GMA results page (Saturday, Nov 14, 2026).
PAGE = """<html><body>
<p>Here are the PCSO lotto results for Saturday: Ultra Lotto 6/58, Grand Lotto 6/55, 4-Digit and more.</p>
<h3><a href="/x">2D 2PM:</a></h3><p>30 28</p><p>P4,000</p>
<h3><a href="/x">2D 5PM:</a></h3><p>25 30</p><p>P4,000</p>
<h3><a href="/x">2D 9PM:</a></h3><p>13 17</p><p>P4,000</p>
<h3><a href="/x">Swertres 2PM:</a></h3><p>6 6 3</p><p>P4,500</p>
<h3><a href="/x">Swertres 5PM:</a></h3><p>2 5 5</p><p>P4,500</p>
<h3><a href="/x">Swertres 9PM:</a></h3><p>2 7 5</p><p>P4,500</p>
<h3><a href="/x">6D Lotto:</a></h3><p>1 1 8 6 3 9</p><p>P8,025,201.56</p>
<h3><a href="/x">Lotto 6/42:</a></h3><p>28 31 38 22 18 04</p><p>P19,597,809.62</p>
<h3><a href="/x">Grand Lotto 6/55:</a></h3><p>30 28 41 44 04 31</p><p>P365,508,104.29</p>
<h3><a href="/x">Ultra Lotto 6/58:</a></h3>
<h3><a href="/x">4D Lotto:</a></h3>
</body></html>"""
DAY = date(2026, 11, 14)


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.lines = fr.page_lines(PAGE)

    def test_lotto(self):
        got = {d["game"]: d for d in fr.parse_lotto(self.lines, DAY)}
        self.assertEqual(set(got), {"6/42", "6/55"})          # 6/58 is listed with no numbers
        self.assertEqual(got["6/42"]["numbers"], [28, 31, 38, 22, 18, 4])
        self.assertEqual(got["6/42"]["jackpot"], 19597809.62)
        self.assertEqual(got["6/55"]["date"], "2026-11-14")

    def test_digits(self):
        got = {(d["game"], d["time"]): d for d in fr.parse_digits(self.lines, DAY)}
        self.assertEqual(len(got), 7)                          # 3 x 2D, 3 x 3D, 1 x 6D; 4D has no numbers
        self.assertEqual(got[("2D", "9PM")]["numbers"], [13, 17])
        self.assertEqual(got[("3D", "2PM")]["numbers"], [6, 6, 3])
        self.assertEqual(got[("3D", "9PM")]["prize"], 4500.0)
        self.assertEqual(got[("6D", "9PM")]["numbers"], [1, 1, 8, 6, 3, 9])
        self.assertNotIn(("4D", "9PM"), got)

    def test_other_heading_styles(self):
        lines = ["EZ2 9 PM", "07-25", "4-Digit:", "6 9 8 1", "P39,703.00", "3D Lotto 11AM:", "0 0 9"]
        got = {(d["game"], d["time"]): d["numbers"] for d in fr.parse_digits(lines, DAY)}
        self.assertEqual(got, {("2D", "9PM"): [7, 25], ("4D", "9PM"): [6, 9, 8, 1], ("3D", "11AM"): [0, 0, 9]})

    def test_bad_numbers_are_rejected(self):
        self.assertEqual(fr.parse_lotto(["Lotto 6/42:", "28 31 38 22 18 43"], DAY), [])   # 43 is too high
        self.assertEqual(fr.parse_lotto(["Lotto 6/42:", "28 28 38 22 18 04"], DAY), [])   # repeated number
        self.assertEqual(fr.parse_digits(["2D 9PM:", "32 05"], DAY), [])                   # 2D goes up to 31
        self.assertEqual(fr.parse_digits(["Swertres:", "1 2 3"], DAY), [])                 # no draw time

    def test_off_schedule(self):
        today = date(2026, 11, 16)
        sat = {"game": "6/55", "date": "2026-11-14"}       # 6/55 draws Mon, Wed, Sat
        sun = {"game": "6/55", "date": "2026-11-15"}
        old = {"game": "6/55", "date": "2024-03-03"}       # a Sunday long ago: not judged
        self.assertFalse(fr.off_schedule(sat, today))
        self.assertTrue(fr.off_schedule(sun, today))
        self.assertFalse(fr.off_schedule(old, today))

    def test_output_is_valid_compact_json(self):
        draws = fr.parse_lotto(self.lines, DAY)
        text = fr.dump(draws)
        self.assertEqual(json.loads(text)["draws"], draws)
        self.assertEqual(text.count("\n"), len(draws) + 5)   # one line per draw
        self.assertEqual(fr.hour_of("2PM"), 14)
        self.assertEqual(fr.hour_of("9PM"), 21)


if __name__ == "__main__":
    unittest.main()
