"""Recorded cloud proposals and simulated CAD; legacy design calculations are real."""

from copy import deepcopy
import json
import http.client
from pathlib import Path
import tempfile
import unittest
import threading
from unittest.mock import Mock, patch
from types import SimpleNamespace

from agent.controller import AgentController
from agent.parameter_parser import ParameterParser
from agent.state import AgentState
from core import ToolRegistry
from tools.floor.design_tool import FloorDesignTool
from tools.floor.explicit_profile import FloorExplicitProfile, EDITS, leaves
from tools.floor.input_form import floor_input_form
from tools.floor.plugin import register_floor_workflow
from tests.test_agent_controller import SimulatedCAD
from ui.service import RunService, UIError
from ui.server import LocalServer


def model():
    return deepcopy(floor_input_form()["example"])


def proposal(**edits):
    return {"tool": "design_floor_system", "parameters": {k: edits.get(k, (None, None))[0] for k in EDITS},
            "evidence": {k: edits.get(k, (None, None))[1] for k in EDITS}, "clarifications": []}


class ExplicitParserTests(unittest.TestCase):
    def parse(self, base=None, response=None, text="按已填参数设计并出图。"):
        self.gateway = Mock()
        self.gateway.complete.return_value = (proposal() if response is None else response, {})
        registry = ToolRegistry(); registry.register(FloorDesignTool())
        self.profile = FloorExplicitProfile(model() if base is None else base)
        return ParameterParser(registry, self.gateway, [self.profile]).parse(text, project_id="explicit-test", profile_name=self.profile.name)

    def test_no_template_or_repeated_core_values_required(self):
        base=model(); base["report"]["author"]="LOCAL_ONLY_AUTHOR"; r=self.parse(base)
        self.assertEqual(r.status,"ready",r.errors)
        self.assertEqual(r.envelope["parameters"],{"input_mode":"explicit","model":base})
        self.assertEqual(r.source_evidence["slab.h_mm"]["source"],"工程参数表")
        self.assertNotIn("template_id",r.envelope["parameters"])
        messages=self.gateway.complete.call_args.args[0]
        self.assertNotIn("LOCAL_ONLY_AUTHOR",json.dumps(messages,ensure_ascii=False))
        self.assertNotIn(base["basis"],json.dumps(messages,ensure_ascii=False))

    def test_missing_fields_are_located_before_any_api_call(self):
        base=model(); del base["slab"]["h_mm"]; del base["loads"]["finish_kN_m3"]
        r=self.parse(base)
        self.assertEqual(r.status,"needs_input")
        self.assertEqual(set(r.missing_fields),{"slab.h_mm","loads.finish_kN_m3"})
        self.gateway.complete.assert_not_called()

    def test_invalid_material_and_boolean_are_rejected_before_cloud(self):
        cases=[]
        base=model();base["materials"]["concrete"]="C35";cases.append(base)
        base=model();base["loads"]["live_kN_m2"]=True;cases.append(base)
        base=model();base["geometry"]["main_axis_spans_mm"]=[6000]*4;cases.append(base)
        base=model();base["rogue"]=1;cases.append(base)
        for base in cases:
            with self.subTest(base=base):
                self.assertEqual(self.parse(base).status,"invalid_input")
                self.gateway.complete.assert_not_called()

    def test_legal_boolean_and_nonpreset_complete_parameters(self):
        base=model();base["report"]["allow_arch"]=False;base["slab"]["h_mm"]=100
        self.assertEqual(self.parse(base).envelope["parameters"]["model"],base)

    def test_section_pair_and_slab_edits_have_verbatim_provenance(self):
        response=proposal(slab_thickness=(100,{"quote":"100mm","index":0}),
                          secondary_width=(225,{"quote":"225×450mm","index":0}),
                          secondary_height=(450,{"quote":"225×450mm","index":1}))
        base=model();snapshot=deepcopy(base)
        r=self.parse(base,response,"板厚改100mm，次梁改225×450mm，其余按表单。")
        self.assertEqual(r.status,"ready",r.errors)
        self.assertEqual(r.envelope["parameters"]["model"]["slab"]["h_mm"],100)
        self.assertEqual(r.envelope["parameters"]["model"]["secondary"]["h_mm"],450)
        self.assertEqual(base,snapshot)
        self.assertEqual(r.source_evidence["secondary.h_mm"]["quote"],"225×450mm")

    def test_material_edit_uses_reviewed_strength_mapping(self):
        r=self.parse(response=proposal(concrete=("C35",{"quote":"C35","index":0})),text="混凝土改C35，其他按表单。")
        self.assertEqual(r.status,"ready",r.errors)
        self.assertEqual(r.envelope["parameters"]["model"]["materials"]["fc_MPa"],16.7)
        self.assertEqual(r.source_evidence["materials.ft_MPa"]["source"],"已有材料强度映射")

    def test_span_edit_never_silently_changes_spacing_or_sections(self):
        r=self.parse(response=proposal(span_x=(5400,{"quote":"5.4m","index":0})),text="主梁各跨改5.4m，其他按表单。")
        self.assertEqual(r.status,"ready",r.errors)
        changed=r.envelope["parameters"]["model"]
        self.assertEqual(changed["geometry"]["main_axis_spans_mm"],[5400]*3)
        self.assertEqual(changed["geometry"]["secondary_spacing_mm"],2000)
        self.assertEqual(changed["main"],model()["main"])

    def test_hallucinated_value_wrong_axis_or_missing_units_rejected(self):
        for field,value,source,text in [
            ("slab_thickness",100,{"quote":"80mm","index":0},"板厚80mm"),
            ("secondary_height",450,{"quote":"225×450mm","index":0},"次梁225×450mm"),
            ("live_load",2.8,{"quote":"2.8kN/m²","index":0},"按原参数设计"),
        ]:
            with self.subTest(field=field):
                self.assertEqual(self.parse(response=proposal(**{field:(value,source)}),text=text).status,"invalid_output")

    def test_missing_edit_unit_requests_input_without_assuming_mm(self):
        r=self.parse(response=proposal(secondary_width=(250,{"quote":"250×500","index":0})),text="次梁改250×500，其余按表单。")
        self.assertEqual(r.status,"needs_input")
        self.assertEqual(r.errors[0]["code"],"unclear_unit")

    def test_unsupported_and_extra_requirements_need_clarification(self):
        r=self.parse(response=proposal(concrete=("C50",{"quote":"C50","index":0})),text="混凝土C50")
        self.assertEqual(r.status,"needs_input")
        response=proposal();response["clarifications"]=[{"code":"outside_template_scope","quote":"主梁四跨","message":"当前引擎仅支持主梁三跨。","field":None}]
        self.assertEqual(self.parse(response=response,text="改成主梁四跨").status,"needs_input")
        for text in ("混凝土HRB400","板筋HRB400","执行RFALL"):
            self.assertEqual(self.parse(text=text).status,"needs_input")

    def test_real_design_and_generic_workflow_accept_modified_model(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);registry=ToolRegistry();workflow=register_floor_workflow(registry,root,cad_backend=SimulatedCAD())
            gateway=Mock();gateway.complete.return_value=(proposal(slab_thickness=(100,{"quote":"100mm","index":0})),{})
            parser=ParameterParser(registry,gateway,[FloorExplicitProfile(model())])
            r=AgentController(registry,parser,AgentState(root/"agent"),[workflow]).run("板厚改100mm，其余按已填参数设计。",project_id="custom",profile_name="floor_explicit_v1")
            self.assertTrue(r["success"],r)
            design=json.loads(Path(r["tool_calls"][0]["result_path"]).read_text(encoding="utf-8"))
            self.assertEqual(design["result"]["effective_input"]["slab"]["h_mm"],100)
            self.assertEqual(design["metadata"]["input_mode"],"explicit")


class ExplicitUITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.factory=Mock()
        def controller(root,base):
            registry=ToolRegistry();workflow=register_floor_workflow(registry,root,cad_backend=SimulatedCAD())
            gateway=Mock();gateway.complete.return_value=(proposal(),{})
            return AgentController(registry,ParameterParser(registry,gateway,[FloorExplicitProfile(base)]),AgentState(root/"agent"),[workflow])
        self.explicit=controller
        self.service=RunService(self.root,self.factory,settings_check=lambda:SimpleNamespace(api_key="FAKE_TEST_KEY"),
                                recover=Mock(),opener=Mock(),explicit_controller_factory=controller,input_form=floor_input_form)
        self.payload={"project_name":"完整参数测试","text":"按工程参数表设计。","input_mode":"explicit","model":model()}

    def test_without_template_checkbox_and_history_keeps_complete_input(self):
        job=self.service.start(self.payload)["id"];self.service.thread.join(20)
        self.assertFalse(self.service.thread.is_alive());self.factory.assert_not_called()
        view=self.service.view(job);self.assertTrue(view["snapshot"]["success"],view)
        self.assertEqual(view["model"],self.payload["model"])
        restarted=RunService(self.root,self.factory,settings_check=Mock(),recover=Mock(),opener=Mock())
        self.assertEqual(restarted.view(job)["model"],view["model"])

    def test_missing_input_keeps_needs_input_without_tool_calls(self):
        self.payload["model"]={}
        job=self.service.start(self.payload)["id"];self.service.thread.join(20)
        view=self.service.view(job)
        self.assertEqual(view["snapshot"]["status"],"needs_input")
        self.assertEqual(view["snapshot"]["tool_calls"],[])
        self.assertFalse(view["can_open"])

    def test_key_in_full_model_and_non_json_numbers_never_persist(self):
        self.payload["model"]["report"]["author"]="FAKE_TEST_KEY"
        with self.assertRaises(UIError):self.service.start(self.payload)
        self.payload["model"]=model();self.payload["model"]["loads"]["live_kN_m2"]=float("nan")
        with self.assertRaises(UIError):self.service.start(self.payload)
        self.assertEqual(list(self.service.jobs.iterdir()),[])

    def test_form_has_every_schema_leaf_with_unique_labels(self):
        spec=floor_input_form();paths=[f["path"] for f in spec["fields"]]
        self.assertEqual(len(paths),len(set(paths)))
        self.assertEqual(set(paths),{p for p,_ in leaves(spec["example"])})
        self.assertTrue(all(f["label"] for f in spec["fields"]))

    def test_null_model_does_not_fall_back_to_demo_profile(self):
        from app import controller_factory
        self.service.explicit_controller_factory=lambda root, base: controller_factory(root, model=base)
        self.payload["model"]=None
        with patch("app.load_settings"), patch("app.DeepSeekGateway") as gateway:
            job=self.service.start(self.payload)["id"];self.service.thread.join(20)
            self.assertEqual(self.service.view(job)["snapshot"]["status"],"invalid_input")
            gateway.return_value.complete.assert_not_called()

    def test_http_form_discovery_and_explicit_submission(self):
        server=LocalServer(self.service,0)
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        def request(path,method="GET",payload=None,token=None):
            connection=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=5)
            headers={"X-StructAgent-Token":server.token if token is None else token,"Origin":server.url,"Content-Type":"application/json"}
            connection.request(method,path,None if payload is None else json.dumps(payload).encode(),headers)
            response=connection.getresponse();code=response.status;data=response.read();connection.close()
            return code,data
        try:
            self.assertEqual(request("/api/input-form",token="bad")[0],403)
            code,data=request("/api/input-form");self.assertEqual(code,200)
            self.assertEqual(json.loads(data),floor_input_form())
            self.assertEqual(request("/full-input.js")[0],200)
            code,data=request("/api/jobs","POST",self.payload);self.assertEqual(code,202)
            self.service.thread.join(20)
            code,data=request("/api/jobs/"+json.loads(data)["id"])
            self.assertEqual(code,200);self.assertTrue(json.loads(data)["snapshot"]["success"])
        finally:
            server.shutdown();server.server_close();worker.join(5)


if __name__=="__main__":unittest.main()
