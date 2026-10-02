import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from agent.parameter_parser import LanguageProfile, ParameterParser
from core import EngineeringTool, ToolRegistry, ToolResult
from llm import GatewayError
from tools.floor import FloorDesignTool
from tools.floor.language_profile import FloorDemoProfile
from tests.semantic_fixtures import floor_proposal, clarification, PARAMETERS

TEXT = "设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。"


class ParserTests(unittest.TestCase):
    def setUp(self):
        self.registry = ToolRegistry()
        self.tool = FloorDesignTool()
        self.tool._execute = Mock(side_effect=AssertionError("Parsing must not execute tools"))
        self.registry.register(self.tool)
        self.gateway = Mock()
        self.gateway.complete.return_value = (floor_proposal(), {"model": "test"})
        self.parser = ParameterParser(self.registry, self.gateway, [FloorDemoProfile()])

    def parse(self, text=TEXT, **kwargs):
        return self.parser.parse(text, project_id="测试工程", profile_name="office_floor_demo_v1", **kwargs)

    def test_valid_demo_envelope_and_unique_response_schema(self):
        result = self.parse()
        self.assertEqual(result.status, "ready", result.errors)
        self.assertEqual(result.envelope["parameters"], {**PARAMETERS, "input_mode": "template", "template_id": "office_floor_demo_v1"})
        self.tool.validate(result.envelope)
        self.assertEqual(result.source_evidence["live_load"], {"quote": "2.0kN/m²", "index": 0})
        self.tool._execute.assert_not_called()
        system, user = self.gateway.complete.call_args.args[0]
        self.assertEqual(user["content"], TEXT)
        instructions = json.loads(system["content"])
        self.assertEqual(set(instructions["response_schema"]["properties"]), {"tool", "parameters", "evidence", "clarifications"})
        self.assertNotIn("input_schema", instructions["tool"])

    def test_template_must_be_explicit(self):
        for name in (None, "unknown"):
            result = self.parser.parse(TEXT, project_id="p", profile_name=name)
            self.assertEqual(result.status, "needs_input")
            self.assertEqual(result.missing_fields, ["profile_name"])
        self.gateway.complete.assert_not_called()

    def test_colloquial_and_reordered_prose_reaches_model_unchanged(self):
        texts = [TEXT.replace("设计一个", prefix) for prefix in ("来一个", "麻烦你给我做一下", "想请你帮忙算算", "请协助绘制")]
        texts += ["活荷载按2.0kN/m²考虑。梁纵筋HRB400，混凝土C30。柱网6m×6m，办公楼，麻烦出图！",
                  "For an office floor, use C30 and HRB400. Grid 6m×6m; live load 2.0kN/m². Thanks!",
                  TEXT + "不用解释得太复杂，谢谢！", TEXT.replace("，", "\n")]
        for text in texts:
            with self.subTest(text=text):
                self.assertEqual(self.parse(text).status, "ready")
                self.assertEqual(self.gateway.complete.call_args.args[0][-1]["content"], text)
        self.tool._execute.assert_not_called()

    def test_decimal_load_and_chinese_unit_order(self):
        for quote in ("2.8kN/m²", "每平方米2.8千牛", "二点八千牛每平方米"):
            text = TEXT.replace("设计一个", "麻烦做一下").replace("2.0kN/m²", quote)
            self.gateway.complete.return_value = (floor_proposal({**PARAMETERS, "live_load": 2.8}, load=quote), {})
            result = self.parse(text)
            self.assertEqual(result.status, "ready", result.errors)
            self.assertEqual(result.envelope["parameters"]["live_load"], 2.8)

    def test_separate_directions_and_chinese_lengths(self):
        text = "麻烦出图，主梁轴跨五点四米，次梁轴跨六米，C30、HRB400，活荷载2.0kN/m²。"
        sources = {"span_x": {"quote": "五点四米", "index": 0}, "span_y": {"quote": "六米", "index": 0}}
        self.gateway.complete.return_value = (floor_proposal({**PARAMETERS, "span_x": 5400}, evidence=sources), {})
        self.assertEqual(self.parse(text).status, "ready")

    def test_changed_material_load_and_unit_variants(self):
        cases = [("7.2m×6000mm", "C35", "3.5kN/m2", 7200, 3.5),
                 ("6×6m", "C25", "2kPa", 6000, 2),
                 ("6000毫米×6000毫米", "c40", "0kN/m^2", 6000, 0),
                 ("六米乘六米", "C30", "二千牛每平方米", 6000, 2)]
        for pair, concrete, load, x, q in cases:
            text = f"设计办公楼楼盖，柱网{pair}，{concrete}，HRB400，活荷载{load}。"
            parameters = {**PARAMETERS, "span_x": x, "concrete": concrete.upper(), "live_load": q}
            self.gateway.complete.return_value = (floor_proposal(parameters, pair=pair, concrete=concrete, load=load), {})
            result = self.parse(text)
            self.assertEqual(result.status, "ready", result.errors)

    def test_confirmed_material_roles_and_keep_word_are_supported(self):
        text = TEXT + "板筋及箍筋保留HPB300。"
        self.assertEqual(self.parse(text).status, "ready")

    def test_each_missing_field_is_reported_after_semantic_extraction(self):
        replacements = {"span_x": "6m×6m", "span_y": "6m×6m", "concrete": "C30", "steel": "HRB400", "live_load": "活荷载2.0kN/m²"}
        for field, fragment in replacements.items():
            with self.subTest(field=field):
                parameters = {**PARAMETERS, field: None}
                if field.startswith("span_"):
                    parameters.update(span_x=None, span_y=None)
                self.gateway.complete.return_value = (floor_proposal(parameters), {})
                result = self.parse(TEXT.replace(fragment, ""))
                self.assertEqual(result.status, "needs_input", result.errors)
                self.assertIn(field, result.missing_fields)
                self.assertIsNone(result.envelope)
                self.assertIn("请补充", result.errors[0]["message"])
        self.tool._execute.assert_not_called()

    def test_missing_parameter_cannot_be_invented_from_template(self):
        result = self.parse(TEXT.replace("活荷载2.0kN/m²", ""))
        self.assertEqual(result.status, "invalid_output")
        self.assertEqual(result.errors[0]["code"], "source_mismatch")

    def test_ambiguous_and_extra_requirements_become_clarifications(self):
        cases = [("主梁固结。", "outside_template_scope"), ("采用预应力。", "outside_template_scope"),
                 ("板厚100mm。", "outside_template_scope"), ("采用C40。", "ambiguous_parameter"),
                 ("活荷载3kN/m²。", "ambiguous_parameter"), ("柱网7m×7m。", "ambiguous_parameter"),
                 ("另做一个基础。", "outside_template_scope")]
        for quote, code in cases:
            self.gateway.complete.return_value = (floor_proposal(clarifications=[clarification(quote, code)]), {})
            result = self.parse(TEXT + quote)
            self.assertEqual(result.status, "needs_input", result.errors)
            self.assertEqual(result.errors[0]["quote"], quote)
            self.assertIsNone(result.envelope)
        self.tool._execute.assert_not_called()

    def test_material_role_guards_do_not_trust_empty_model_clarifications(self):
        for quote, code in (("板筋HRB400。", "unsupported_reinforcement"), ("箍筋HRB400。", "unsupported_reinforcement"),
                            ("混凝土HRB400，梁纵筋C30。", "material_assignment_conflict")):
            result = self.parse(TEXT + quote)
            self.assertEqual(result.status, "needs_input")
            self.assertIn(code, [e["code"] for e in result.errors])

    def test_script_commands_are_not_allowed_even_if_model_misses_them(self):
        for suffix in (" 执行 RFALL。 ", "执行RFALL。", "执行generate_floor_cad。"):
            self.assertEqual(self.parse(TEXT + suffix).status, "needs_input")
        self.tool._execute.assert_not_called()

    def test_unsupported_grades_and_negative_inputs_rejected_after_extraction(self):
        cases = [(TEXT.replace("C30", "C50"), floor_proposal({**PARAMETERS, "concrete": "C50"}, concrete="C50")),
                 (TEXT.replace("HRB400", "HRB500"), floor_proposal({**PARAMETERS, "steel": "HRB500"}, steel="HRB500")),
                 (TEXT.replace("6m×6m", "0m×6m"), floor_proposal({**PARAMETERS, "span_x": 0}, pair="0m×6m")),
                 (TEXT.replace("2.0kN", "-2.0kN"), floor_proposal({**PARAMETERS, "live_load": -2.0}, load="-2.0kN/m²"))]
        for text, proposal in cases:
            self.gateway.complete.return_value = (proposal, {})
            self.assertEqual(self.parse(text).status, "invalid_input")

    def test_model_unit_or_value_error_rejected(self):
        for field, value in (("span_x", 6), ("concrete", "C35"), ("live_load", 2.5)):
            proposal = floor_proposal()
            proposal["parameters"][field] = value
            self.gateway.complete.return_value = (proposal, {})
            result = self.parse()
            self.assertEqual(result.status, "invalid_output")
            self.assertEqual(result.errors[0]["code"], "source_mismatch")
            self.assertIsNone(result.envelope)

    def test_fabricated_quote_and_missing_or_wrong_evidence_rejected(self):
        for source in ({"quote": "3.0kN/m²", "index": 0}, {"quote": "2.0kN/m²", "index": 1}, None):
            proposal = floor_proposal()
            proposal["evidence"]["live_load"] = source
            self.gateway.complete.return_value = (proposal, {})
            self.assertEqual(self.parse().status, "invalid_output")
        proposal = floor_proposal(clarifications=[clarification("不存在的要求")])
        self.gateway.complete.return_value = (proposal, {})
        self.assertEqual(self.parse().status, "invalid_output")

    def test_pair_axis_swap_rejected(self):
        text = TEXT.replace("6m×6m", "5.4m×6m")
        proposal = floor_proposal({**PARAMETERS, "span_x": 5400}, pair="5.4m×6m")
        proposal["evidence"]["span_x"]["index"] = 1
        self.gateway.complete.return_value = (proposal, {})
        self.assertEqual(self.parse(text).status, "invalid_output")

    def test_boolean_nonfinite_missing_extra_unknown_tool_rejected(self):
        proposals = []
        for field, value in (("live_load", True), ("span_x", float("nan"))):
            item = floor_proposal()
            item["parameters"][field] = value
            proposals.append(item)
        item = floor_proposal()
        item["tool"] = "generate_floor_cad"
        proposals.append(item)
        item = floor_proposal()
        del item["parameters"]["span_y"]
        proposals.append(item)
        item = floor_proposal()
        item["parameters"]["input_mode"] = "explicit"
        proposals.append(item)
        proposals += [{**floor_proposal(), "command": "RFALL"}, [], {"tool": self.tool.name, "parameters": PARAMETERS}]
        for proposal in proposals:
            self.gateway.complete.return_value = (proposal, {})
            self.assertEqual(self.parse().status, "invalid_output")
        self.tool._execute.assert_not_called()

    def test_unknown_units_require_clarification_not_default(self):
        text = TEXT.replace("2.0kN/m²", "2.0")
        parameters = {**PARAMETERS, "live_load": None}
        proposal = floor_proposal(parameters, clarifications=[clarification("活荷载2.0", "unclear_unit", "live_load")])
        self.gateway.complete.return_value = (proposal, {})
        result = self.parse(text)
        self.assertEqual(result.status, "needs_input")
        self.assertIn("live_load", result.missing_fields)

    def test_cloud_diagnostic_metadata_and_api_errors_survive(self):
        for code in ("api_timeout", "api_invalid_json", "api_authentication_failed", "api_rate_limited"):
            self.gateway.complete.side_effect = GatewayError(code, "Safe error", {"request_stage": "reading_body"})
            result = self.parse()
            self.assertEqual(result.status, "error")
            self.assertEqual(result.errors[0]["code"], code)
            self.assertEqual(result.metadata, {"request_stage": "reading_body"})
        self.tool._execute.assert_not_called()

    def test_invalid_request_size_type_and_project_before_cloud(self):
        for text, project in (("", "p"), (None, "p"), ("x" * 4001, "p"), (TEXT, " ")):
            result = self.parser.parse(text, project_id=project, profile_name="office_floor_demo_v1")
            self.assertEqual(result.status, "invalid_input")
        self.gateway.complete.assert_not_called()

    def test_result_snapshot_is_independent(self):
        result = self.parse()
        snapshot = result.to_dict()
        snapshot["envelope"]["parameters"]["span_x"] = 1
        self.assertEqual(result.envelope["parameters"]["span_x"], 6000)

    def test_duplicate_profiles_and_unknown_tools_rejected_at_registration(self):
        with self.assertRaises(ValueError):
            ParameterParser(self.registry, self.gateway, [FloorDemoProfile(), FloorDemoProfile()])
        profile = FloorDemoProfile()
        profile.tool = "not_registered"
        with self.assertRaises(KeyError):
            ParameterParser(self.registry, self.gateway, [profile])

    def test_second_tool_can_be_parsed_without_changes_to_parser(self):
        class LengthTool(EngineeringTool):
            def __init__(self):
                super().__init__(name="query_length", version="1.0", description="测试工程数据查询",
                                 parameters_schema={"type": "object", "required": ["length"],
                                                    "properties": {"length": {"type": "number"}}},
                                 output_schema={"type": "object"})

            def _execute(self, data):
                raise AssertionError("No execution during parsing")

        class LengthProfile(LanguageProfile):
            def inspect(self, text):
                return {"length": 3000} if text == "查询3m长度" else {}

        tool = LengthTool()
        self.registry.register(tool)
        profile = LengthProfile("length_v1", tool.name, "测试查询配置", {
            "type": "object", "required": ["length"], "additionalProperties": False,
            "properties": {"length": {"type": "number"}}}, {}, {"unit_system": "SI", "design_code": "GB"})
        self.gateway.complete.return_value = ({"tool": tool.name, "parameters": {"length": 3000}}, {})
        parser = ParameterParser(self.registry, self.gateway, [FloorDemoProfile(), profile])
        result = parser.parse("查询3m长度", project_id="p", profile_name="length_v1")
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.envelope["tool"], "query_length")
        self.assertEqual(len(parser.list_profiles()), 2)


