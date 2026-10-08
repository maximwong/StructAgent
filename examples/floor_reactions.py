"""Complete JSON/CLI reaction workflows; no cloud, CAD or column invocation."""
import argparse
import json
from pathlib import Path
import sys

from agent.controller import AgentController
from agent.local_parser import LocalEnvelopeParser
from agent.state import AgentState
from core.json_data import loads_json
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins


def run_request(envelope,output_root):
    if type(envelope)!=dict or envelope.get('tool') not in ('extract_floor_reactions','analyze_floor_wall_reactions'):
        raise ValueError('Reaction Envelope required.')
    catalog=load_plugins(Path(__file__).resolve().parents[1]/'plugins',PluginContext(Path(output_root)))
    workflow=next(w for w in catalog.workflows if w.name==envelope['tool'])
    return AgentController(catalog.registry,LocalEnvelopeParser(envelope,catalog.registry),
        AgentState(Path(output_root)/'reaction-agent'),[workflow]).run('完整本地反力请求',project_id=envelope.get('project_id'))


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--request-file',type=Path,required=True)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1]/'data/projects')
    args=parser.parse_args(argv)
    try:
        result=run_request(loads_json(args.request_file.read_text(encoding='utf-8-sig')),args.output_root)
    except Exception:
        result={'success':False,'status':'invalid_input','errors':[{'code':'reaction_request_failed','message':'反力请求文件或初始化失败。','path':[]}]}
    output=json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    if hasattr(sys.stdout,'buffer'): sys.stdout.buffer.write(output.encode('utf-8'))
    else: sys.stdout.write(output)
    return 0 if result['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
