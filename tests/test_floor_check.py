"""Real legacy resistance checks; cloud/CAD only simulated for workflow faults."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.state import AgentState
from core import ToolRegistry, ToolResult
from tests.semantic_fixtures import floor_proposal
from tests.test_agent_controller import SimulatedCAD, TEXT
from tools.floor.check_adapter import FloorCheckAdapter
from tools.floor.design_adapter import canonical_hash
from tools.floor.language_profile import FloorDemoProfile
from tools.floor.plugin import register_floor_workflow

ROOT=Path(__file__).resolve().parents[1]
CONTEXT={'unit_system':'SI','design_code':'GB'}


class FloorCheckTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry=ToolRegistry()
        self.workflow=register_floor_workflow(self.registry,self.root,cad_backend=SimulatedCAD())
        self.tool=self.registry.get('check_floor_design');self.store=self.tool.store
        self.design=self.design_case('demo_a')
        self.ref=self.design.metadata['design_result_ref']

    def design_case(self,name):
        model=json.loads((ROOT/'legacy/rc_floor'/f'{name}.json').read_text(encoding='utf-8-sig'))
        result=self.registry.get('design_floor_system').execute({'project_id':'qa','tool':'design_floor_system','context':CONTEXT,'parameters':{'input_mode':'explicit','model':model}})
        self.assertTrue(result.success,result.errors)
        return result

    def run_check(self,ref=None,project='qa'):
        return self.tool.execute({'project_id':project,'tool':self.tool.name,'context':CONTEXT,'parameters':{'design_result_ref':ref or self.ref}})

    def changed_snapshot(self,mutate):
        data=self.store.load(self.ref,project_id='qa').to_dict()
        raw=data['result']['legacy_result'];mutate(raw)
        data['result']['slab']['sections']=deepcopy(raw['slab'])
        for member,key in [('secondary','secondary_beam'),('main','main_beam')]:
            data['result'][key]['sections']=deepcopy(raw[member])
            data['result'][key]['shear_checks']=deepcopy(raw[member+'_shear'])
        data['metadata']['legacy_result_sha256']=canonical_hash(raw)
        return self.store.save(ToolResult(**data))

    def test_three_baselines_pass_without_mutating_design_or_selecting_new_bars(self):
        for name in ['demo_a','sample1','changed']:
            with self.subTest(case=name):
                design=self.design_case(name);ref=design.metadata['design_result_ref']
                path=self.store.root/(ref+'.json');before=path.read_bytes()
                result=self.run_check(ref)
                self.assertTrue(result.success,result.errors)
                self.assertEqual(result.result['status'],'PASS')
                self.assertEqual(result.result['summary']['failed'],0)
                self.assertGreater(result.result['summary']['total'],100)
                self.assertEqual(path.read_bytes(),before)
                self.assertEqual(self.run_check(ref).to_dict(),result.to_dict())
                self.assertTrue(result.result['coverage']['not_checked'])

    def test_under_reinforced_slab_fails_even_when_cached_capacity_is_unchanged(self):
        ref=self.changed_snapshot(lambda r:r['slab'][0].update(diameter=4))
        result=self.run_check(ref)
        self.assertFalse(result.success)
        self.assertEqual(result.result['status'],'FAIL')
        failed={c['id'] for c in result.result['checks'] if not c['passed']}
        self.assertIn('slab.0.flexure',failed)
        self.assertIn('slab.0.area_cache',failed)

    def test_json_integral_float_counts_keep_existing_schema_compatibility(self):
        ref=self.changed_snapshot(lambda r:r['main_shear'][0].update(legs=2.0))
        self.assertTrue(self.run_check(ref).success)

    def test_shear_ignores_claimed_capacity_and_rechecks_actual_spacing(self):
        ref=self.changed_snapshot(lambda r:r['main_shear'][0].update(spacing=1000,capacity_kN=1e9))
        result=self.run_check(ref)
        self.assertEqual(result.result['status'],'FAIL')
        self.assertTrue(any(not c['passed'] and c['id'].startswith('main.0.stirrup_') for c in result.result['checks']))

    def test_impossible_bar_layout_does_not_turn_skipped_shear_into_pass(self):
        ref=self.changed_snapshot(lambda r:r['main'][0].update(count=99))
        result=self.run_check(ref)
        self.assertEqual(result.result['status'],'FAIL')
        self.assertTrue(any(c['id']=='main.0.shear_geometry' and not c['passed'] for c in result.result['checks']))

    def test_false_stored_strength_and_height_are_detected(self):
        for changes in ({'Mu_kNm':1e9},{'h0':9999},{'bf':99999}):
            with self.subTest(changes=changes):
                ref=self.changed_snapshot(lambda r:r['main'][0].update(**changes))
                self.assertEqual(self.run_check(ref).result['status'],'FAIL')

    def test_missing_sections_and_boolean_numbers_cannot_pass(self):
        for mutate in [lambda r:r['slab'].pop(),lambda r:r['main'][0].update(count=True),lambda r:r['main'][0].pop('diameter')]:
            with self.subTest(mutate=mutate):
                result=self.run_check(self.changed_snapshot(mutate))
                self.assertFalse(result.success)
                self.assertEqual(result.errors[0]['code'],'check_input_invalid')

    def test_summary_rows_cannot_disagree_with_legacy_rows(self):
        data=self.store.load(self.ref,project_id='qa').to_dict()
        data['result']['slab']['sections'][0]['diameter']=4
        result=self.run_check(self.store.save(ToolResult(**data)))
        self.assertFalse(result.success)
        self.assertEqual(result.errors[0]['code'],'check_input_inconsistent')

    def test_project_path_and_checksum_boundaries_stop_before_worker(self):
        for ref,project in [(self.ref,'another-project'),('../bad','qa'),('floor-'+'0'*32,'qa')]:
            with patch.object(self.tool.adapter,'check') as call:
                self.assertFalse(self.run_check(ref,project).success);call.assert_not_called()
        path=self.store.root/(self.ref+'.json')
        payload=json.loads(path.read_text(encoding='utf-8'));payload['design']['result']['legacy_result']['slab'][0]['diameter']=4
        path.write_text(json.dumps(payload),encoding='utf-8')
        self.assertEqual(self.run_check().errors[0]['code'],'invalid_design_reference')

    def test_worker_timeout_and_invalid_protocol_fail_closed(self):
        with patch('tools.floor.check_adapter.subprocess.run',side_effect=subprocess.TimeoutExpired('check',.01)):
            self.assertEqual(self.run_check().errors[0]['code'],'check_timeout')
        for stdout in ['not JSON','[]','{"protocol":true,"success":true}', '{"protocol":1,"success":true,"result":{}}']:
            with patch('tools.floor.check_adapter.subprocess.run',return_value=SimpleNamespace(returncode=0,stdout=stdout)):
                self.assertEqual(self.run_check().errors[0]['code'],'check_protocol_error')
        for timeout in [True,0,-1,float('inf')]:
            with self.assertRaises(ValueError):FloorCheckAdapter(timeout)

    def test_checks_use_existing_pure_functions_without_calling_design_entries(self):
        code="""
