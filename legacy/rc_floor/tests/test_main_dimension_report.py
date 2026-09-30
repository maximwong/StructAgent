import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from cad_scene import make_scene
from main_dimension_report import layout,figure


class MainDimensionReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases={n:calculate(json.loads((ROOT/(n+'.json')).read_text(encoding='utf-8'))) for n in ('sample1','changed')}

    def test_hidden_projections_inside_main_beam(self):
        for r in self.cases.values():
            g=layout(r);self.assertEqual(len(g['intersections_mm']),6)
            for a,b in g['hidden_projection']:
                for x,y in (a,b):
                    self.assertGreaterEqual(y,g['h']-g['secondary_h'])
                    self.assertLessEqual(y,g['h']-g['slab_h'])
                    self.assertTrue(g['extent'][0]<=x<=g['extent'][1])
            self.assertIsNone(g['column_full_height']);self.assertIsNone(g['flange_calculation_width'])

    def test_all_dimensions_use_true_uniform_scale(self):
        for r in self.cases.values():
            c=figure(r)
            for d in c.dimension_records:self.assertAlmostEqual(d['pixels'],d['value_mm']*d['scale'])
            self.assertEqual([d['value_mm'] for d in c.dimension_records if d['direction']=='z'],[r['input']['slab']['h_mm'],r['input']['main']['h_mm']])

    def test_no_result_or_cad_mutation(self):
        r=self.cases['sample1'];before=copy.deepcopy(r);cad=copy.deepcopy(make_scene(r).groups)
        figure(r);self.assertEqual(r,before);self.assertEqual(make_scene(r).groups,cad)

    def test_parameter_linkage_and_closed_chains(self):
        p=copy.deepcopy(self.cases['changed']['input']);p['loads']['live_kN_m2']=2
        p['main'].update(b_mm=280,h_mm=700);p['slab']['h_mm']=100
        p['geometry'].update(main_axis_spans_mm=[6300]*3,secondary_axis_spans_mm=[6300]*5,secondary_spacing_mm=2100,column_width_mm=340,wall_axis_to_inner_face_mm=150,main_bearing_mm=380)
        r=calculate(p);c=figure(r);g=c.geometry
        self.assertEqual((g['web_w'],g['h'],g['slab_h'],g['column_w'],g['bearing_mm']),(280,700,100,340,380))
        self.assertEqual(g['intersections_mm'],[2100,4200,8400,10500,14700,16800])
        self.assertEqual(g['chains'][0]['clear_mm'],6300-150-170)
        self.assertEqual(g['extent'][0],-230)

    def test_wall_hatching_clear_of_main_beam(self):
        c=figure(self.cases['sample1'])
        for wall in c.wall_regions:
            l,b,r,t=wall['beam']
            for a,z in wall['hatches']:
                for f in (.001,.25,.5,.75,.999):
                    x=a[0]+f*(z[0]-a[0]);y=a[1]+f*(z[1]-a[1])
                    self.assertFalse(l+1e-6<x<r-1e-6 and b+1e-6<y<t-1e-6)

    def test_inconsistent_dimension_record_fails(self):
        r=copy.deepcopy(self.cases['sample1']);r['dimension_geometry']['main']['chains'][0]['clear_mm']+=1
        with self.assertRaisesRegex(ValueError,'尺寸链不闭合'):figure(r)

    def test_annotation_bounds(self):
        for r in self.cases.values():
            c=figure(r)
            for a,b,x,y in c.text_boxes:
                self.assertGreaterEqual(min(a,b),0);self.assertLessEqual(x,c.w);self.assertLessEqual(y,c.h)


if __name__=='__main__':unittest.main()
