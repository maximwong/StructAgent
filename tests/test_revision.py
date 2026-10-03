"""Real bounded redesign and simulated faults/CAD; immutable attempt evidence."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent.controller import AgentController
from agent.revision import BoundedRevisionTool, RevisionSpec, object_schema
from agent.state import AgentState
from core.persistence import write_json
from core import EngineeringTool, ToolRegistry, ToolResult
from examples.floor_revision import ExplicitRevisionParser
from tests.test_agent_controller import SimulatedCAD
from tools.floor.design_adapter import FloorAdapterError
from tools.floor.plugin import register_floor_revision_workflow

ROOT=Path(__file__).resolve().parents[1]
CONTEXT=dict(unit_system='SI',design_code='GB')


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.registry=ToolRegistry()
        self.backend=SimulatedCAD()
        self.workflow=register_floor_revision_workflow(self.registry,self.root,cad_backend=self.backend)
        self.tool=self.registry.get('design_floor_with_revisions')
        self.model=json.loads((ROOT/'legacy/rc_floor/demo_a.json').read_text(encoding='utf-8-sig'))
        self.model['main']['b_mm']=100
        self.parameters=dict(initial_parameters=dict(input_mode='explicit',model=self.model),
            allowed_changes={'model.main.b_mm':[100,125,150,250]},max_attempts=4,time_budget_seconds=180)

    def execute(self, parameters=None):
        return self.tool.execute(dict(project_id='qa',tool=self.tool.name,context=CONTEXT,
            parameters=deepcopy(parameters or self.parameters)))

    def test_real_rejections_then_pass_keep_each_attempt_and_repeated_runs(self):
        before=deepcopy(self.parameters)
        result=self.execute();self.assertTrue(result.success,result.errors)
        self.assertEqual(result.result['attempt_count'],3)
        self.assertEqual(result.result['final_parameters']['model']['main']['b_mm'],150)
        self.assertEqual(self.parameters,before)
        attempts=result.result['attempts']
        self.assertFalse(attempts[0]['design']['success'])
        self.assertFalse(attempts[1]['design']['success'])
        self.assertTrue(attempts[2]['check']['success'])
        self.assertEqual(attempts[0]['change'],dict(field='model.main.b_mm',before=100,after=125))
        folder=Path(result.artifacts[0]['path']).parent
        hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.rglob('*.json')}
        repeated=self.execute();self.assertTrue(repeated.success)
        self.assertNotEqual(result.result['revision_id'],repeated.result['revision_id'])
        self.assertTrue(all(hashlib.sha256(p.read_bytes()).hexdigest()==h for p,h in hashes.items()))

    def test_round_limit_and_exhausted_candidates_never_return_a_final_reference(self):
        for count,choices in [(1,[100,125,150]),(3,[100,110,125]),(4,[100])]:
            p=deepcopy(self.parameters);p.update(max_attempts=count,allowed_changes={'model.main.b_mm':choices})
            result=self.execute(p);self.assertFalse(result.success)
            self.assertIn(result.result['status'],('LIMIT','STOPPED'))
            self.assertLessEqual(result.result['attempt_count'],count)
            self.assertIsNone(result.result['final_reference'])

    def test_bad_authorisation_is_rejected_before_any_calculation_or_journal(self):
        for changes in ({'model.loads.live_kN_m2':[2,3]}, {'model.main.b_mm':[125,150]},
                        {'model.main.b_mm':[100,99]}, {'model.main.b_mm':[100,True]},
                        {'model.main.b_mm':[100,100]}, {}):
            p=deepcopy(self.parameters);p['allowed_changes']=changes
            self.assertFalse(self.execute(p).success)
        for count in (True,0,5):
            p=deepcopy(self.parameters);p['max_attempts']=count
            self.assertFalse(self.execute(p).success)
        self.assertFalse((self.root/'revisions').exists())
        self.assertFalse((self.root/'designs').exists())

    def test_timeout_is_not_diagnosed_or_retried(self):
        adapter=self.registry.get('design_floor_system')._adapter
        proposal=self.registry.get('propose_floor_revision')
        with (patch.object(adapter,'design',side_effect=FloorAdapterError('design_timeout','simulated timeout')),
              patch.object(proposal,'_execute') as diagnose):
            result=self.execute();self.assertEqual(result.result['attempt_count'],1)
            self.assertEqual(result.result['status'],'STOPPED');diagnose.assert_not_called()

    def test_unknown_engineering_rejection_does_not_lower_load_or_change_materials(self):
        p=deepcopy(self.parameters);p['initial_parameters']['model']['loads']['live_kN_m2']=100
        result=self.execute(p)
        self.assertFalse(result.success);self.assertEqual(result.result['status'],'STOPPED')
        self.assertEqual(result.result['attempt_count'],1)
        self.assertEqual(result.result['final_parameters'],p['initial_parameters'])

    def test_malicious_proposals_cannot_change_protected_fields_or_skip_candidates(self):
        proposal=self.registry.get('propose_floor_revision')
        for changes in ({'loads':3}, {'width':200}, {'width':150}, {'width':125,'loads':3}):
            def malicious(data):
                candidate=deepcopy(data['parameters']['design_parameters'])
                if 'width' in changes:candidate['model']['main']['b_mm']=changes['width']
                if 'loads' in changes:candidate['model']['loads']['live_kN_m2']=changes['loads']
                return ToolResult(True,proposal.name,proposal.version,result=dict(action='revise',parameters=candidate,
                    reason='simulated malicious proposal',changes=[dict(field='model.main.b_mm',before=100,after=changes.get('width',125))]))
            with patch.object(proposal,'_execute',side_effect=malicious):
                result=self.execute()
                self.assertFalse(result.success);self.assertEqual(result.result['attempt_count'],1)

    def test_wrong_check_reference_stops_both_pass_and_domain_failure(self):
        parameters=deepcopy(self.parameters)
        parameters['initial_parameters']['model']['main']['b_mm']=250
        parameters['allowed_changes']={'model.slab.h_mm':[80,90]}
        check=self.registry.get('check_floor_design');original=check._execute
        proposal=self.registry.get('propose_floor_revision')
        for fail in (False,True):
            def wrong_reference(data):
                payload=original(data)
                result=deepcopy(payload.result)
                result['design_result_ref']='floor-design-other-attempt'
                return ToolResult(not fail,check.name,check.version,result=result,
                    errors=[dict(code='design_check_failed',message='Simulated failure',path=[])] if fail else [])
            with (patch.object(check,'_execute',side_effect=wrong_reference),
                  patch.object(proposal,'_execute') as diagnose):
                result=self.execute(parameters)
                self.assertFalse(result.success);self.assertEqual(result.result['attempt_count'],1)
                self.assertEqual(result.result['status'],'STOPPED');diagnose.assert_not_called()

    def test_result_publication_failure_never_declares_pass_or_calls_cad(self):
        def fail_result(path,data,**kwargs):
            if Path(path).name=='result.json':raise OSError('Simulated disk failure')
            return write_json(path,data,**kwargs)
        controller=AgentController(self.registry,ExplicitRevisionParser(self.parameters),AgentState(self.root/'agent'),[self.workflow])
        with (patch('agent.revision.write_json',side_effect=fail_result),
              patch.object(self.backend,'execute',wraps=self.backend.execute) as cad):
            result=controller.run('explicit test request',project_id='qa')
        self.assertFalse(result['success']);cad.assert_not_called()
        self.assertEqual(result['steps']['cad'],'skipped')
        manifest=json.loads(next((self.root/'revisions').glob('*/state.json')).read_text(encoding='utf-8'))
        self.assertEqual(manifest['status'],'RUNNING')
        self.assertFalse(list((self.root/'revisions').glob('*/result.json')))

    def test_total_budget_stops_after_inflight_call_and_interrupt_keeps_journal(self):
        ticks=iter([0,0,181]);self.tool.clock=lambda:next(ticks)
        result=self.execute();self.assertEqual(result.result['status'],'TIMEOUT')
        self.assertIsNone(result.result['final_reference'])
        self.tool.clock=lambda:0
        with patch.object(self.registry.get('design_floor_system'),'_execute',side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):self.execute()
        manifests=[json.loads(p.read_text(encoding='utf-8')) for p in (self.root/'revisions').glob('*/state.json')]
        self.assertTrue(any(m['status']=='INTERRUPTED' for m in manifests))

    def test_declared_workflow_calls_cad_once_after_final_pass_and_never_on_failure(self):
        for p,expected in [(self.parameters,True),({**self.parameters,'max_attempts':1},False)]:
            controller=AgentController(self.registry,ExplicitRevisionParser(p),AgentState(self.root/'agent'),[self.workflow])
            with patch.object(self.backend,'execute',wraps=self.backend.execute) as cad:
                result=controller.run('explicit test request',project_id='qa')
                self.assertEqual(result['success'],expected,result)
                self.assertEqual(cad.call_count,1 if expected else 0)
                self.assertEqual(result['steps']['cad'],'completed' if expected else 'skipped')

    def test_simulated_check_fail_is_preserved_then_new_design_passes(self):
        p=deepcopy(self.parameters);p['initial_parameters']['model']['main']['b_mm']=250
        p['allowed_changes']={'model.slab.h_mm':[80,90]}
        check=self.registry.get('check_floor_design');original=check._execute
        counter=0
        def fail_once(data):
            nonlocal counter
            payload=original(data);counter+=1
            if counter!=1:return payload
            self.assertTrue(payload.success)
            result=deepcopy(payload.result)
            item=next(item for item in result['checks'] if item['id']=='slab.0.flexure')
            item.update(actual=0,passed=False)
            result.update(status='FAIL',summary=dict(total=len(result['checks']),passed=len(result['checks'])-1,failed=1))
            return ToolResult(False,check.name,check.version,result=result,
                errors=[dict(code='design_check_failed',message='Simulated slab flexure failure',path=[])],metadata=payload.metadata)
        with patch.object(check,'_execute',side_effect=fail_once):
            result=self.execute(p)
        self.assertTrue(result.success,result.errors)
        self.assertEqual(result.result['attempt_count'],2)
        failed_path=Path(result.result['attempts'][0]['check']['path'])
        failed=json.loads(failed_path.read_text(encoding='utf-8'))
        self.assertFalse(failed['success']);self.assertEqual(failed['result']['status'],'FAIL')
        self.assertEqual(result.result['final_parameters']['model']['slab']['h_mm'],90)

    def test_composition_is_reusable_for_non_floor_tools(self):
        class DemoTool(EngineeringTool):
            def __init__(self,name,schema,output,execute):
                super().__init__(name=name,version='1',description='Test only',parameters_schema=schema,output_schema=output)
                self.perform=execute
            def _execute(self,data):return self.perform(data)
        registry=ToolRegistry()
        initial=object_schema({'x':{'type':'number'}})
        output=object_schema({'ref':{'type':'string'}})
        registry.register(DemoTool('demo_design',initial,output,lambda d:
            ToolResult.failure('demo_design','1','capacity_shortage','test shortage') if d['parameters']['x']==1 else
            ToolResult(True,'demo_design','1',result={'ref':'candidate-2'})))
        registry.register(DemoTool('demo_check',output,object_schema({'ref':{'type':'string'},'status':{'const':'PASS'}}),
            lambda d:ToolResult(True,'demo_check','1',result={'ref':d['parameters']['ref'],'status':'PASS'})))
        registry.register(DemoTool('demo_propose',{'type':'object'}, {'type':'object'},lambda d:
            ToolResult(True,'demo_propose','1',result=dict(action='revise',parameters={'x':2},reason='test',
                changes=[dict(field='x',before=1,after=2)]))))
        spec=RevisionSpec('demo_design','demo_check','demo_propose',('result','ref'),'ref',('result','ref'),('capacity_shortage',))
        tool=BoundedRevisionTool(name='demo_revision',description='Test only',registry=registry,root=self.root/'generic',
            spec=spec,initial_schema=initial,changes_schema=object_schema({'x':{'type':'array','items':{'type':'number'}}}),
            context_schema={'type':'object'})
        result=tool.execute(dict(project_id='qa',tool=tool.name,context=CONTEXT,parameters=dict(initial_parameters={'x':1},
            allowed_changes={'x':[1,2]},max_attempts=2,time_budget_seconds=10)))
        self.assertTrue(result.success,result.errors);self.assertEqual(result.result['final_reference'],'candidate-2')


if __name__=='__main__':unittest.main()
