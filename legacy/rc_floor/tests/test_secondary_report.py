import copy,json,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from secondary_report import layout,figure
from cad_scene import make_scene


class SecondaryReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases={n:calculate(json.loads((ROOT/(n+'.json')).read_text(encoding='utf-8'))) for n in ('sample1','changed')}

    def test_stored_paths_and_control_rows(self):
        for r in self.cases.values():
            g=layout(r)
            self.assertEqual(g['bars'],r['drawing_geometry']['secondary']['bars'])
            self.assertEqual(len(g['controls']),9)
            for row in g['controls']:
                self.assertGreaterEqual(row['provided'],row['required'])
            self.assertEqual([x['mark'] for x in g['controls'] if x['role']=='F'],['CL-F1','CL-F2','CL-F3','CL-F4'])

    def test_no_calculation_or_cad_mutation(self):
        r=self.cases['sample1'];before=copy.deepcopy(r);cad=copy.deepcopy(make_scene(r).groups)
        figure(r)
        self.assertEqual(r,before);self.assertEqual(cad,make_scene(r).groups)

    def test_invalid_schedule_and_area_fail(self):
        r=copy.deepcopy(self.cases['sample1']);r['secondary'][0]['As_provided']=1
        with self.assertRaisesRegex(ValueError,'采用面积'):layout(r)
        r=copy.deepcopy(self.cases['sample1']);r['drawing_geometry']['secondary']['bars'][0]['path_mm'][0][0]-=30
        with self.assertRaisesRegex(ValueError,'路径长度'):layout(r)

    def test_wall_hatch_excludes_beam_and_representative_stations(self):
        c=figure(self.cases['sample1'])
        self.assertLess(len(c.representative_stations),len(c.geometry['stirrup_stations_mm']))
        self.assertTrue(set(c.representative_stations)<=set(c.geometry['stirrup_stations_mm']))
        self.assertIsNone(c.geometry['wall_thickness'])
        for region in c.wall_regions:
            l,b,r,t=region['beam']
            for a,z in region['hatches']:
                for f in (.001,.25,.5,.75,.999):
                    x=a[0]+(z[0]-a[0])*f;y=a[1]+(z[1]-a[1])*f
                    self.assertFalse(l+1e-6<x<r-1e-6 and b+1e-6<y<t-1e-6)

    def test_parameter_linkage(self):
        p=copy.deepcopy(self.cases['changed']['input']);p['loads']['live_kN_m2']=2
        p['secondary']['h_mm']=500;p['main']['b_mm']=300;p['main']['h_mm']=700
        p['geometry']['secondary_axis_spans_mm']=[6200]*5
        r=calculate(p);c=figure(r)
        self.assertEqual((c.geometry['h'],c.geometry['main_h'],c.geometry['support'],c.geometry['total']),(500,700,300,31000))
        self.assertEqual(c.geometry['controls'][0]['provided'],r['secondary'][0]['As_provided'])

    def test_label_bounds(self):
        for r in self.cases.values():
            c=figure(r)
            for a,b,x,y in c.text_boxes:
                self.assertGreaterEqual(min(a,b),0);self.assertLessEqual(x,c.w);self.assertLessEqual(y,c.h)


if __name__=='__main__':unittest.main()
