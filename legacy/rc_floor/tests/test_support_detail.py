import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from PIL import ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from engine import calculate
from scaled_figures import dimension_figure
from report_support_detail import geometry
from cad_scene import make_scene


class SupportDetailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results = {case: calculate(json.loads((ROOT / (case + '.json')).read_text(encoding='utf-8')))
                       for case in ('sample1', 'changed')}

    def test_full_t_section_has_no_seam_across_web(self):
        for case, r in self.results.items():
            g = geometry(r)
            w, h, height = (g[k] for k in ('support_width_mm', 'slab_thickness_mm', 'beam_total_height_mm'))
            self.assertFalse(g['truncated'])
            self.assertEqual(h + g['visible_below_slab_mm'], height)
            self.assertEqual(g['lower_boundary'], [[-w/2, h-height], [w/2, h-height]])
            self.assertNotIn(([-w/2, 0], [w/2, 0]), g['outline_lines'])
            self.assertEqual(g['dimension_values_mm'], [w/2, w/2, w])
            self.assertEqual(height, 400 if case == 'sample1' else 450)

    def test_parameter_linkage_including_reference_dimensions(self):
        p = copy.deepcopy(self.results['sample1']['input'])
        p['loads']['live_kN_m2'] = 2
        p['secondary'].update(b_mm=240, h_mm=600)
        p['main']['h_mm'] = 700
        r = calculate(p)
        g = geometry(r)
        self.assertEqual(g['dimension_values_mm'], [120, 120, 240])
        self.assertEqual(g['beam_total_height_mm'], 600)
        self.assertEqual(g['slab_thickness_mm'], 80)
        dimension_figure(r, 'slab')
        p['slab']['h_mm'] = 100
        r = calculate(p)
        self.assertEqual(geometry(r)['slab_thickness_mm'], 100)
        self.assertEqual(geometry(r)['visible_below_slab_mm'], 500)
        dimension_figure(r, 'slab')

    def test_only_target_pixels_change(self):
        for r in self.results.values():
            with patch('report_support_detail.replace_slab_support', lambda *args: None):
                before = dimension_figure(r, 'slab')
            after = dimension_figure(r, 'slab')
            self.assertEqual(before.image.size, after.image.size)
            changed = ImageChops.difference(before.image, after.image).getbbox()
            box = after.support_detail['pixel_box']
            self.assertIsNotNone(changed)
            self.assertGreaterEqual(changed[0], box[0])
            self.assertGreaterEqual(changed[1], box[1])
            self.assertLessEqual(changed[2], box[2])
            self.assertLessEqual(changed[3], box[3])

    def test_render_does_not_mutate_calculation_or_cad(self):
        for r in self.results.values():
            before = copy.deepcopy(r)
            cad = copy.deepcopy(make_scene(r).groups)
            dimension_figure(r, 'slab')
            self.assertEqual(before, r)
            self.assertEqual(cad, make_scene(r).groups)

    def test_true_scale_and_annotation_bounds(self):
        for r in self.results.values():
            c = dimension_figure(r, 'slab')
            m = c.support_detail
            g = m['geometry']
            width, height = m['pixel_box'][2]-m['pixel_box'][0], m['pixel_box'][3]-m['pixel_box'][1]
            for dim in m['vertical_dimensions']:
                self.assertAlmostEqual(dim['y2_px']-dim['y1_px'], dim['value_mm']*m['pixels_per_mm'])
            self.assertEqual([d['value_mm'] for d in m['vertical_dimensions']],
                             [g['slab_thickness_mm'], g['beam_total_height_mm']])
            for label in m['label_bounds']:
                a,b,x,y=label['bounds']
                self.assertGreaterEqual(min(a,b),0)
                self.assertLessEqual(x,width)
                self.assertLessEqual(y,height)

    def test_invalid_or_inconsistent_geometry_is_rejected(self):
        r = copy.deepcopy(self.results['sample1'])
        r['dimension_geometry']['slab']['support_width_mm'] += 10
        with self.assertRaisesRegex(ValueError, '不一致'):
            geometry(r)
        r = copy.deepcopy(self.results['sample1'])
        r['secondary'] = {}  # Not the authoritative input; must have no effect.
        self.assertEqual(geometry(r)['beam_total_height_mm'], 400)
        r['input']['secondary']['h_mm'] = r['input']['slab']['h_mm']
        with self.assertRaisesRegex(ValueError, '无效'):
            geometry(r)


if __name__ == '__main__':
    unittest.main()