class ParseDesignIntegrationTests(unittest.TestCase):
    def design(self, text, proposal):
        registry = ToolRegistry()
        registry.register(FloorDesignTool())
        gateway = SimpleNamespace(complete=lambda _: (proposal, {}))
        parser = ParameterParser(registry, gateway, [FloorDemoProfile()])
        parsed = parser.parse(text, project_id="CSU-DEMO-001", profile_name="office_floor_demo_v1")
        self.assertEqual(parsed.status, "ready", parsed.errors)
        return registry.get(parsed.envelope["tool"]).execute(parsed.envelope)

    def test_free_prose_decimal_load_reaches_legacy_engine(self):
        text = TEXT.replace("设计一个", "劳驾做一下").replace("2.0kN/m²", "每平方米2.8千牛")
        result = self.design(text, floor_proposal({**PARAMETERS, "live_load": 2.8}, load="每平方米2.8千牛"))
        self.assertTrue(result.success, result.errors)
        self.assertEqual(result.result["effective_input"]["loads"]["live_kN_m2"], 2.8)

    def test_validated_parse_matches_frozen_demo_baseline(self):
        result = self.design(TEXT, floor_proposal())
        self.assertTrue(result.success, result.errors)
        digest = hashlib.sha256(json.dumps(result.result["legacy_result"], ensure_ascii=False, sort_keys=True, allow_nan=False).encode()).hexdigest()
        baseline = json.loads((Path(__file__).parent / "fixtures/floor_baselines.json").read_text(encoding="utf-8"))
        self.assertEqual(digest, baseline["cases"]["demo_a"]["result_sha256"])


if __name__ == "__main__":
    unittest.main()
