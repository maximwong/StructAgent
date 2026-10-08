"""Read-only legacy provenance verification, then independent reaction analysis."""
from copy import deepcopy
from itertools import product
import math

from core.validation import make_validator, validate_json
from legacy.rc_floor.input_validation import validate_engineering_inputs
from .schemas import EXPLICIT_MODEL
from .reaction_input import validate_parameters, validate_positions
from .reaction_calculation import rational as F, beam_reactions, wall_weight, display

_MODEL = make_validator(EXPLICIT_MODEL)


def _close(actual, expected):
    if type(actual) not in (int,float) or not math.isfinite(actual) or not math.isclose(actual,float(expected),rel_tol=1e-8,abs_tol=1e-8):
        raise ValueError("Legacy span/load/reaction/segment provenance differs from effective input.")


def legacy_loads(model):
    """Independent transcription of legacy load-path contract, not a design call."""
    validate_json(model,_MODEL)
    validate_engineering_inputs(model)
    g,l,s,sec,main = (model[k] for k in ('geometry','loads','slab','secondary','main'))
    h,space = F(s['h_mm']),F(g['secondary_spacing_mm'])
    slab = (h*F(l['concrete_kN_m3'])+F(l['finish_mm'])*F(l['finish_kN_m3'])+F(l['plaster_mm'])*F(l['plaster_kN_m3']))/1000
    self_sec = F(sec['b_mm'])*(F(sec['h_mm'])-h)*F(l['concrete_kN_m3'])/1000000
    plaster_sec = 2*(F(sec['h_mm'])-h)*F(l['plaster_mm'])*F(l['plaster_kN_m3'])/1000000
    sec_g = (slab*space/1000+self_sec+plaster_sec)*F(l['gamma_g'])
    sec_q = F(l['live_kN_m2'])*space/1000*F(l['gamma_q'])
    trib = F(g['secondary_axis_spans_mm'][0])/1000
    self_main = (F(main['b_mm'])/1000*F(l['concrete_kN_m3'])+2*F(l['plaster_mm'])/1000*F(l['plaster_kN_m3']))*(F(main['h_mm'])-h)/1000
    G = sec_g*trib+self_main*F(l['gamma_g'])*space/1000
    Q = sec_q*trib
    spans=[]
    for i,ax in enumerate(g['main_axis_spans_mm']):
        net = F(ax)-F(g['wall_axis_to_inner_face_mm'])-F(g['column_width_mm'])/2
        spans.append(min(net+F(g['main_bearing_mm'])/2+F(g['column_width_mm'])/2,
                         F(1.025)*net+F(g['column_width_mm'])/2)/1000 if i in (0,2) else F(ax)/1000)
    return spans,G,Q


def case_points(spans,G,Q,pattern):
    points=[];x=F(0)
    for length,on in zip(spans,pattern):
        points.extend([(x+length/3,G+int(on)*Q),(x+2*length/3,G+int(on)*Q)])
        x+=length
    return points


def verified_baseline(design):
    raw=design.result['legacy_result'];model=design.result['effective_input']
    spans,G,Q=legacy_loads(model)
    if len(raw['spans']['main_m'])!=3 or len(raw['envelope']['spans'])!=3:
        raise ValueError('Three calculation spans required.')
    for actual,expected in zip(raw['spans']['main_m'],spans): _close(actual,expected)
    for actual,expected in zip(raw['envelope']['spans'],spans): _close(actual,expected)
    _close(raw['loads']['G_kN'],G);_close(raw['loads']['Q_kN'],Q)
    cases=raw['envelope']['cases']
    patterns=[''.join(map(str,p)) for p in product((0,1),repeat=3)]
    if len(cases)!=8 or {c['pattern'] for c in cases}!=set(patterns):
        raise ValueError('All eight unique legacy patterns required.')
    by_pattern={c['pattern']:c for c in cases};verified=[]
    for pattern in patterns:
        old=by_pattern[pattern];points=case_points(spans,G,Q,pattern)
        exact=beam_reactions(spans,points)
        if len(old['reactions'])!=4 or len(old['segments'])!=9:
            raise ValueError('Incomplete legacy response.')
        for a,e in zip(old['reactions'],exact['reactions']): _close(a,e)
        _close(old['equilibrium_error'],0)
        boundaries=[F(0)]
        for length in spans:
            boundaries.extend([boundaries[-1]+length/3,boundaries[-1]+2*length/3,boundaries[-1]+length])
        def moment(x):
            return sum(r*(x-a) for a,r in zip(exact['support_x_m'],exact['reactions']) if a<=x)-sum(p*(x-a) for a,p in points if a<=x)
        for seg,a,b in zip(old['segments'],boundaries,boundaries[1:]):
            _close(seg['x0'],a);_close(seg['x1'],b)
            _close(seg['m0'],moment(a));_close(seg['m1'],moment(b))
            middle=(a+b)/2
            shear=sum(r for x,r in zip(exact['support_x_m'],exact['reactions']) if x<middle)-sum(p for x,p in points if x<middle)
            _close(seg['v'],shear)
        verified.append((pattern,points,exact))
    return spans,G,Q,verified


