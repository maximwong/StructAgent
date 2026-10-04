"""Discover installed local plugins and publish a validated capability catalog.

Plugin Python is trusted application code, not a sandbox or downloaded extension.
Manifests are data; only the fixed plugin.py entry file may be imported.
"""

from dataclasses import dataclass
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys

from .plugin_base import PluginContext, PluginContribution, PluginWebBinding
from .tool_registry import ToolRegistry

IDENTIFIER = re.compile(r'[a-z][a-z0-9_]*\Z')
VERSION = re.compile(r'(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)\Z')
MAX_MANIFEST_BYTES = 65536


class PluginLoadError(ValueError):
    def __init__(self, code, plugin_id=None):
        self.code, self.plugin_id = code, plugin_id
        # Do not expose arbitrary plugin exception text, paths, or local secrets.
        super().__init__(f'Plugin loading failed: {code}' + (f' ({plugin_id})' if plugin_id else ''))


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate manifest key.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Non-finite manifest value.')


def discover_plugins(directory):
    root = Path(directory).resolve()
    if not root.is_dir():
        raise PluginLoadError('plugin_directory_missing')
    discovered = []
    for path in sorted(root.glob('*/plugin.json')):
        plugin_id = path.parent.name
        if not IDENTIFIER.fullmatch(plugin_id):
            raise PluginLoadError('invalid_plugin_directory')
        try:
            if path.resolve() != path or path.parent.resolve() != path.parent:
                raise ValueError('Redirected manifest.')
            raw = path.read_bytes()
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ValueError('Oversized manifest.')
            manifest = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs,
                                  parse_constant=_invalid_constant)
        except (OSError, ValueError):
            raise PluginLoadError('invalid_manifest', plugin_id) from None
        required = {'id', 'name', 'version', 'api_version', 'description', 'entry_point', 'tools'}
        if (not isinstance(manifest, dict) or not required <= manifest.keys()
                or manifest.keys() - required - {'enabled'}):
            raise PluginLoadError('invalid_manifest', plugin_id)
        if type(manifest['api_version']) is not int or manifest['api_version'] != 1:
            raise PluginLoadError('unsupported_plugin_api', plugin_id)
        if (manifest['id'] != plugin_id
                or not isinstance(manifest['version'], str) or not VERSION.fullmatch(manifest['version'])
                or any(not isinstance(manifest[k], str) or not 1 <= len(manifest[k].strip()) <= 1000
                       for k in ('name', 'description'))
                or type(manifest.get('enabled', True)) is not bool
                or not isinstance(manifest['entry_point'], str)
                or re.fullmatch(r'plugin\.py:[a-z][a-z0-9_]*', manifest['entry_point']) is None
                or not isinstance(manifest['tools'], list) or not manifest['tools']
                or any(not isinstance(name, str) or not IDENTIFIER.fullmatch(name) for name in manifest['tools'])
                or len(set(manifest['tools'])) != len(manifest['tools'])):
            raise PluginLoadError('invalid_manifest', plugin_id)
        discovered.append((path.parent, manifest))
    return discovered


