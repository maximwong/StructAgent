"""Independently check a saved floor design; this command never starts CAD or an LLM."""

import argparse
import json
from pathlib import Path
import sys
from core import ToolRegistry
from tools.floor.check_tool import FloorCheckTool
from tools.floor.design_store import FloorDesignStore


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--design-result-ref',required=True)
    parser.add_argument('--project-id',required=True)
    parser.add_argument('--output-root',type=Path,default=Path(__file__).resolve().parents[1]/'data/projects')
    args=parser.parse_args()
    registry=ToolRegistry();registry.register(FloorCheckTool(FloorDesignStore(args.output_root/'designs')))
    result=registry.get('check_floor_design').execute({'project_id':args.project_id,'tool':'check_floor_design',
        'context':{'unit_system':'SI','design_code':'GB'},'parameters':{'design_result_ref':args.design_result_ref}})
    print(json.dumps(result.to_dict(),ensure_ascii=False,indent=2,allow_nan=False))
    return 0 if result.success else 1


if __name__=='__main__':raise SystemExit(main())
