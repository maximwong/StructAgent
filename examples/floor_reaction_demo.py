"""Explicit anonymous 6x6 floor demo, then one local reaction workflow.

This command explicitly selects the office_floor_demo_v1 teaching template.
It creates a new design reference, never draws or modifies a prior design.
"""
import argparse
import json
from pathlib import Path
import sys

from core.json_data import loads_json
from core.persistence import write_json
from core.plugin_base import PluginContext
from core.plugin_loader import load_plugins
from .floor_reactions import run_request


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case',required=True,choices=('baseline','wall-opening','wall-cross-support'))
    parser.add_argument('--output-root',type=Path,required=True)
    args=parser.parse_args(argv)
    root=Path(__file__).resolve().parents[1]
    catalog=load_plugins(root/'plugins',PluginContext(args.output_root))
    design=catalog.registry.get('design_floor_system').execute({'project_id':'REACTION-DEMO','tool':'design_floor_system',
        'context':{'unit_system':'SI','design_code':'GB'},'parameters':{'input_mode':'template',
            'template_id':'office_floor_demo_v1','span_x':6000,'span_y':6000,'concrete':'C30','steel':'HRB400','live_load':2}})
    if design.success:
        envelope=loads_json((root/'demos'/('floor-reactions-'+args.case+'.json')).read_text(encoding='utf-8'))
        envelope['parameters']['design_result_ref']=design.metadata['design_result_ref']
        write_json(args.output_root/('request-'+design.metadata['design_result_ref']+'.json'),envelope,exclusive=True)
        result=run_request(envelope,args.output_root)
    else:
        result=design.to_dict()
    output=json.dumps(result,ensure_ascii=False,allow_nan=False,indent=2)+'\n'
    if hasattr(sys.stdout,'buffer'):sys.stdout.buffer.write(output.encode('utf-8'))
    else:sys.stdout.write(output)
    return 0 if result['success'] else 1


if __name__=='__main__':
    raise SystemExit(main())