def _factory(directory, manifest):
    path = directory/'plugin.py'
    if not path.is_file() or path.resolve() != path:
        raise PluginLoadError('plugin_entry_missing', manifest['id'])
    namespace = '_structagent_plugin_' + hashlib.sha256(str(path).encode()).hexdigest()[:24]
    module = sys.modules.get(namespace)
    if module is None:
        spec = importlib.util.spec_from_file_location(namespace, path, submodule_search_locations=[str(directory)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[namespace] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            for key in list(sys.modules):
                if key == namespace or key.startswith(namespace+'.'):
                    del sys.modules[key]
            raise PluginLoadError('plugin_import_failed', manifest['id']) from None
    factory = getattr(module, manifest['entry_point'].split(':')[1], None)
    if not callable(factory):
        raise PluginLoadError('plugin_factory_missing', manifest['id'])
    return factory


@dataclass(frozen=True)
class PluginCatalog:
    registry: ToolRegistry
    workflows: tuple
    profiles: tuple
    plugins: tuple
    web_bindings: tuple

    def web_binding(self):
        if len(self.web_bindings) != 1:
            raise PluginLoadError('one_web_plugin_required')
        return self.web_bindings[0]

    def explicit_profiles(self, model):
        from agent.parameter_parser import LanguageProfile
        binding = self.web_binding()
        profile = binding.explicit_factory(model)
        if (not isinstance(profile, LanguageProfile) or profile.name != binding.explicit_profile
                or profile.tool not in {w.steps[0].tool for w in self.workflows}):
            raise PluginLoadError('invalid_explicit_profile')
        return (profile,)

    def report_workflow(self, envelope):
        name = self.web_binding().report_workflow
        workflow = next(w for w in self.workflows if w.name == name)
        if not isinstance(envelope, dict) or envelope.get('tool') != workflow.steps[0].tool:
            raise PluginLoadError('report_tool_mismatch')
        return workflow

    def describe(self):
        return {'plugins': deepcopy(list(self.plugins)), 'tools': self.registry.list_tools(),
                'workflows': [{'name': w.name, 'entry_tool': w.steps[0].tool} for w in self.workflows],
                'profiles': [{'name': p.name, 'tool': p.tool, 'description': p.description} for p in self.profiles]}


def load_plugins(directory, context):
    from agent.parameter_parser import LanguageProfile, ParameterParser
    from agent.workflow import Workflow
    if not isinstance(context, PluginContext):
        raise TypeError('PluginContext is required.')
    manifests = discover_plugins(directory)  # Validate all metadata before running any plugin code.
    registry, workflows, profiles, web, descriptions = ToolRegistry(), [], [], [], []
    workflow_names, entry_tools, profile_names, explicit_names = set(), set(), set(), set()
    for location, manifest in manifests:
        if not manifest.get('enabled', True):
            continue
        plugin_id = manifest['id']
        try:
            contribution = _factory(location, manifest)(context)
            if not isinstance(contribution, PluginContribution) or not isinstance(contribution.registry, ToolRegistry):
                raise PluginLoadError('invalid_contribution', plugin_id)
            actual = contribution.registry.list_tools()
            if {item['name'] for item in actual} != set(manifest['tools']):
                raise PluginLoadError('manifest_tool_mismatch', plugin_id)
            for item in actual:
                if item['name'] in {existing['name'] for existing in registry.list_tools()}:
                    raise PluginLoadError('duplicate_tool', plugin_id)
                registry.register(contribution.registry.get(item['name']))
            for workflow in contribution.workflows:
                if not isinstance(workflow, Workflow):
                    raise PluginLoadError('invalid_workflow', plugin_id)
                if workflow.name in workflow_names or workflow.steps and workflow.steps[0].tool in entry_tools:
                    raise PluginLoadError('duplicate_workflow', plugin_id)
                workflow.validate(contribution.registry)  # v1 dependencies stay within the plugin.
                workflow_names.add(workflow.name); entry_tools.add(workflow.steps[0].tool)
                workflows.append(workflow)
            for profile in contribution.profiles:
                if not isinstance(profile, LanguageProfile) or not IDENTIFIER.fullmatch(profile.name):
                    raise PluginLoadError('invalid_profile', plugin_id)
                if profile.name in profile_names or profile.name in explicit_names:
                    raise PluginLoadError('duplicate_profile', plugin_id)
                if profile.tool not in {w.steps[0].tool for w in contribution.workflows}:
                    raise PluginLoadError('profile_workflow_missing', plugin_id)
                ParameterParser(contribution.registry, None, [profile])
                profile_names.add(profile.name); profiles.append(profile)
            if contribution.web is not None:
                binding = contribution.web
                if (not isinstance(binding, PluginWebBinding)
                        or binding.template_profile not in {p.name for p in contribution.profiles}
                        or not isinstance(binding.explicit_profile, str) or not IDENTIFIER.fullmatch(binding.explicit_profile)
                        or binding.explicit_profile in profile_names or binding.explicit_profile in explicit_names
                        or any(not callable(getattr(binding, name)) for name in
                               ('explicit_factory', 'input_form', 'report_source', 'report_validator', 'recover'))):
                    raise PluginLoadError('invalid_web_binding', plugin_id)
                report = next((w for w in contribution.workflows if w.name == binding.report_workflow), None)
                if (report is None or report.name != 'artifact_report' or len(report.steps) != 1
                        or report.steps[0].name != 'report' or report.steps[0].external_effects):
                    raise PluginLoadError('invalid_report_binding', plugin_id)
                web.append(binding)
                explicit_names.add(binding.explicit_profile)
            descriptions.append({k: manifest[k] for k in ('id', 'name', 'version', 'api_version', 'description', 'tools')})
        except PluginLoadError:
            raise
        except Exception:
            raise PluginLoadError('plugin_composition_failed', plugin_id) from None
    if not descriptions:
        raise PluginLoadError('no_enabled_plugins')
    return PluginCatalog(registry, tuple(workflows), tuple(profiles), tuple(descriptions), tuple(web))