class FloorReactionAdapter:
    def __init__(self,design_store):
        self.design_store=design_store

    def analyze(self,parameters,*,project_id,walls=False):
        validate_parameters(parameters,walls=walls)
        design=self.design_store.load(parameters['design_result_ref'],project_id=project_id)
        spans,G,Q,baseline=verified_baseline(design)
        validate_positions(parameters,spans)
        wall_results=[];udls=[]
        for wall in parameters.get('walls',[]):
            weight=wall_weight(wall,design.result['effective_input']['loads']['gamma_g'])
            wall_results.append({'wall_id':wall['wall_id'],'source':deepcopy(wall['source']),**weight})
            # Recover exact rational, never route rounded display numbers into analysis.
            from fractions import Fraction
            udls.append((F(wall['start_mm'])/1000,F(wall['end_mm'])/1000,Fraction(weight['design_q_kN_m']['exact'])))
        increment=beam_reactions(spans,udls=udls)
        cases=[];exact_totals=[]
        for pattern,points,base in baseline:
            total=beam_reactions(spans,points,udls)
            if any(t!=b+w for t,b,w in zip(total['reactions'],base['reactions'],increment['reactions'])):
                raise ArithmeticError('Load superposition failed.')
            exact_totals.append(total['reactions'])
            cases.append({'pattern':pattern,'baseline_reactions_kN':[display(x) for x in base['reactions']],
                          'wall_increment_reactions_kN':[display(x) for x in increment['reactions']],
                          'total_reactions_kN':[display(x) for x in total['reactions']],
                          'end_moments_kN_m':[[display(x) for x in pair] for pair in total['end_moments']],
                          'force_residual_kN':display(total['force_residual']),
                          'moment_residual_kN_m':display(total['moment_residual'])})
        controls=[]
        for j,support in enumerate(parameters['beam_binding']['support_ids']):
            vals=[row[j] for row in exact_totals];lo,hi=min(vals),max(vals)
            controls.append({'support_id':support,'minimum_kN':display(lo),'maximum_kN':display(hi),
                             'minimum_patterns':[c['pattern'] for c,v in zip(cases,vals) if v==lo],
                             'maximum_patterns':[c['pattern'] for c,v in zip(cases,vals) if v==hi]})
        return {'status':'MODEL_ANALYZED','input':deepcopy(parameters),
                'source_design_sha256':design.metadata['legacy_result_sha256'],
                'spans_m':[display(x) for x in spans],
                'support_coordinates_mm':[display(x*1000) for x in increment['support_x_m']],
                'legacy_factored_G_kN':display(G),'legacy_factored_Q_kN':display(Q),
                'walls':wall_results,'cases':cases,'controls':controls,
                'column_input_ready':False,'floor_design_recheck_required':walls,
                'support_contact_review_required':any(x<0 for row in exact_totals for x in row),
                'coverage':{'model':'constant_EI_bilateral_no_settlement',
                            'combination_policy':'inherited_legacy_eight_patterns_not_full_code_combinations',
                            'wall_distribution':'total_weight_uniform_over_declared_interval',
                            'not_checked':['whole_floor_transfer','column_design_actions','floor_capacity_after_wall',
                                           'wall_stiffness','opening_local_transfer','compression_only_support_contact']}}
