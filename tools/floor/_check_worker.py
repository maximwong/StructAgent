"""Recheck supplied sections; never call the legacy design/selection entry points."""

from contextlib import redirect_stdout
import json
import math
from pathlib import Path
import sys


def check(raw):
    from engine import capacity, check_input
    from legacy_core import area, flexure, layout, shear, validate

    p = raw['input']
    check_input(p)
    validate(p)
    m, g = p['materials'], p['geometry']
    checks, heights = [], {}

    def number(row, key, positive=False, integer=False):
        value = row[key]
        if (type(value) not in (int, float) or not math.isfinite(value)
                or positive and value <= 0 or integer and value != int(value)):
            raise ValueError('Invalid check input field: ' + key)
        return int(value) if integer else value

    def close(a, b):
        if isinstance(a, list) and isinstance(b, list):
            return len(a) == len(b) and all(close(x, y) for x, y in zip(a, b))
        return type(a) in (int, float) and type(b) in (int, float) and math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-7)

    def record(member, index, rule, label, actual, relation, limit, unit, source):
        tolerance = 1e-7 + 1e-8 * max(abs(actual), abs(limit))
        passed = (actual + tolerance >= limit if relation == '>=' else
                  actual <= limit + tolerance if relation == '<=' else abs(actual-limit) <= tolerance)
        checks.append(dict(id=f'{member}.{index}.{rule}', member=member, section=index,
                           label=label, actual=actual, relation=relation, limit=limit,
                           unit=unit, passed=passed, source=source))

    for member, count in [('slab', 6), ('secondary', 4), ('main', 4)]:
        rows = raw[member]
        if not isinstance(rows, list) or len(rows) != count:
            raise ValueError('Incomplete section set: ' + member)
        heights[member] = []
        for i, row in enumerate(rows):
            s = p[member]
            d = number(row, 'diameter', True)
            moment = number(row, 'M_kNm')
            if member == 'slab':
                spacing = number(row, 'spacing', True)
                steel = area(d)*1000/spacing
                h0, b, bf, top = s['h_mm']-s['cover_mm']-d/2, 1000, 1000, False
                record(member, i, 'spacing_min', '板筋最小间距', spacing, '>=', 70, 'mm', 'legacy_core.slab_design')
                record(member, i, 'spacing_max', '板筋最大间距', spacing, '<=', 200 if s['h_mm'] <= 150 else min(1.5*s['h_mm'],250), 'mm', 'legacy_core.slab_design')
            else:
                n = number(row, 'count', True, True)
                if type(row['top']) is not bool:
                    raise ValueError('Section top must be boolean.')
                top = i in (1, 3)
                record(member, i, 'face', '受拉钢筋位置一致性', int(row['top'] == top), '=', 1, '', 'legacy_core.run')
                lay = layout(s['b_mm'], s['h_mm'], s['cover_mm'], s['stirrup_diameter_mm'], d, n,
                             top, s['extra_top_mm'], p['detailing']['aggregate_mm'], p['detailing']['maximum_rows'])
                record(member, i, 'layout', '实配钢筋净距与排布', int(lay is not None), '=', 1, '', 'legacy_core.layout')
                if lay is None:
                    continue
                record(member, i, 'centres', '已存钢筋坐标与排数一致性', int(close(row['centres'],lay['centres']) and close(row['rows'],lay['rows'])), '=', 1, '', 'legacy_core.layout')
                steel, h0, b = n*area(d), lay['h0'], s['b_mm']
                if top:
                    bf = b
                elif member == 'secondary':
                    span = number(raw['spans'], 'secondary_edge_mm' if i < 2 else 'secondary_inner_mm', True)
                    bf = min(span/3, g['secondary_spacing_mm'])
                else:
                    spans = raw['spans']['main_m']
                    if len(spans) != 3 or any(type(x) not in (int,float) or not math.isfinite(x) or x <= 0 for x in spans):
                        raise ValueError('Invalid main analysis spans.')
                    bf = min(min(spans)*1000/3, g['secondary_axis_spans_mm'][0])
                if not top and p['slab']['h_mm']/h0 < .1:
                    bf = min(bf, b+12*p['slab']['h_mm'])
                if not top:
                    end = g[member+'_bearing_mm']-s['cover_mm']-s['stirrup_diameter_mm']-d/2
                    support = p['main']['b_mm'] if member == 'secondary' else g['column_width_mm']
                    record(member, i, 'end_fit', '正筋端部直段容纳', 10*d, '<=', min(end,support-s['cover_mm']), 'mm', 'legacy_core.beam_design')
            if not 0 < h0 < s['h_mm']:
                record(member, i, 'height', '有效高度有效性', 0, '=', 1, '', 'legacy_core.flexure')
                continue
            heights[member].append(h0)
            bf = max(b, bf)
            fy = m['slab_fy_MPa'] if member == 'slab' else m['beam_fy_MPa']
            xi_limit = m['xi_elastic_limit'] if member == 'main' else m['xi_plastic_limit']
            trial = dict(As_provided=steel, h0=h0, bf=bf)
            x, mu = capacity(trial, p, member)
            record(member, i, 'area_cache', '已存实配面积一致性', number(row,'As_provided',True), '=', steel, 'mm²', 'legacy_core.area')
            record(member, i, 'height_cache', '已存有效高度一致性', number(row,'h0',True), '=', h0, 'mm', 'legacy_core.layout/slab_design')
            record(member, i, 'flange_cache', '已存翼缘宽度一致性', number(row,'bf',True), '=', bf, 'mm', 'legacy_core.beam_design')
            record(member, i, 'capacity_cache', '已存实配承载力一致性', number(row,'Mu_kNm'), '=', mu, 'kN·m', 'engine.capacity')
            record(member, i, 'flexure', '实配受弯承载力', mu, '>=', abs(moment), 'kN·m', 'engine.capacity')
            record(member, i, 'xi', '实配相对受压区高度', x/h0, '<=', xi_limit, '', 'legacy_core.provided_x')
            # Zero demand gives the same existing minimum-steel rule without selecting bars.
            minimum = flexure(0,b,s['h_mm'],h0,m['fc_MPa'],fy,m['ft_MPa'],m['alpha1'],bf,p['slab']['h_mm'] if not top else 0)['As_min']
            record(member, i, 'minimum', '最小配筋面积', steel, '>=', minimum, 'mm²', 'legacy_core.flexure')

    for member, count in [('secondary',4), ('main',3)]:
        rows = raw[member+'_shear']
        if not isinstance(rows,list) or len(rows) != count:
            raise ValueError('Incomplete shear section set: ' + member)
        if len(heights[member]) != 4:
            record(member, 0, 'shear_geometry', '抗剪复核所需截面排布完整性', 0, '=', 1, '', 'legacy_core.layout')
            continue
        h0 = min(heights[member])
        for i, row in enumerate(rows):
            v = number(row,'V_kN')
            if v < 0:
                raise ValueError('Shear demand must be nonnegative.')
            s = p[member]
            record(member, i, 'stirrup_match', '箍筋直径与肢数一致性', int(number(row,'diameter',True)==s['stirrup_diameter_mm'] and number(row,'legs',True,True)==s['stirrup_legs']), '=', 1, '', 'legacy_core.shear')
            try:
                limits = shear(p,member,'check',v,h0)
            except ValueError:
                record(member, i, 'shear_domain', '截面抗剪上限及适用范围', 0, '=', 1, '', 'legacy_core.shear')
                continue
            spacing = number(row,'spacing',True)
            record(member, i, 'shear_height_cache', '抗剪有效高度一致性', number(row,'h0',True), '=', h0, 'mm', 'legacy_core.shear')
            record(member, i, 'stirrup_min', '箍筋间距下限', spacing, '>=', 50, 'mm', 'legacy_core.shear')
            for name, limit in [('strength',limits['s_strength_mm']),('ratio',limits['s_rho_mm']),('code',limits['s_code_mm']),('input',s['max_stirrup_spacing_mm'])]:
                if limit is not None:
                    record(member, i, 'stirrup_'+name, '箍筋间距约束：'+name, spacing, '<=', limit, 'mm', 'legacy_core.shear')
    failed = sum(not item['passed'] for item in checks)
    return dict(status='FAIL' if failed else 'PASS', checks=checks,
                summary=dict(total=len(checks),passed=len(checks)-failed,failed=failed))


def main():
    for stream in (sys.stdin,sys.stdout,sys.stderr):
        stream.reconfigure(encoding='utf-8')
    sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'legacy'/'rc_floor'))
    try:
        raw=json.load(sys.stdin)
        with redirect_stdout(sys.stderr):
            result=check(raw)
        message=dict(protocol=1,success=True,result=result)
    except (ValueError,KeyError,TypeError,IndexError,OverflowError,ZeroDivisionError) as exc:
        message=dict(protocol=1,success=False,error=dict(code='check_input_invalid',message='无法完整复核设计数据（'+type(exc).__name__+'），禁止继续出图。'))
    except Exception:
        message=dict(protocol=1,success=False,error=dict(code='check_execution_error',message='独立校核执行失败，禁止继续出图。'))
    sys.stdout.write(json.dumps(message,ensure_ascii=False,allow_nan=False))


if __name__ == '__main__':
    main()
