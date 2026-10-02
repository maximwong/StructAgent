import unittest

from tools.floor.source_evidence import number_value, quoted_value
from examples.language_acceptance import qualifies
from agent.parameter_parser import ParseResult


class SourceEvidenceTests(unittest.TestCase):
    def test_chinese_numbers(self):
        for text, expected in (("六", 6), ("五点四", 5.4), ("二点八", 2.8), ("两千", 2000),
                               ("六千零五十", 6050), ("一万二千三百四十五", 12345), ("负二点八", -2.8)):
            self.assertEqual(number_value(text), expected)

    def test_length_units_pairs_and_shared_units(self):
        for text, x, y in (("5.4m×6000mm", 5400, 6000), ("六乘六米", 6000, 6000),
                           ("6 metres by 6 metres", 6000, 6000)):
            self.assertEqual(quoted_value("span_x", text, 0), x)
            self.assertEqual(quoted_value("span_y", text, 1), y)

    def test_centimetres_and_grouped_or_scientific_numbers(self):
        for text in ("600厘米", "600cm", "6,000mm", "6e3mm"):
            self.assertEqual(quoted_value("span_x", text, 0), 6000)

    def test_load_units_and_order(self):
        for text in ("2.8kN/m²", "2.8kN/m2", "2.8kN/m^2", "2.8kPa", "2.8 kN per square metre",
                     "二点八千牛每平方米", "每平方米2.8千牛", "2.8kN/平方米"):
            self.assertEqual(quoted_value("live_load", text, 0), 2.8)

    def test_source_quotes_require_units_and_unique_value(self):
        for field, text in (("span_x", "6"), ("span_x", "6m²"), ("live_load", "2.8"), ("live_load", "2.8kg/m²"),
                            ("live_load", "2kPa和3kPa"), ("concrete", "C30和C35")):
            with self.assertRaises(ValueError):
                quoted_value(field, text, 0)

    def test_language_acceptance_distinguishes_expected_clarification_from_success(self):
        case = {"status": "needs_input", "missing_fields": ["live_load"]}
        self.assertTrue(qualifies(case, ParseResult("needs_input", missing_fields=["live_load"])))
        self.assertFalse(qualifies(case, ParseResult("needs_input")))
        self.assertFalse(qualifies(case, ParseResult("error", missing_fields=["live_load"])))
