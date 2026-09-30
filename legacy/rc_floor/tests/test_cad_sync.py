import copy,json,math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from cad_scene import make_scene
from cad_sync import secondary_scene,slab_scenes,main_dimensions,slab_dimensions,coefficients,offsets
from secondary_report import layout as secondary_layout
from slab_report_geometry import layout as slab_layout
from main_dimension_report import layout as main_layout
from report_support_detail import geometry
from scene_base import bounds

class CadSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.results=[calculate(json.loads((ROOT/(n+'.json')).read_text('utf8'))) for n in ('sample1','changed')]

    def test_shared_result_is_not_modified(self):
        for r in self.results:
            before=copy.deepcopy(r);make_scene(r);self.assertEqual(before,r)

    def test_secondary_primary_paths_exact(self):
        for r in self.results:
            items=secondary_scene(r).items
            for b in secondary_layout(r)['bars']:
                self.assertIn(['POLY','ERECT' if b['role']=='J' else 'REBAR',False,[list(p) for p in b['path_mm']]],items)

    def test_slab_primary_paths_exact(self):
        for r in self.results:
            items=slab_scenes(r).items
            for b in slab_layout(r)['bars']:
                if b['role']!='corner':self.assertIn(['POLY','REBAR',False,[list(p) for p in b['path']]],items)

    def test_full_t_dimensions_real_values(self):
        for r in self.results:
            for scene,g,keys in [(slab_dimensions(r),geometry(r),('support_width_mm','beam_total_height_mm','slab_thickness_mm')),(main_dimensions(r),main_layout(r),('web_w','h','slab_h'))]:
                values=[]
                for o in scene.items:
                    if o[0]=='DIM':
                        a=math.radians(o[5]);values.append(abs((o[3][0]-o[2][0])*math.cos(a)+(o[3][1]-o[2][1])*math.sin(a))*o[6])
                for k in keys:self.assertTrue(any(abs(g[k]-v)<1e-6 for v in values),(k,g[k]))

    def test_hidden_and_center_are_distinct(self):
        for r in self.results:
            layers={o[1] for o in main_dimensions(r).items};self.assertTrue({'HIDDEN','CENTER','CONC'}<=layers)

    def test_group_extents_do_not_overlap(self):
        for r in self.results:
            s=make_scene(r);off=offsets(s.groups);boxes={}
            for k,v in s.groups.items():
                x,y=off[k];a,b,c,d=bounds(v);boxes[k]=(a+x,b+y,c+x,d+y)
            for i,(k,a) in enumerate(boxes.items()):
                for q,b in list(boxes.items())[i+1:]:self.assertFalse(a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3],(k,q))

    def test_coefficients_and_interpolated_control_values(self):
        for r in self.results:
            scene=coefficients(r,'slab');curves=[o for o in scene.items if o[0]=='POLY' and o[1]=='ENV']
            self.assertEqual(len(curves),5)
            for a,b in zip(curves,curves[1:]):self.assertEqual(a[3][-1],b[3][0])
            text=[o[5] for o in scene.items if o[0]=='TEXT']
            for s in ('1/11','-1/11','1/16','-1/14'):self.assertIn(s,text)

if __name__=='__main__':unittest.main()
