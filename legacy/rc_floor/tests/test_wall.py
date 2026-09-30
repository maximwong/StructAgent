import copy,json,math,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from dimension_scene import dimension_scene,wall_profile


def inside(p,poly):
    # Independent ray-casting oracle, with boundary tolerance.
    x,y=p;hit=False
    for a,b in zip(poly,poly[1:]+poly[:1]):
        cross=(x-a[0])*(b[1]-a[1])-(y-a[1])*(b[0]-a[0])
        if abs(cross)<1e-5 and min(a[0],b[0])-1e-7<=x<=max(a[0],b[0])+1e-7 and min(a[1],b[1])-1e-7<=y<=max(a[1],b[1])+1e-7:return True
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:hit=not hit
    return hit


class WallTests(unittest.TestCase):
    def check_region(self,region):
        self.assertTrue(region['hatches'])
        x1,y1,x2,y2=region['beam']
        for a,b in region['hatches']:
            self.assertAlmostEqual(abs(a[0]-b[0]),abs(a[1]-b[1]),places=6)
            for i in range(21):
                p=[a[j]+(b[j]-a[j])*i/20 for j in (0,1)]
                self.assertTrue(inside(p,region['polygon']),p)
                self.assertFalse(x1+1e-7<p[0]<x2-1e-7 and y1+1e-7<p[1]<y2-1e-7,p)

    def test_hatch_clipped_to_broken_wall_and_outside_beam(self):
        for config in ['sample1','changed']:
            r=calculate(json.loads((ROOT/(config+'.json')).read_text(encoding='utf-8')))
            before=copy.deepcopy(r)
            for member in ['slab','secondary','main']:
                sc=dimension_scene(r,member)
                self.assertEqual(len(sc.wall_regions),4) # overall L/R plus local L/R
                for region in sc.wall_regions:self.check_region(region)
                texts=[o[5] for o in sc.items if o[0]=='TEXT']
                self.assertTrue(any('支承墙体（外侧截断，墙厚未给定）' in t for t in texts))
                self.assertTrue(any('左端支承' in t for t in texts))
                self.assertTrue(any('右端支承' in t for t in texts))
            self.assertEqual(r,before) # drawing never mutates calculation or rebar data

    def test_clipping_both_sides_and_narrow_walls(self):
        for width in [17,120,360,730]:
            for sign in [-1,1]:
                beam=sorted([sign*width*.75,sign*-width])
                self.check_region(wall_profile(0,sign*width,-90,190,[beam[0],0,beam[1],47],13))

    def test_end_dimensions_follow_parameters_on_both_sides(self):
        p=json.loads((ROOT/'sample1.json').read_text(encoding='utf-8'))
        p['geometry']['wall_axis_to_inner_face_mm']=130
        p['geometry']['main_bearing_mm']=380
        p['geometry']['secondary_bearing_mm']=260
        r=calculate(p)
        for member in ['slab','secondary','main']:
            d=r['dimension_geometry'][member];sc=dimension_scene(r,member)
            # Local bearing dimensions are inserted before the 3 internal support DIMs.
            dims=[o for o in sc.items if o[0]=='DIM'][-7:-3]
            values=[abs(o[2][0]-o[3][0])*o[6] for o in dims]
            for value,expected in zip(values,[130,d['bearing_mm'],130,d['bearing_mm']]):self.assertAlmostEqual(value,expected,6)
            self.assertIsNone(d['wall_thickness_mm'])
            for region in sc.wall_regions:self.check_region(region)


if __name__=='__main__':unittest.main()
