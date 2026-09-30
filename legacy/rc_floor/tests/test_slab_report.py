import unittest,json,copy,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from slab_report_geometry import layout
from slab_report_figures import overview,details,generate
from cad_scene import make_scene


class SlabReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=calculate(json.loads((ROOT/'sample1.json').read_text(encoding='utf-8')))

    def test_five_spans_and_mirrored_ends(self):
        g=layout(self.r);self.assertEqual(len(g['axis_mm']),6)
        bottoms=[b for b in g['bars'] if b['role']=='bottom']
        self.assertEqual([b['mark'] for b in bottoms],['B1','B3','B3','B3','B1'])
        self.assertEqual([b['mark'] for b in g['bars'] if b['role']=='top'],['B2','B4','B4','B2'])
        self.assertEqual(bottoms[-1]['path'],[[g['total_mm']-x,y] for x,y in reversed(bottoms[0]['path'])])
        for mark in ('B6','B7'):
            bars=[b for b in g['bars'] if b['mark']==mark]
            self.assertEqual(bars[1]['path'],[[g['total_mm']-x,y] for x,y in bars[0]['path']])

    def test_bar_placement_closes_against_schedule(self):
        for case in ('sample1','changed'):
            r=calculate(json.loads((ROOT/(case+'.json')).read_text(encoding='utf-8')))
            g=layout(r)
            for b in g['bars']:
                length=sum(abs(a[0]-z[0])+abs(a[1]-z[1]) for a,z in zip(b['path'],b['path'][1:]))
                self.assertAlmostEqual(length+b.get('allowance_mm',0),b['length_mm'])
                if b['role']=='bottom':
                    self.assertLess(b['path'][0][0],b['faces'][0]);self.assertGreater(b['path'][-1][0],b['faces'][-1])
                if b['role']=='top':
                    self.assertAlmostEqual(b['path'][2][0]-b['path'][1][0],sum(b['extensions'])+g['support_width_mm'])

    def test_renderers_do_not_mutate_result_or_cad(self):
        before=copy.deepcopy(self.r);cad=make_scene(self.r).items
        with tempfile.TemporaryDirectory() as tmp:generate(self.r,tmp)
        self.assertEqual(before,self.r);self.assertEqual(cad,make_scene(self.r).items)

    def test_bad_geometry_fails_with_reason(self):
        for mark,part in [('B1','净跨'),('B2','支座宽'),('B6','墙内直段')]:
            r=copy.deepcopy(self.r);bar=next(b for b in r['bars'] if b['mark']==mark)
            bar['segments']=[(label,v+10 if label==part else v) for label,v in bar['segments']]
            bar['length_mm']+=10
            with self.assertRaisesRegex(ValueError,'板配筋插图数据不一致'):layout(r)

    def test_wall_hatching_does_not_cross_slab(self):
        im=overview(self.r)
        self.assertEqual(len(im.wall_regions),2)
        for wall in im.wall_regions:
            l,b,r,t=wall['beam']
            for a,z in wall['hatches']:
                for f in (.01,.25,.5,.75,.99):
                    x=a[0]+f*(z[0]-a[0]);y=a[1]+f*(z[1]-a[1])
                    self.assertFalse(l+1e-6<x<r-1e-6 and b+1e-6<y<t-1e-6)
        self.assertIsNone(im.geometry['wall_thickness_mm'])

    def test_labels_fit_both_cases(self):
        for case in ('sample1','changed'):
            r=calculate(json.loads((ROOT/(case+'.json')).read_text(encoding='utf-8')))
            for im in (overview(r),details(r)):
                for box in im.text_boxes:
                    self.assertGreaterEqual(box[0],0);self.assertGreaterEqual(box[1],0)
                    self.assertLessEqual(box[2],im.w);self.assertLessEqual(box[3],im.h)

    def test_dimensions_link_to_changed_input(self):
        # Low live load isolates drawing linkage from beam selection failure.
        p=copy.deepcopy(self.r['input']);p['loads']['live_kN_m2']=2
        p['slab']['h_mm']=100;p['slab']['cover_mm']=20
        p['secondary']['b_mm']=220;p['geometry']['slab_bearing_mm']=150
        p['geometry']['secondary_spacing_mm']=2100
        p['geometry']['main_axis_spans_mm']=[6300]*3
        p['geometry']['secondary_axis_spans_mm']=[6500]*5
        r=calculate(p);g=layout(r)
        self.assertEqual(g['axis_mm'],[0,2100,4200,6300,8400,10500])
        self.assertEqual((g['h_mm'],g['cover_mm'],g['support_width_mm'],g['bearing_mm']),(100,20,220,150))
        for b in g['bars']:
            if b['role']=='bottom':self.assertEqual(b['path'][0][1],20+b['diameter']/2)
        with tempfile.TemporaryDirectory() as tmp:generate(r,tmp)


if __name__=='__main__':unittest.main()
