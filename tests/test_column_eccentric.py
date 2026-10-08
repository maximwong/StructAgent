"""Independent pre-implementation references and adversarial eccentric boundaries."""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from core import ToolValidationError
from examples.column_eccentric import run_request
from tests.test_column_combinations import combination_parameters
from tests.test_column_tools import envelope
from tools.column.eccentric_calculation import check_column_eccentric, design_column_eccentric, validate_design_semantics
from tools.column.eccentric_input import validate_parameters
from tools.column.eccentric_store import ColumnEccentricStore, ColumnEccentricReferenceError
from tools.column.eccentric_tools import ColumnEccentricDesignTool, ColumnEccentricCheckTool
from tools.column.json_data import canonical_hash

ROOT=Path(__file__).resolve().parents[1]
REF=json.loads((ROOT/'tests/fixtures/column_eccentric_references.json').read_text(encoding='utf-8'))


def parameters(n=500,m=125):
    p=combination_parameters(forces=[n])
    model=p['model']
    model['section'].update(b_mm=300,h_mm=400,cover_to_outer_tie_mm=35)
    model['effective_length']={'lc_mm':3000,'source':'Anonymous final section analysis',
        'analysis_id':'TEACHING-ANALYSIS-1','covers_bending_plane':True}
    model['ties']={'diameter_mm':8,'spacing_mm':150,'hook_angle_deg':135,'hook_extension_mm':80}
    model['bending_axis']='x'
    model['scope'].pop('ideal_axial_compression')
    model['scope']['uniaxial_eccentric_compression']=True
    group=p['combinations'][0]
    group['actions'].update(Mx_kN_m=m,M_includes_gamma0=True)
    group['second_order']={'analysis_id':'TEACHING-ANALYSIS-1','combination_id':'ULS-1',
        'frame_P_Delta_included':True,'member_P_delta_included':True,
        'additional_eccentricity_included':False,'source':'Anonymous externally analysed final vector, ea excluded'}
    return p


def actual(d=20):
    return {'bar_count':4,'bar_diameter_mm':d,'layout':'four_corner_bars','perimeter_closed':True,
            'crosstie_axes':[],'crossties_at_every_layer':False,'ends_engage_bars':False}


