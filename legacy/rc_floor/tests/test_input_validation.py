import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app import MATERIALS
from engine import calculate
from legacy_core import run
from input_validation import CONCRETE_MATERIALS, validate_engineering_inputs


class InputValidationTests(unittest.TestCase):
    def setUp(self):
        self.p = json.loads((ROOT / 'sample1.json').read_text(encoding='utf-8'))

    def test_all_existing_concrete_grades_and_gui_share_table(self):
        self.assertIs(MATERIALS, CONCRETE_MATERIALS)
        self.assertEqual(MATERIALS, {'C25': (11.9, 1.27), 'C30': (14.3, 1.43), 'C35': (16.7, 1.57), 'C40': (19.1, 1.71)})
        for grade, (fc, ft) in MATERIALS.items():
            with self.subTest(grade=grade):
                p = copy.deepcopy(self.p)
                p['materials'].update(concrete=grade, fc_MPa=fc, ft_MPa=ft)
                before = copy.deepcopy(p)
                validate_engineering_inputs(p)
                self.assertEqual(p, before)

    def test_mismatched_materials_rejected_by_both_entrypoints(self):
        changes = {'fc_MPa': 11.9, 'ft_MPa': 1.27, 'slab_fy_MPa': 360,
                   'beam_fy_MPa': 270, 'stirrup_fy_MPa': 360}
        for field, wrong in changes.items():
            for entry in (calculate, run):
                with self.subTest(field=field, entry=entry.__name__):
                    p = copy.deepcopy(self.p); p['materials'][field] = wrong
                    before = copy.deepcopy(p)
                    with self.assertRaises(ValueError) as ctx:
                        entry(p)
                    self.assertIn('materials.' + field, str(ctx.exception))
                    self.assertIn(repr(wrong), str(ctx.exception))
                    self.assertIn('预期', str(ctx.exception))
                    self.assertEqual(p, before)

    def test_unsupported_grades_rejected(self):
        for field, wrong in [('concrete', 'C60'), ('beam_steel', 'HRB500'),
                             ('slab_steel', 'HRB400'), ('stirrup_steel', 'HRB400')]:
            for entry in (calculate, run):
                with self.subTest(field=field, entry=entry.__name__):
                    p = copy.deepcopy(self.p); p['materials'][field] = wrong
                    with self.assertRaisesRegex(ValueError, 'materials.' + field):
                        entry(p)

    def test_every_numeric_leaf_rejects_both_booleans(self):
        def leaves(value, path=()):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield from leaves(child, path + (key,))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from leaves(child, path + (index,))
            elif type(value) in (int, float):
                yield path
        for path in leaves(self.p):
            for wrong in (True, False):
                for entry in (calculate, run):
                    with self.subTest(path=path, value=wrong, entry=entry.__name__):
                        p = copy.deepcopy(self.p); target = p
                        for part in path[:-1]:
                            target = target[part]
                        target[path[-1]] = wrong
                        with self.assertRaisesRegex(ValueError, '布尔值'):
                            entry(p)

    def test_valid_boolean_flag_and_nonfinite_numbers(self):
        for flag in (True, False):
            p = copy.deepcopy(self.p); p['report']['allow_arch'] = flag
            self.assertTrue(calculate(p)['slab'])
            self.assertTrue(run(p)['slab'])
        for wrong in (float('nan'), float('inf'), '2.0', None):
            p = copy.deepcopy(self.p); p['loads']['live_kN_m2'] = wrong
            for entry in (calculate, run):
                with self.assertRaisesRegex(ValueError, 'loads.live_kN_m2'):
                    entry(p)

    def test_validation_precedes_arithmetic(self):
        p = copy.deepcopy(self.p); p['report']['anchor_ribbed_factor'] = True
        with patch('engine.legacy_run', side_effect=AssertionError('calculation entered')):
            with self.assertRaisesRegex(ValueError, 'report.anchor_ribbed_factor'):
                calculate(p)
        p = copy.deepcopy(self.p); p['loads']['live_kN_m2'] = True
        with patch('legacy_core.slab_design', side_effect=AssertionError('calculation entered')):
            with self.assertRaisesRegex(ValueError, 'loads.live_kN_m2'):
                run(p)

    def test_three_fixtures_remain_accepted(self):
        for name in ('sample1', 'changed', 'demo_a'):
            p = json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8-sig'))
            before = copy.deepcopy(p)
            for entry in (calculate, run):
                result = entry(p)
                self.assertEqual(len(result['slab']), 6)
                self.assertEqual(len(result['secondary']), 4)
                self.assertEqual(len(result['main']), 4)
            self.assertEqual(p, before)


if __name__ == '__main__':
    unittest.main()
