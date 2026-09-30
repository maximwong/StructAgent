import json,math,re,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from engine import calculate
from cad_scene import make_scene,export_drawing
from workflow import generate,retry_cad


class UnifiedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.r=calculate(json.loads((ROOT/'sample1.json').read_text(encoding='utf-8')))
        cls.changed=calculate(json.loads((ROOT/'changed.json').read_text(encoding='utf-8')))

    def test_actual_paths_equal_schedule_lengths(self):
        for r in [self.r,self.changed]:
            for b in r['bars']:
                if 'physical_path_mm' not in b:continue
                pts=b['physical_path_mm'];L=sum(math.dist(a,z) for a,z in zip(pts,pts[1:]))
                self.assertAlmostEqual(L,b['length_mm'],places=6,msg=b['mark'])

    def test_lap_interval_matches_report(self):
        for r in [self.r,self.changed]:
            event=next(e for e in r['joint_checks'] if e.get('member')=='main' and 'overlap_mm' in e)
            z=r['drawing_geometry']['main']['lap_zones'][0]
            self.assertAlmostEqual(z['end']-z['start'],event['overlap_mm'])
            stations=[x for x in r['drawing_geometry']['main']['stirrup_stations_mm'] if z['start']-1e-5<=x<=z['end']+1e-5]
            self.assertLessEqual(max(b-a for a,b in zip(stations,stations[1:])),z['spacing']+1e-5)

    def test_cad_adopted_top_bars_and_unique_schedule(self):
        for r in [self.r,self.changed]:
            scene=make_scene(r);texts=[o[5] for o in scene.groups['TABLE'] if o[0]=='TEXT']
            for b in r['bars']:
                headers=[t for t in texts if t.startswith(b['mark']+' ')]
                self.assertEqual(len(headers),1)
                self.assertIn(str(b['count'])+'Φ'+str(b['diameter']),headers[0])
            details=[o[5] for o in scene.groups['DETAIL'] if o[0]=='TEXT']
            event=next(e for e in r['joint_checks'] if 'physical_count' in e)
            self.assertIn(str(event['physical_count'])+'Φ'+str(event['diameter']),details)

    def test_lisp_balance_and_bigfont_fix(self):
        src=(ROOT/'RCFLOOR.lsp').read_text(encoding='ascii');stack=[];quoted=False;escape=False
        for n,line in enumerate(src.splitlines(),1):
            for c in line:
                if quoted:
                    if escape:escape=False
                    elif c=='\\':escape=True
                    elif c=='"':quoted=False
                elif c==';':break
                elif c=='"':quoted=True
                elif c=='(':stack.append(n)
                elif c==')':self.assertTrue(stack,'Unexpected close '+str(n));stack.pop()
        self.assertFalse(stack);self.assertFalse(quoted)
        self.assertNotIn('(vla-put-BigFontFile',src)

    def test_shared_offsets_unicode_and_dimensions(self):
        with tempfile.TemporaryDirectory() as tmp:
            data=export_drawing(self.r,tmp);raw=(Path(tmp)/'floor_data.dat').read_text(encoding='ascii')
            self.assertIn('"OFFSETS"',raw);self.assertIn('\\\\U+',raw)
            from scene_base import bounds
            self.assertEqual(data['offsets']['TABLE'][1],-3000)
            self.assertGreater(data['offsets']['TABLE'][0],max(bounds(data['groups'][k])[2] for k in ['PLAN','BEAMS','DETAIL']))
            for items in data['groups'].values():
                for o in items:
                    if o[0]=='TEXT':self.assertNotIn('\ufffd',o[5]);self.assertLessEqual(len(o[5]),255)
                    if o[0]=='DIM':self.assertNotEqual(o[2],o[3]);self.assertIn(o[5],[0,90])

    def test_parameters_change_geometry_and_annotation(self):
        a=make_scene(self.r).groups;b=make_scene(self.changed).groups
        for key in ['BEAMS','DETAIL','ENVELOPE','TABLE']:self.assertNotEqual(a[key],b[key])

    def test_partial_output_is_not_success_and_retry_preserves_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('workflow.draw_figures',return_value={}),patch('report.build_docx'),patch('report.convert',return_value='test'),patch('workflow.export_cad',side_effect=RuntimeError('CAD unavailable')):
                out=generate(ROOT/'sample1.json',Path(tmp)/'out')
            state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'));self.assertEqual(state['state'],'PARTIAL');self.assertEqual(state['outputs']['word']['state'],'SUCCESS')
            before=(out/'results.json').read_bytes()
            with patch('workflow.calculate',side_effect=AssertionError('must not recalculate')),patch('workflow.export_cad',return_value={'state':'SUCCESS'}):retry_cad(out)
            self.assertEqual((out/'results.json').read_bytes(),before)
            self.assertEqual(json.loads((out/'STATUS.json').read_text(encoding='utf-8'))['state'],'SUCCESS')
            (out/'cad/drawing_scene.json').write_text('{}',encoding='utf-8')
            with self.assertRaises(ValueError):retry_cad(out)

    def test_word_failure_still_attempts_cad(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('workflow.draw_figures',side_effect=RuntimeError('font missing')),patch('workflow.export_cad',return_value={'state':'SUCCESS'}) as cad:
                out=generate(ROOT/'sample1.json',Path(tmp)/'out')
            self.assertEqual(cad.call_count,1)
            state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'));self.assertEqual(state['state'],'PARTIAL');self.assertEqual(state['outputs']['pdf']['state'],'FAILED')

if __name__=='__main__':unittest.main()