class EccentricCalculationTests(unittest.TestCase):
    def test_independent_large_and_small_references_and_previous_candidate(self):
        for name in ('large','small'):
            reference=REF[name]
            p=parameters(reference['N_kN'],reference['M_kN_m']);before=deepcopy(p)
            report=check_column_eccentric(p,actual())
            self.assertEqual(report['status'],'PASS')
            info=report['combination_results'][0]['intermediates']
            for key in ('x_mm','sigma_s_MPa','capacity_kN_m'):
                self.assertAlmostEqual(info[key],reference[key],delta=1e-7)
            self.assertEqual(info['eccentricity_class'],name)
            prev=check_column_eccentric(p,actual(18))
            self.assertEqual(prev['status'],'FAIL')
            self.assertAlmostEqual(prev['combination_results'][0]['intermediates']['input_moment_limit_kN_m'],reference['previous_input_moment_limit_kN_m'],delta=1e-7)
            designed=design_column_eccentric(p)
            self.assertEqual(designed['selected']['actual'],actual())
            self.assertEqual([r['actual']['bar_diameter_mm'] for r in designed['attempts']],[12,14,16,18,20])
            self.assertEqual(p,before)

    def test_balanced_exact_equality_and_neighbour_classes(self):
        p=parameters(755.04,131.706);p['model']['section']['h_mm']=393
        r=check_column_eccentric(p,actual())
        i=r['combination_results'][0]['intermediates']
        self.assertEqual(r['status'],'PASS');self.assertEqual(i['eccentricity_class'],'large')
        self.assertEqual(i['x_mm'],176);self.assertEqual(i['capacity_kN_m'],146.8068)
        p['combinations'][0]['actions']['Mx_kN_m']=131.706000001
        self.assertEqual(check_column_eccentric(p,actual())['status'],'FAIL')
        for n,branch in ((755.0399,'large'),(755.0401,'small')):
            p['combinations'][0]['actions'].update(N_kN=n,Mx_kN_m=130)
            self.assertEqual(check_column_eccentric(p,actual())['combination_results'][0]['intermediates']['eccentricity_class'],branch)

    def test_negative_mirror_and_rotated_axis(self):
        a=check_column_eccentric(parameters(),actual())['combination_results'][0]['intermediates']
        b=check_column_eccentric(parameters(m=-125),actual())['combination_results'][0]['intermediates']
        self.assertNotEqual(a['compression_face'],b['compression_face'])
        self.assertEqual(a['capacity_interval_exact'],b['capacity_interval_exact'])
        p=parameters();p['model']['section'].update(b_mm=400,h_mm=300);p['model']['bending_axis']='y'
        p['combinations'][0]['actions'].update(Mx_kN_m=0,My_kN_m=125)
        c=check_column_eccentric(p,actual())['combination_results'][0]['intermediates']
        self.assertEqual(a,c)

    def test_small_root_interval_and_conservative_capacity_are_exact(self):
        i=check_column_eccentric(parameters(1200,100),actual())['combination_results'][0]['intermediates']
        lo,hi=map(Fraction,i['x_interval_exact'])
        equilibrium=lambda x: Fraction('14.3')*300*x+360*628-660*(Fraction('.8')*347/x-1)*628-1200000
        self.assertLessEqual(equilibrium(lo),0);self.assertGreaterEqual(equilibrium(hi),0)
        lower,upper=map(Fraction,i['capacity_interval_exact'])
        self.assertLessEqual(lower,upper)
        self.assertLessEqual(Fraction(i['capacity_interval_N_mm'][0]),lower)
        self.assertGreaterEqual(Fraction(i['capacity_interval_N_mm'][1]),upper)
        self.assertLessEqual(Fraction(i['demand_N_mm_exact']),lower)

    def test_small_exact_capacity_unresolved_interval_cannot_authorize_pass(self):
        # Independently choose x=200mm: sigma=256.08, N=923.26176,
        # MR=142.67404128, input-M limit=124.20880608. The exact
        # rational root is not a finite node in the 106..320 bisection.
        for m,status in ((124.20880608,'INDETERMINATE'),(124.20880607,'PASS'),(124.20880609,'FAIL')):
            self.assertEqual(check_column_eccentric(parameters(923.26176,m),actual())['status'],status)

    def test_control_not_maximum_axial_and_exact_ties(self):
        p=parameters(1200,50)
        group=deepcopy(parameters(500,125)['combinations'][0])
        for k in ('combination_id',): group[k]='ULS-2'
        group['source'].update(combination_id='ULS-2',force_record_id='ROW-2')
        group['second_order']['combination_id']='ULS-2';p['combinations'].append(group)
        r=check_column_eccentric(p,actual());self.assertEqual(r['controlling_combinations'],['ULS-2'])
        twin=deepcopy(group);twin['combination_id']='ULS-3';twin['source'].update(combination_id='ULS-3',force_record_id='ROW-3');twin['second_order']['combination_id']='ULS-3'
        p['combinations'].append(twin)
        self.assertEqual(check_column_eccentric(p,actual())['controlling_combinations'],['ULS-2','ULS-3'])

    def test_scope_limits_not_reported_as_proven_capacity_failure(self):
        for n in (100,1700,2000):
            r=check_column_eccentric(parameters(n,10),actual())
            self.assertEqual(r['status'],'OUTSIDE_SCOPE')
            self.assertNotIn('capacity_kN_m',r['combination_results'][0]['intermediates'])

    def test_failed_detailing_and_no_automatic_model_change(self):
        for path,value in ((('ties','hook_angle_deg'),180),(('ties','hook_extension_mm'),79),(('ties','spacing_mm'),301),(('ties','diameter_mm'),4)):
            p=parameters();p['model'][path[0]][path[1]]=value
            r=check_column_eccentric(p,actual());self.assertEqual(r['status'],'FAIL')
        a=actual();a['perimeter_closed']=False
        self.assertEqual(check_column_eccentric(parameters(),a)['status'],'FAIL')
        p=parameters(m=1000);before=deepcopy(p);r=design_column_eccentric(p)
        self.assertEqual(r['status'],'FAIL');self.assertIsNone(r['selected']);self.assertEqual(len(r['attempts']),8)
        self.assertEqual(p,before)

    def test_material_conflicts_bool_nan_and_extra_fields(self):
        cases=[('model','section','b_mm',True),('model','ties','diameter_mm',False),
               ('model','materials','fc_MPa',14.4),('model','materials','fy_tension_MPa',400),
               ('model','materials','Es_MPa',200001),('model','effective_length','lc_mm',float('inf'))]
        for first,second,key,value in cases:
            p=parameters();p[first][second][key]=value
            with self.assertRaises(ToolValidationError):validate_parameters(p)
        for key,value in (('N_kN',True),('Mx_kN_m',float('nan')),('My_kN_m',1),('Vx_kN',1),('Mx_kN_m',0),('M_includes_gamma0',False)):
            p=parameters();p['combinations'][0]['actions'][key]=value
            with self.assertRaises(ToolValidationError):validate_parameters(p)
        p=parameters();del p['combinations'][0]['actions']['M_includes_gamma0']
        with self.assertRaises(ToolValidationError):validate_parameters(p)
        p=parameters();p['model']['unexpected']=1
        with self.assertRaises(ToolValidationError):validate_parameters(p)

    def test_source_second_order_mismatch_and_missing_declarations(self):
        for key,value in (('analysis_id','OTHER'),('combination_id','OTHER'),('frame_P_Delta_included',False),('member_P_delta_included',False),('additional_eccentricity_included',True),('source',' ')):
            p=parameters();p['combinations'][0]['second_order'][key]=value
            with self.assertRaises(ToolValidationError):validate_parameters(p)
        p=parameters();group=deepcopy(p['combinations'][0]);p['combinations'].append(group)
        with self.assertRaises(ToolValidationError):validate_parameters(p)


class EccentricToolTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=ColumnEccentricStore(Path(self.temp.name)/'偏压柱')
        self.design=ColumnEccentricDesignTool(self.store);self.check=ColumnEccentricCheckTool(self.store)

    def test_reference_actual_and_cross_project(self):
        result=self.design.execute(envelope('design_column_eccentric',parameters()))
        self.assertTrue(result.success,result.errors)
        ref=result.result['design_result_ref']
        with patch('tools.column.eccentric_calculation.design_column_eccentric',side_effect=AssertionError('reference check cannot design')):
            checked=self.check.execute(envelope('check_column_eccentric',{'design_result_ref':ref}))
        self.assertTrue(checked.success,checked.errors);self.assertEqual(checked.result['actual'],actual())
        self.assertFalse(self.check.execute(envelope('check_column_eccentric',{'design_result_ref':ref},'OTHER')).success)
        with patch('tools.column.eccentric_calculation.design_column_eccentric',side_effect=AssertionError('no reselection')):
            weak=self.check.execute(envelope('check_column_eccentric',{**parameters(),'actual':actual(18)}))
        self.assertFalse(weak.success);self.assertEqual(weak.result['status'],'FAIL')

    def test_rehashed_forgery_and_truncated_candidate_prefix_rejected(self):
        result=self.design.execute(envelope('design_column_eccentric',parameters()))
        ref=result.result['design_result_ref'];path=self.store.root/(ref+'.json')
        payload=json.loads(path.read_text(encoding='utf-8'))
        payload['design']['result']['attempts']=payload['design']['result']['attempts'][-1:]
        report={k:v for k,v in payload['design']['result'].items() if k!='design_result_ref'}
        payload['design']['metadata']['column_eccentric_sha256']=canonical_hash(report)
        payload['checksum']=canonical_hash({k:v for k,v in payload.items() if k!='checksum'})
        path.write_text(json.dumps(payload),encoding='utf-8')
        with self.assertRaises(ColumnEccentricReferenceError):self.store.load(ref,project_id='COLUMN-TEST')

    def test_failed_reports_preserved_and_not_saved(self):
        r=self.design.execute(envelope('design_column_eccentric',parameters(m=1000)))
        self.assertFalse(r.success);self.assertEqual(len(r.result['attempts']),8)
        self.assertFalse(self.store.root.exists())
        p=parameters(1700,10)
        r=self.check.execute(envelope('check_column_eccentric',{**p,'actual':actual()}))
        self.assertFalse(r.success);self.assertEqual(r.result['status'],'OUTSIDE_SCOPE')

    def test_original_controller_workflow_and_stop_on_fail(self):
        for m,success in ((125,True),(1000,False)):
            r=run_request(envelope('design_column_eccentric',parameters(m=m)),Path(self.temp.name)/str(m))
            self.assertEqual(r['success'],success,r['errors'])
            self.assertEqual([x['tool'] for x in r['tool_calls']],['design_column_eccentric','check_column_eccentric'] if success else ['design_column_eccentric'])

    def test_cli_request_and_invalid_json(self):
        path=Path(self.temp.name)/'request.json'
        path.write_text(json.dumps(envelope('design_column_eccentric',parameters())),encoding='utf-8')
        cmd=[sys.executable,'-m','examples.column_eccentric','--request-file',str(path),'--output-root',self.temp.name]
        r=subprocess.run(cmd,cwd=ROOT,capture_output=True)
        self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['success'])
        path.write_text('{"tool":"x","tool":"y"}',encoding='utf-8')
        r=subprocess.run(cmd,cwd=ROOT,capture_output=True)
        self.assertEqual(r.returncode,1);self.assertEqual(json.loads(r.stdout)['status'],'invalid_input')
