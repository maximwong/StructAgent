import copy,json,math,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from detail_geometry import enrich_details,vertices
from scaled_figures import shapes
from cad_scene import make_scene
from scene_base import bounds
from figures import generate
from report import build_docx
from docx import Document


class ScaledTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p=json.loads((ROOT/'sample1.json').read_text(encoding='utf-8'));cls.r=calculate(cls.p)

    def test_dimension_chains_and_bearing_independence(self):
        for member,d in self.r['dimension_geometry'].items():
            for ch in d['chains']:self.assertAlmostEqual(ch['left_offset_mm']+ch['clear_mm']+ch['right_offset_mm'],ch['axis_mm'])
            self.assertIsNone(d['wall_thickness_mm'])
        self.assertEqual(self.r['dimension_geometry']['secondary']['chains'][0]['clear_mm'],5755)
        for key,value in [('secondary_axis_spans_mm',[6005]*5),('secondary_bearing_mm',260)]:
            p=copy.deepcopy(self.p);p['geometry'][key]=value;r=calculate(p)
            self.assertNotEqual(self.r['dimension_geometry']['secondary'],r['dimension_geometry']['secondary'])
        p=copy.deepcopy(self.p);p['main']['b_mm']=280;r=calculate(p)
        self.assertEqual(r['dimension_geometry']['secondary']['chains'][0]['clear_mm'],5740)
        self.assertEqual(r['dimension_geometry']['secondary']['bearing_mm'],240)

    def fixture(self):
        r=copy.deepcopy(self.r)
        r['bars']=[b for b in r['bars'] if b['member']!='slab']
        for i,L in enumerate([6000,4000,1000,6000,4000,501.25]):
            r['bars'].append(dict(mark=f'T{i+1}',member='slab',use='比例验收直筋',diameter=12,count=1,pieces=1,segments=[('直长',L)],length_mm=L,rounded_mm=math.ceil(L/10)*10,shape='straight',notes=''))
        return enrich_details(r)

    def test_6000_4000_same_and_cross_page_pixels_and_cad(self):
        r=self.fixture();lengths=[]
        for page in [0,1]:
            image=shapes(r,'slab',page).image
            for i in [0,1]:
                y=85+i*500+210
                black=[x for x in range(50,1600) if image.getpixel((x,y))==(0,0,0)]
                lengths.append(max(black)-min(black))
        self.assertEqual(lengths,[1200,800,1200,800])
        from scene_base import Scene
        from scaled_cad import bar_table
        sc=Scene();bar_table(sc,r);table=sc.groups['TABLE']
        lengths=[math.dist(o[3][0],o[3][-1]) for o in table if o[0]=='POLY' and o[1]=='REBAR' and len(o[3])==2]
        self.assertGreaterEqual(lengths.count(6000),2);self.assertGreaterEqual(lengths.count(4000),2)

    def test_developed_geometry_and_allowances(self):
        for cfg in ['sample1.json','changed.json']:
            r=calculate(json.loads((ROOT/cfg).read_text(encoding='utf-8')))
            for b in r['bars']:
                g=b['drawing'];length=sum(x['length_mm'] for x in g['components'])+sum(x['length_mm'] for x in g['allowances'])
                self.assertAlmostEqual(length,b['length_mm'],6,b['mark'])
                self.assertEqual(g['comparison_line'][1][0],b['length_mm'])
                if b['shape']=='hook':self.assertFalse(any(x['kind']=='arc' for x in g['components']));self.assertTrue(g['allowances'])
                for part in g['components']:
                    if part['kind']=='arc':
                        pts=vertices(part);self.assertLess(sum(math.dist(a,z) for a,z in zip(pts,pts[1:])),part['length_mm'])

    def test_last_sheet_width_and_word_extents(self):
        r=self.fixture()
        # A one-bar final sheet must not be enlarged by report auto-fitting.
        r['bars']=[b for b in r['bars'] if b['mark'] not in ['T5','T6']];enrich_details(r)
        with tempfile.TemporaryDirectory() as tmp:
            files=[]
            for pg in range(2):
                f=Path(tmp)/f'slab_shapes_{pg}.png';shapes(r,'slab',pg).save(f);files.append(f)
            figs={'slab_shapes':files};r['chapters']=[dict(title='比例验收',items=[dict(type='figure',key='slab_shapes',caption='固定比例')])]
            path=Path(tmp)/'test.docx';build_docx(r,figs,path);doc=Document(path)
            self.assertEqual(len(doc.inline_shapes),2)
            self.assertEqual([s.width for s in doc.inline_shapes],[170*36000]*2)
            self.assertLess(doc.inline_shapes[1].height,doc.inline_shapes[0].height)

    def test_scene_groups_have_no_overlapping_sheet_bounds(self):
        from cad_scene import export_drawing
        with tempfile.TemporaryDirectory() as tmp:
            data=export_drawing(self.r,tmp);boxes={}
            for key,items in data['groups'].items():
                x,y=data['offsets'][key];a,b,c,d=bounds(items);boxes[key]=(a+x,b+y,c+x,d+y)
            for key,a in boxes.items():
                for other,b in boxes.items():
                    if key>=other:continue
                    self.assertTrue(a[2]<=b[0] or b[2]<=a[0] or a[3]<=b[1] or b[3]<=a[1],(key,other,a,b))

    def test_report_scale_is_chosen_once_from_longest_bar(self):
        r=self.fixture();bar=next(b for b in r['bars'] if b['mark']=='T1');bar['length_mm']=11999.125;bar['segments']=[('直长',11999.125)];enrich_details(r)
        lay=r['bar_report_layout']['main']
        self.assertLessEqual(lay['max_width_mm']/lay['scale'],145)
        for m in ['slab','secondary','main']:
            for page in range(len(r['bar_report_layout'][m]['pages'])):
                im=shapes(r,m,page).image;self.assertEqual(im.width,1700);self.assertLessEqual(im.height,1800)

if __name__=='__main__':unittest.main()