import json,sys
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'legacy/rc_floor'));sys.path.insert(0,str(root/'tools/floor'))
import engine,legacy_core
def forbidden(*args,**kwargs):raise AssertionError('Design selection is forbidden during check')
engine.calculate=engine.legacy_run=legacy_core.run=legacy_core.beam_design=legacy_core.slab_design=forbidden
from _check_worker import check
result=check(json.load(sys.stdin));assert result['status']=='PASS'
"""
        before=set(sys.modules)
        result=subprocess.run([sys.executable,'-I','-c',code,str(ROOT)],input=json.dumps(self.design.result['legacy_result']),capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.run_check()
        self.assertFalse((set(sys.modules)-before)&{'engine','legacy_core','beam_solver'})

    def test_fail_gate_stops_cad_and_fresh_corrected_run_preserves_failure(self):
        gateway=Mock();gateway.complete.return_value=(floor_proposal(),{})
        controller=AgentController(self.registry,ParameterParser(self.registry,gateway,[FloorDemoProfile()]),AgentState(self.root/'agent'),[self.workflow])
        bad_ref=self.changed_snapshot(lambda r:r['slab'][0].update(diameter=4))
        bad=self.store.load(bad_ref,project_id='qa')
        bad_output={'result':bad.result,'metadata':bad.metadata,'warnings':bad.warnings}
        adapter=self.registry.get('design_floor_system')._adapter
        backend=self.registry.get('generate_floor_cad').adapter.backend
        with patch.object(adapter,'design',return_value=bad_output),patch.object(backend,'execute') as cad:
            failed=controller.run(TEXT,project_id='qa',profile_name='office_floor_demo_v1')
            self.assertFalse(failed['success']);self.assertEqual(failed['steps']['check'],'failed')
            self.assertEqual(failed['steps']['cad'],'skipped');self.assertFalse(failed['external_started']);cad.assert_not_called()
        path=Path(failed['tool_calls'][-1]['result_path']);before=hashlib.sha256(path.read_bytes()).hexdigest()
        corrected=controller.run(TEXT,project_id='qa',profile_name='office_floor_demo_v1')
        self.assertTrue(corrected['success'],corrected)
        self.assertNotEqual(corrected['run_id'],failed['run_id'])
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),before)
        self.assertEqual(controller.state.get(failed['run_id'])['steps']['cad'],'skipped')


if __name__=='__main__':unittest.main()
