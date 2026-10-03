"""Explicitly authorised bounded redesign; CAD is enabled only with --cad."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.parameter_parser import ParseResult
from agent.state import AgentState
from core import ToolRegistry
from tools.floor.plugin import register_floor_revision_workflow


class ExplicitRevisionParser:
    """Application-owned structured request; no unvalidated LLM text or inferred limits."""
    def __init__(self, parameters):self.parameters=deepcopy(parameters)

    def parse(self, text, *, project_id, profile_name=None):
        return ParseResult('ready',envelope=dict(project_id=project_id,tool='design_floor_with_revisions',
            context=dict(unit_system='SI',design_code='GB'),parameters=deepcopy(self.parameters)))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file',type=Path,required=True,help='完整初始参数、授权尺寸候选、轮数与时间预算JSON。')
    parser.add_argument('--project-id',default='CSU-REVISION-001')
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1]/'data/projects')
    parser.add_argument('--cad',action='store_true',help='最终PASS后生成一次真实CAD；需AutoCAD空闲。')
    args=parser.parse_args()
    try:
        parameters=json.loads(args.request_file.read_text(encoding='utf-8-sig'))
        registry=ToolRegistry();workflow=register_floor_revision_workflow(registry,args.output_root)
        if args.cad:
            controller=AgentController(registry,ExplicitRevisionParser(parameters),AgentState(args.output_root/'agent'),[workflow])
            result=controller.run('显式受限重设计请求',project_id=args.project_id)
        else:
            result=registry.get('design_floor_with_revisions').execute(dict(project_id=args.project_id,
                tool='design_floor_with_revisions',context=dict(unit_system='SI',design_code='GB'),parameters=parameters)).to_dict()
    except (OSError,ValueError,KeyError):
        result=dict(success=False,status='error',errors=[dict(code='setup_failed',message='请求文件或初始化失败。')])
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
