"""Real local plugin discovery; cloud/CAD are explicitly simulated where used."""

import ast
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from types import SimpleNamespace
from app import controller_factory, create_service
from core.plugin_base import PluginContext
from core.plugin_loader import discover_plugins, load_plugins, PluginLoadError
from tests.test_agent_controller import SimulatedCAD
from tests.test_explicit_input import model, proposal
from ui.service import RunService

ROOT = Path(__file__).resolve().parents[1]


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)/'中文 插件'; self.directory.mkdir()
        self.output = Path(self.temp.name)/'输出'
        self.context = PluginContext(self.output, {'cad_backend': SimulatedCAD()})

    def add(self, name='echo', *, tool='echo_value', workflow='echo_workflow', profile='echo_v1', **changes):
        path = self.directory/name; path.mkdir()
        manifest = dict(id=name, name='Test '+name, version='1.0.0', api_version=1,
                        description='No engineering', entry_point='plugin.py:create_plugin', tools=[tool])
        manifest.update(changes)
        (path/'plugin.json').write_text(json.dumps(manifest), encoding='utf-8')
        (path/'plugin.py').write_text('from tests.plugin_fixture import contribution\n'
            f'def create_plugin(context): return contribution(context, {tool!r}, {workflow!r}, {profile!r})\n', encoding='utf-8')
        return path

    def floor(self):
        shutil.copytree(ROOT/'plugins/rc_floor', self.directory/'rc_floor', ignore=shutil.ignore_patterns('__pycache__'))

    def error(self, expected):
        with self.assertRaises(PluginLoadError) as caught:
            load_plugins(self.directory, self.context)
        self.assertEqual(caught.exception.code, expected)
        return caught.exception

    def test_floor_inventory_has_versions_and_both_schemas_without_execution(self):
        with patch('tools.floor.design_tool.FloorDesignTool.execute', side_effect=AssertionError('No calculation')):
            catalog = load_plugins(ROOT/'plugins', self.context)
        view = catalog.describe()
        self.assertEqual([p['id'] for p in view['plugins']], ['rc_column', 'rc_floor'])
        self.assertEqual({t['name'] for t in view['tools']},
                         {'design_floor_system','check_floor_design','generate_floor_cad','generate_floor_report',
                          'design_column','check_column_design',
                          'design_column_combinations','check_column_combinations','design_column_layouts','check_column_layouts','design_column_eccentric','check_column_eccentric'})
        self.assertTrue(all(t['version']=='1.0.0' and t['input_schema'] and t['output_schema'] for t in view['tools']))
        self.assertEqual(catalog.web_binding().explicit_profile, 'floor_explicit_v1')
        floor = next(p for p in view['plugins'] if p['id'] == 'rc_floor')
        floor['tools'].clear()
        self.assertEqual(len(next(p for p in catalog.describe()['plugins'] if p['id'] == 'rc_floor')['tools']),4)

    def test_second_plugin_executes_through_unchanged_application_and_controller(self):
        self.floor()
        shutil.copytree(ROOT/'tests/fixtures/plugins/echo', self.directory/'echo')
        before = (ROOT/'agent/controller.py').read_bytes()
        gateway = Mock(); gateway.complete.return_value = ({'tool':'echo_value','parameters':{'value':6}}, {})
        with patch('app.load_settings'), patch('app.DeepSeekGateway', return_value=gateway):
            controller = controller_factory(self.output, plugin_directory=self.directory, plugin_options=self.context.options)
            result = controller.run('6', project_id='plugin-proof', profile_name='echo_v1')
        self.assertTrue(result['success'], result)
        self.assertEqual([c['tool'] for c in result['tool_calls']], ['echo_value'])
        saved = json.loads(Path(result['tool_calls'][0]['result_path']).read_text(encoding='utf-8'))
        self.assertEqual(saved['result'], {'value':6})
        self.assertEqual((ROOT/'agent/controller.py').read_bytes(), before)
        self.assertEqual(len(controller.capabilities()),5)

    def test_disabled_plugin_code_is_never_imported(self):
        self.floor(); path = self.add(enabled=False)
        (path/'plugin.py').write_text("raise RuntimeError('must not execute')", encoding='utf-8')
        self.assertEqual([p['id'] for p in load_plugins(self.directory,self.context).plugins],['rc_floor'])

    def test_invalid_manifest_versions_names_and_entry_points_fail_before_import(self):
        path = self.add(); original = json.loads((path/'plugin.json').read_text(encoding='utf-8'))
        (path/'plugin.py').write_text("raise RuntimeError('must not import')", encoding='utf-8')
        for changes, code in [({'api_version':2},'unsupported_plugin_api'),({'api_version':True},'unsupported_plugin_api'),
                ({'id':'other'},'invalid_manifest'),({'version':'1.0'},'invalid_manifest'),
                ({'entry_point':'../other.py:run'},'invalid_manifest'),({'enabled':'yes'},'invalid_manifest'),
                ({'tools':['echo_value','echo_value']},'invalid_manifest'),({'name':None},'invalid_manifest')]:
            with self.subTest(changes=changes):
                (path/'plugin.json').write_text(json.dumps(original|changes),encoding='utf-8'); self.error(code)
        (path/'plugin.json').write_text('{"id":"echo","id":"other"}',encoding='utf-8')
        self.error('invalid_manifest')

    def test_all_manifests_are_checked_before_any_plugin_import(self):
        path = self.add('a'); marker=self.directory/'imported'
        (path/'plugin.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n',encoding='utf-8')
        self.add('z', api_version=999)
        self.error('unsupported_plugin_api'); self.assertFalse(marker.exists())

    def test_declared_tools_must_match_contributed_tools(self):
        self.add(tools=['nonexistent']); self.error('manifest_tool_mismatch')

    def test_duplicate_tools_abort_catalog_instead_of_overwriting(self):
        self.add('a'); self.add('b',workflow='other_workflow',profile='other_profile')
        self.error('duplicate_tool')

    def test_duplicate_workflows_or_profiles_abort_catalog(self):
        self.add('a'); path=self.add('b',tool='other_value',profile='other_profile')
        self.error('duplicate_workflow')
        (path/'plugin.py').write_text("from tests.plugin_fixture import contribution\n"
            "def create_plugin(context): return contribution(context,'other_value','other_workflow','echo_v1')",encoding='utf-8')
        # Existing Python modules are intentionally not hot-reloaded; a fresh directory models a restart.
        fresh = self.directory/'fresh'; fresh.mkdir(); shutil.copytree(self.directory/'a',fresh/'a'); shutil.copytree(path,fresh/'b')
        with self.assertRaises(PluginLoadError) as caught: load_plugins(fresh,self.context)
        self.assertEqual(caught.exception.code,'duplicate_profile')

    def test_invalid_workflow_dependencies_are_not_published(self):
        path=self.add()
        (path/'plugin.py').write_text("from tests.plugin_fixture import contribution\nfrom core.plugin_base import PluginContribution\n"
            "from agent.workflow import Workflow,WorkflowStep\n"
            "def create_plugin(context):\n c=contribution(context)\n return PluginContribution(c.registry,(Workflow('bad',(WorkflowStep('bad','missing'),)),),c.profiles)\n",encoding='utf-8')
        self.error('plugin_composition_failed')

    def test_import_and_factory_failures_are_sanitized_and_missing_entry_is_reported(self):
        path=self.add()
        (path/'plugin.py').write_text("raise RuntimeError('PRIVATE_TEST_SECRET')",encoding='utf-8')
        self.assertNotIn('PRIVATE_TEST_SECRET',str(self.error('plugin_import_failed')))
        (path/'plugin.py').write_text("def create_plugin(context): raise RuntimeError('PRIVATE_TEST_SECRET')",encoding='utf-8')
        self.assertNotIn('PRIVATE_TEST_SECRET',str(self.error('plugin_composition_failed')))
        missing = self.directory/'missing'; missing.mkdir(); shutil.copytree(path,missing/'echo')
        (missing/'echo/plugin.py').write_text('value=1',encoding='utf-8')
        with self.assertRaises(PluginLoadError) as caught:load_plugins(missing,self.context)
        self.assertEqual(caught.exception.code,'plugin_factory_missing')

    def test_relative_plugin_imports_and_repeat_builds_use_fresh_tool_instances(self):
        path=self.add()
        (path/'helpers.py').write_text('from tests.plugin_fixture import contribution',encoding='utf-8')
        (path/'plugin.py').write_text('from .helpers import contribution\ndef create_plugin(context): return contribution(context)',encoding='utf-8')
        first=load_plugins(self.directory,self.context);second=load_plugins(self.directory,self.context)
        self.assertIsNot(first.registry.get('echo_value'),second.registry.get('echo_value'))

    def test_disabled_only_or_missing_directory_cannot_start_application(self):
        self.add(enabled=False);self.error('no_enabled_plugins')
        with self.assertRaises(PluginLoadError) as caught:discover_plugins(self.directory/'absent')
        self.assertEqual(caught.exception.code,'plugin_directory_missing')

    def test_reserved_explicit_profile_cannot_collide_with_another_plugin(self):
        self.floor();self.add('z',profile='floor_explicit_v1')
        self.error('duplicate_profile')

    def test_floor_recovery_callback_preserves_command_timeout_and_success_gate(self):
        recover=load_plugins(ROOT/'plugins',self.context).web_binding().recover
        with patch(recover.__module__+'.subprocess.run') as execute:
            execute.return_value=SimpleNamespace(returncode=0,stdout=b'{"success":true}')
            recover(self.output)
            self.assertEqual(execute.call_args.args[0],[sys.executable,'-m','examples.cad_recovery','--output-root',str(self.output)])
            self.assertEqual(execute.call_args.kwargs['timeout'],40)
            self.assertEqual(execute.call_args.kwargs['cwd'],ROOT)
            for result in (SimpleNamespace(returncode=1,stdout=b'{"success":true}'),
                           SimpleNamespace(returncode=0,stdout=b'{"success":false}')):
                execute.return_value=result
                with self.assertRaises(ValueError):recover(self.output)

    def test_missing_web_composition_and_wrong_report_tool_are_rejected(self):
        self.add();catalog=load_plugins(self.directory,self.context)
        with self.assertRaises(PluginLoadError) as caught:catalog.web_binding()
        self.assertEqual(caught.exception.code,'one_web_plugin_required')
        catalog=load_plugins(ROOT/'plugins',self.context)
        with self.assertRaises(PluginLoadError) as caught:catalog.report_workflow({'tool':'design_floor_system'})
        self.assertEqual(caught.exception.code,'report_tool_mismatch')

    def test_ui_uses_injected_profile_names_instead_of_floor_identifiers(self):
        factory=Mock();explicit=Mock()
        for builder in (factory,explicit):builder.return_value.run.return_value={'success':True}
        service=RunService(self.output,factory,settings_check=lambda:SimpleNamespace(api_key='FAKE_TEST_KEY'),
            recover=Mock(),opener=Mock(),explicit_controller_factory=explicit,
            template_profile='custom_template',explicit_profile='custom_explicit')
        first=service.start(dict(project_name='测试',text='6',template_confirmed=True))['id'];service.thread.join(5)
        self.assertEqual(service._record(first)['profile'],'custom_template')
        self.assertEqual(factory.return_value.run.call_args.kwargs['profile_name'],'custom_template')
        second=service.start(dict(project_name='测试',text='6',input_mode='explicit',model={}))['id'];service.thread.join(5)
        self.assertEqual(service._record(second)['profile'],'custom_explicit')
        self.assertEqual(explicit.return_value.run.call_args.kwargs['profile_name'],'custom_explicit')

    def test_generic_files_have_no_professional_imports(self):
        for file in ('app.py','core/plugin_base.py','core/plugin_loader.py','agent/controller.py'):
            tree=ast.parse((ROOT/file).read_text(encoding='utf-8-sig'))
            imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and n.module]
            imports += [a.name for n in ast.walk(tree) if isinstance(n,ast.Import) for a in n.names]
            self.assertFalse(any(name.startswith(('tools.floor','tools.column','legacy')) for name in imports),file)

    def test_inventory_cli_is_valid_utf8_without_api_configuration(self):
        result=subprocess.run([sys.executable,'-m','examples.plugin_inventory'],cwd=ROOT,capture_output=True,check=True)
        self.assertEqual({p['id'] for p in json.loads(result.stdout.decode('utf-8'))['plugins']},
                         {'rc_floor', 'rc_column'})

    def test_explicit_design_and_separate_report_reuse_the_loaded_plugin(self):
        gateway=Mock();gateway.complete.return_value=(proposal(slab_thickness=(100,{'quote':'100mm','index':0})),{})
        base=model();base['loads']['live_kN_m2']=2.0
        options=self.context.options
        with patch('app.load_settings',return_value=SimpleNamespace(api_key='FAKE_TEST_KEY')),patch('app.DeepSeekGateway',return_value=gateway):
            service=create_service(self.output,plugin_options=options)
            service.opener=Mock()
            job=service.start({'project_name':'插件完整参数测试','text':'板厚改100mm，其余按已填参数设计。',
                               'input_mode':'explicit','model':base})['id']
            service.thread.join(30)
        self.assertFalse(service.thread.is_alive())
        original=service.view(job)['snapshot']; self.assertTrue(original['success'],original)
        self.assertEqual(original['parse_result']['envelope']['parameters']['model']['slab']['h_mm'],100)
        service.reports.start(job);service.thread.join(90)
        self.assertFalse(service.thread.is_alive())
        view=service.view(job)
        self.assertEqual(view['report']['status'],'completed',view['report'])
        self.assertEqual(view['snapshot'],original)
        self.assertNotEqual(view['report']['run_id'],original['run_id'])
        self.assertTrue(service.reports.artifact(job)['content'].startswith(b'PK'))


if __name__=='__main__':unittest.main()
