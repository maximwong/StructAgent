"""Generate a calculation book from an existing reference or an explicit model."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.parameter_parser import ParseResult
from agent.state import AgentState
from core import ToolRegistry
from tools.floor.plugin import register_floor_report_workflow


class ReportRequestParser:
    def __init__(self,parameters,revision=False):
        self.parameters, self.revision = deepcopy(parameters), revision

    def parse(self,text,*,project_id,profile_name=None):
        return ParseResult('ready',envelope=dict(project_id=project_id,
            tool='design_floor_with_revisions' if self.revision else 'design_floor_system',
            context=dict(unit_system='SI',design_code='GB'),parameters=deepcopy(self.parameters)))


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    source=parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--design-ref',help='现有设计的不可变引用；不重新设计。')
    source.add_argument('--request-file',type=Path,help='普通显式设计参数或受限重设计请求JSON。')
    source.add_argument('--case',choices=('demo_a','sample1','changed'),help='显式选择仓库中的完整样例，不调用云模型。')
    parser.add_argument('--revision',action='store_true',help='请求文件为带授权候选的受限重设计请求。')
    parser.add_argument('--revision-id',help='现有引用关联的完整PASS调整记录编号。')
    parser.add_argument('--project-id',required=True,help='必须与现有引用的项目身份一致。')
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1]/'data/projects')
    parser.add_argument('--cad',action='store_true',help='请求工作流生成报告后再调用一次真实CAD。')
    args=parser.parse_args()
    if args.design_ref and (args.revision or args.cad):parser.error('已有引用模式不执行重设计或CAD。')
    if args.revision and not args.request_file:parser.error('--revision需要--request-file。')
    if args.revision_id and not args.design_ref:parser.error('--revision-id仅用于现有引用模式。')
    try:
        registry=ToolRegistry()
        workflow=register_floor_report_workflow(registry,args.output_root,revision=args.revision or bool(args.revision_id),cad=args.cad)
        if args.design_ref:
            parameters={'design_result_ref':args.design_ref}
            if args.revision_id:parameters['revision_id']=args.revision_id
            result=registry.get('generate_floor_report').execute(dict(project_id=args.project_id,tool='generate_floor_report',
                context=dict(unit_system='SI',design_code='GB'),parameters=parameters)).to_dict()
        else:
            if args.case:
                model=json.loads((Path(__file__).resolve().parents[1]/'legacy/rc_floor'/f'{args.case}.json').read_text(encoding='utf-8-sig'))
                parameters=dict(input_mode='explicit',model=model)
            else:
                parameters=json.loads(args.request_file.read_text(encoding='utf-8-sig'))
            controller=AgentController(registry,ReportRequestParser(parameters,args.revision),AgentState(args.output_root/'agent'),[workflow])
            result=controller.run('显式计算书请求',project_id=args.project_id)
    except (OSError,ValueError,KeyError):
        result=dict(success=False,status='error',errors=[dict(code='report_setup_failed',message='请求或工具初始化失败。')])
    print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result['success'] else 1


if __name__=='__main__':raise SystemExit(main())
