"""Isolated evaluation of existing supplied reinforcement, with a finite deadline."""

import json
import math
import os
from pathlib import Path
import subprocess
import sys

from core.validation import ensure_json, make_validator, validate_json
from .schemas import EXPLICIT_MODEL, object_schema

ITEM = object_schema({
    'id': {'type':'string'}, 'member': {'enum':['slab','secondary','main']},
    'section': {'type':'integer','minimum':0}, 'label': {'type':'string'},
    'actual': {'type':'number'}, 'relation': {'enum':['>=','<=','=']},
    'limit': {'type':'number'}, 'unit': {'type':'string'},
    'passed': {'type':'boolean'}, 'source': {'type':'string'},
})
REPORT = object_schema({'status':{'enum':['PASS','FAIL']},
    'checks':{'type':'array','items':ITEM,'minItems':1},
    'summary':object_schema({k:{'type':'integer','minimum':0} for k in ('total','passed','failed')})})
COVERAGE = {
    'recomputed':['板/梁实配受弯承载力','最小配筋与实配受压区','梁钢筋排布与正筋端部容纳','板筋间距','梁抗剪与箍筋间距约束'],
    'demand_source':'已保存设计的弯矩、剪力和计算跨度；本工具不独立重算荷载与内力分析。',
    'not_checked':['荷载组合与内力分析','分布筋、吊筋与附加箍筋','锚固搭接、材料包络与下料长度','裂缝挠度、抗震、耐久性、防火和节点碰撞'],
}


class FloorCheckError(ValueError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def validate_report(result):
    """Validate both shape and verdict; shared by execution and saved-result readers."""
    validate_json(result, make_validator(REPORT))
    checks = result['checks']
    for item in checks:
        actual, limit = item['actual'], item['limit']
        tolerance = 1e-7 + 1e-8 * max(abs(actual), abs(limit))
        passed = (actual + tolerance >= limit if item['relation'] == '>=' else
                  actual <= limit + tolerance if item['relation'] == '<=' else abs(actual-limit) <= tolerance)
        if item['passed'] != passed:
            raise ValueError('Check verdict disagrees with the recorded comparison.')
    failed = sum(not item['passed'] for item in checks)
    if (result['status'] != ('FAIL' if failed else 'PASS')
            or result['summary'] != dict(total=len(checks), passed=len(checks)-failed, failed=failed)
            or len({item['id'] for item in checks}) != len(checks)):
        raise ValueError('Inconsistent check report.')


class FloorCheckAdapter:
    def __init__(self,timeout_seconds=30):
        if type(timeout_seconds) not in (int,float) or not math.isfinite(timeout_seconds) or timeout_seconds<=0:
            raise ValueError('Check timeout must be positive and finite.')
        self.timeout=timeout_seconds

    def check(self,design):
        raw=design.result['legacy_result']
        validate_json(raw['input'],make_validator(EXPLICIT_MODEL))
        # CAD and consumers use normalized rows as well as the legacy snapshot.
        comparisons=[(design.result['slab']['sections'],raw['slab']),
                     (design.result['secondary_beam']['sections'],raw['secondary']),
                     (design.result['main_beam']['sections'],raw['main']),
                     (design.result['secondary_beam']['shear_checks'],raw['secondary_shear']),
                     (design.result['main_beam']['shear_checks'],raw['main_shear'])]
        if any(left!=right for left,right in comparisons):
            raise FloorCheckError('check_input_inconsistent','标准设计截面与旧程序结果不一致，禁止继续出图。')
        worker=Path(__file__).with_name('_check_worker.py')
        try:
            process=subprocess.run([sys.executable,'-I',str(worker)],input=json.dumps(raw,ensure_ascii=False,allow_nan=False),
                capture_output=True,text=True,encoding='utf-8',cwd=str(worker.parents[2]),timeout=self.timeout,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except subprocess.TimeoutExpired:
            raise FloorCheckError('check_timeout','独立校核超时，禁止继续出图。') from None
        except (OSError,UnicodeError):
            raise FloorCheckError('check_start_failed','无法启动或读取独立校核进程。') from None
        try:
            if process.returncode!=0:raise ValueError('Worker failed.')
            data=json.loads(process.stdout);ensure_json(data)
            if type(data.get('protocol')) is not int or data['protocol']!=1 or type(data.get('success')) is not bool:
                raise ValueError('Invalid worker protocol.')
            if not data['success']:
                error=data['error']
                if error['code'] not in ('check_input_invalid','check_execution_error') or not isinstance(error['message'],str):
                    raise ValueError('Invalid worker error.')
                raise FloorCheckError(error['code'],error['message'])
            result=data['result'];validate_report(result)
            return result
        except FloorCheckError:
            raise
        except (ValueError,KeyError,TypeError,AttributeError,ArithmeticError):
            raise FloorCheckError('check_protocol_error','独立校核返回格式无效，禁止继续出图。') from None
