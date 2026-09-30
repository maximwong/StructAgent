"""RC floor coursework calculator. Python 3.8+, standard library only.

Run: python calculate.py example.json --out generated
All section units: N, mm, MPa; actions: kN, m. No silent unit conversion.
"""
import argparse
import csv
import json
import math
from pathlib import Path
from beam_solver import envelope, moment, exact_envelope_points
from input_validation import validate_engineering_inputs


def area(d):
    return math.pi*d*d/4


def validate(p):
    validate_engineering_inputs(p)
    def finite(v, path=''):
        if isinstance(v, dict):
            for k, x in v.items(): finite(x, path+'.'+k)
        elif isinstance(v, list):
            for x in v: finite(x, path)
        elif isinstance(v, (float, int)) and (not math.isfinite(v) or v < 0):
            raise ValueError('参数必须是非负有限数: '+path)
    finite(p)
    g, s, m, l, mat = (p[k] for k in ('geometry','slab','main','loads','materials'))
    for k in ('fc_MPa','ft_MPa','alpha1','slab_fy_MPa','beam_fy_MPa','stirrup_fy_MPa'):
        if mat[k] <= 0: raise ValueError(k+' 必须大于0')
    if l['gamma_g'] <= 0 or l['gamma_q'] <= 0 or l['concrete_kN_m3'] <= 0:
        raise ValueError('荷载分项系数及混凝土重度必须大于0')
    if len(g['main_axis_spans_mm']) != 3:
        raise ValueError('当前楼盖模型限定主梁三跨，不能用五跨结果冒充其他跨数')
    if not 5 <= len(g['secondary_axis_spans_mm']) <= 12:
        raise ValueError('次梁系数法仅支持5至12跨规则连续梁')
    for arr in ('secondary_axis_spans_mm','main_axis_spans_mm'):
        spans = g[arr]
        if min(spans) <= 0 or max(spans)/min(spans) > 1.1:
            raise ValueError(arr+' 必须正值，跨度相差不超过10%')
    # Load path uses one repeating secondary span and exactly two beam loads per main span.
    if max(g['secondary_axis_spans_mm'])-min(g['secondary_axis_spans_mm']) > 1e-6:
        raise ValueError('荷载传递近似限定次梁等轴跨；不等跨需支座反力传递模型')
    spacing=g['secondary_spacing_mm']
    if spacing <= 0 or any(abs(x-3*spacing)>1e-6 for x in g['main_axis_spans_mm']):
        raise ValueError('每个主梁轴跨必须恰为3倍次梁间距（两处三分点荷载）')
    if min(g['secondary_axis_spans_mm'])/spacing < 3:
        raise ValueError('本工具按原文长短跨比>=3限定单向板；其他板形需另建模型')
    if not 0 < s['arch_factor'] <= 1:
        raise ValueError('arch_factor 必须在(0,1]，是否允许折减需人工校核')
    if s['h_mm'] <= 2*s['cover_mm']+max(s['main_diameters_mm']):
        raise ValueError('板厚/保护层/钢筋直径不相容')
    if m['support_moment'] not in ('axis','face'):
        raise ValueError('support_moment 只能为axis或face')
    if not 0 < m['hanger_angle_deg'] < 90:
        raise ValueError('吊筋角度必须在0到90度之间')
    if p['detailing']['maximum_rows'] not in (1,2):
        raise ValueError('只支持单排或双排钢筋')
    if min(s['main_diameters_mm']+s['spacings_mm']+p['detailing']['beam_diameters_mm']) <= 0:
        raise ValueError('候选直径、间距必须大于0')
    if not 0 < p['detailing']['slab_support_extension_ratio'] <= 0.5:
        raise ValueError('负筋示意伸出比例须在0到0.5之间')
    if not 0 < p['detailing']['slab_wall_extension_ratio'] <= 0.5:
        raise ValueError('墙边构造筋示意伸出比例须在0到0.5之间')
    for k in ('secondary','main'):
        b=p[k]
        if b['stirrup_legs'] != 2: raise ValueError('当前图形只支持双肢箍')
        if b['h_mm'] <= s['h_mm'] or b['cover_mm'] <= 0 or b['b_mm'] <= 2*(b['cover_mm']+b['stirrup_diameter_mm']):
            raise ValueError(k+' 截面/保护层无效')
        if b['h_mm'] <= 150 or b['h_mm'] > 800:
            raise ValueError('当前梁高适用范围150<h<=800mm')
        if b['stirrup_diameter_mm'] < 6 or b['max_stirrup_spacing_mm'] < 50:
            raise ValueError(k+' 箍筋直径/间距无效')
    if g['column_width_mm'] >= min(g['main_axis_spans_mm']) or g['column_width_mm'] <= 0:
        raise ValueError('柱宽无效')


def flexure(M, b, h, h0, fc, fy, ft, alpha=1.0, bf=None, hf=0.0):
    """Singly reinforced rectangular / first and second type T sections.
    Solve compression-block resultant and moment, then apply minimum steel
    to web b*h. Material strength parameters are explicitly supplied by user.
    """
    M=abs(M)*1e6
    bf=max(b, bf or b)
    def result(x):
        if x <= hf and bf > b:
            return alpha*fc*bf*x, alpha*fc*bf*x*(h0-x/2)
        f1=alpha*fc*b*x
        f2=alpha*fc*(bf-b)*hf
        return f1+f2, f1*(h0-x/2)+f2*(h0-hf/2)
    if not 0 < h0 < h: raise ValueError('无效有效高度')
    if result(h0)[1] < M: raise ValueError('受弯需求超过单筋截面理论上限，请加大截面')
    lo,hi=0.0,h0
    for _ in range(70):
        mid=(lo+hi)/2
        if result(mid)[1] < M: lo=mid
        else: hi=mid
    x=(lo+hi)/2
    as_calc=result(x)[0]/fy
    as_min=max(0.002,0.45*ft/fy)*b*h
    return dict(As_calc=as_calc, As_min=as_min, As_required=max(as_calc,as_min),
                x=x, xi=x/h0, h0=h0, bf=bf,
                section_type=('矩形' if bf==b else ('第一类T形' if x<=hf else '第二类T形')))


def provided_x(As, fy, fc, alpha, b, bf, hf):
    force=As*fy
    if bf>b and force<=alpha*fc*bf*hf:
        return force/(alpha*fc*bf)
    return (force/(alpha*fc)-(bf-b)*hf)/b


def layout(b, h, cover, stirrup, d, n, top, extra, aggregate, max_rows):
    """Actual circle centres measured from beam bottom-left; centroid gives h0."""
    clear=max(25.0 if not top else 30.0, (1 if not top else 1.5)*d,1.25*aggregate)
    available=b-2*(cover+stirrup)
    per=int((available+clear)//(d+clear))
    if per < 2 or n < 2 or n > per*max_rows: return None
    rows=math.ceil(n/per)
    counts=[n] if rows==1 else [math.ceil(n/2),n//2]
    if max(counts)>per: return None
    vertical=max(25.0,d,1.25*aggregate)
    centres=[]
    for r,count in enumerate(counts):
        a=cover+stirrup+d/2+(extra if top else 0)+r*(d+vertical)
        y=h-a if top else a
        for i in range(count):
            x=(b/2 if count==1 else cover+stirrup+d/2+i*(available-d)/(count-1))
            centres.append([x,y])
    centroid=sum(y for _,y in centres)/n
    h0=centroid if top else h-centroid
    if h0 <= h/2: return None
    return dict(rows=counts,centres=centres,h0=h0,clear_mm=clear)


def beam_design(p, member, name, M, top=False, bf=None):
    s=p[member]; mat=p['materials'];det=p['detailing'];opts=[]
    limit=mat['xi_plastic_limit'] if member=='secondary' else mat['xi_elastic_limit']
    for d in det['beam_diameters_mm']:
        # Positive bars use the bounded straight anchorage detail. Select a
        # smaller diameter/more bars when a large diameter cannot fit.
        support=p['main']['b_mm'] if member=='secondary' else p['geometry']['column_width_mm']
        end=p['geometry'][member+'_bearing_mm']-s['cover_mm']-s['stirrup_diameter_mm']-d/2
        if not top and 10*d > min(end,support-s['cover_mm']):
            continue
        for n in range(2,13):
            lay=layout(s['b_mm'],s['h_mm'],s['cover_mm'],s['stirrup_diameter_mm'],d,n,
                       top,s['extra_top_mm'],det['aggregate_mm'],det['maximum_rows'])
            if not lay: continue
            try:
                effective_bf=bf
                if bf and p['slab']['h_mm']/lay['h0']<0.1:
                    effective_bf=min(bf,s['b_mm']+12*p['slab']['h_mm'])
                calc=flexure(M,s['b_mm'],s['h_mm'],lay['h0'],mat['fc_MPa'],mat['beam_fy_MPa'],
                             mat['ft_MPa'],mat['alpha1'],effective_bf if not top else None,p['slab']['h_mm'] if not top else 0)
            except ValueError: continue
            xi_provided=provided_x(n*area(d),mat['beam_fy_MPa'],mat['fc_MPa'],mat['alpha1'],
                                  s['b_mm'],calc['bf'],p['slab']['h_mm'] if not top else 0)/lay['h0']
            if max(calc['xi'],xi_provided)>limit or n*area(d)+1e-7<calc['As_required']: continue
            opts.append(dict(name=name,M_kNm=M,diameter=d,count=n,As_provided=n*area(d),
                             top=top,xi_provided=xi_provided,**lay,**{k:v for k,v in calc.items() if k!='h0'}))
    if not opts: raise ValueError(member+'/'+name+'：两排以内没有满足面积、净距及xi限制的配筋，请增大截面')
    # Mild congestion penalty; chosen option still satisfies all explicit checks.
    return min(opts,key=lambda x:(x['As_provided']*(1+0.02*max(0,x['count']-4)+0.05*(len(x['rows'])-1)),x['count']))


def slab_design(p, name, M):
    s=p['slab'];mat=p['materials'];opts=[]
    for d in s['main_diameters_mm']:
        c=flexure(M,1000,s['h_mm'],s['h_mm']-s['cover_mm']-d/2,
                  mat['fc_MPa'],mat['slab_fy_MPa'],mat['ft_MPa'],mat['alpha1'])
        for spacing in s['spacings_mm']:
            maxs=200 if s['h_mm']<=150 else min(1.5*s['h_mm'],250)
            xi_provided=area(d)*1000/spacing*mat['slab_fy_MPa']/(mat['alpha1']*mat['fc_MPa']*1000*c['h0'])
            if 70<=spacing<=maxs and area(d)*1000/spacing>=c['As_required'] and max(c['xi'],xi_provided)<=mat['xi_plastic_limit']:
                opts.append(dict(name=name,M_kNm=M,diameter=d,spacing=spacing,
                                 As_provided=area(d)*1000/spacing,xi_provided=xi_provided,**c))
    if not opts: raise ValueError(name+' 板候选配筋不足')
    return min(opts,key=lambda x:(x['As_provided'],-x['spacing']))


def shear(p, member, name, V, h0):
    s=p[member];m=p['materials'];b=s['b_mm'];h=s['h_mm']
    vmax=0.25*m['fc_MPa']*b*h0/1000
    if V>vmax: raise ValueError(name+' 超过0.25fc*b*h0截面抗剪上限')
    # Thin / deep-web beta_h variants intentionally outside this bounded model.
    if h0/b>4: raise ValueError('腹板高宽比超出本工具简化抗剪适用范围')
    vc=0.7*m['ft_MPa']*b*h0/1000
    asv=s['stirrup_legs']*area(s['stirrup_diameter_mm'])
    sf=math.inf if V<=vc else 1.25*m['stirrup_fy_MPa']*asv*h0/((V-vc)*1000)
    rho_min=0.24*m['ft_MPa']/m['stirrup_fy_MPa']
    sr=asv/(rho_min*b)
    cap=(150 if h<=300 else 200 if h<=500 else 250) if V>vc else (200 if h<=300 else 300 if h<=500 else 350)
    spacing=math.floor(min(sf,sr,cap,s['max_stirrup_spacing_mm'])/10)*10
    if spacing<50: raise ValueError(name+' 所需箍筋间距小于50mm，应调整截面或箍筋')
    capacity=vc+1.25*m['stirrup_fy_MPa']*asv*h0/spacing/1000
    return dict(name=name,V_kN=V,h0=h0,Vmax_kN=vmax,Vc_kN=vc,
                Asv=asv,spacing=spacing,diameter=s['stirrup_diameter_mm'],legs=s['stirrup_legs'],
                s_strength_mm=None if not math.isfinite(sf) else sf,s_rho_mm=sr,s_code_mm=cap,
                capacity_kN=min(vmax,capacity),rho_min=rho_min)


def run(p):
    validate(p)
    geo=p['geometry'];l=p['loads'];s=p['slab'];sec=p['secondary'];main=p['main'];m=p['materials']
    h=s['h_mm'];space=geo['secondary_spacing_mm'];wall=geo['wall_axis_to_inner_face_mm']
    slab_gk=(h*l['concrete_kN_m3']+l['finish_mm']*l['finish_kN_m3']+l['plaster_mm']*l['plaster_kN_m3'])/1000
    slab_g=slab_gk*l['gamma_g'];slab_q=l['live_kN_m2']*l['gamma_q']
    sec_self=sec['b_mm']/1000*(sec['h_mm']-h)/1000*l['concrete_kN_m3']
    sec_plaster=2*(sec['h_mm']-h)/1000*l['plaster_mm']/1000*l['plaster_kN_m3']
    sec_gk=slab_gk*space/1000+sec_self+sec_plaster
    sec_g=sec_gk*l['gamma_g'];sec_q=l['live_kN_m2']*space/1000*l['gamma_q']
    trib=geo['secondary_axis_spans_mm'][0]/1000
    main_self=(main['b_mm']/1000*l['concrete_kN_m3']+2*l['plaster_mm']/1000*l['plaster_kN_m3'])*(main['h_mm']-h)/1000
    G=sec_g*trib+main_self*l['gamma_g']*space/1000
    Q=sec_q*trib
    slab_ln=space-sec['b_mm'];slab_edge_net=space-wall-sec['b_mm']/2
    slab_edge=min(slab_edge_net+h/2,slab_edge_net+geo['slab_bearing_mm']/2)
    sec_ln=geo['secondary_axis_spans_mm'][0]-main['b_mm']
    sec_edge_net=geo['secondary_axis_spans_mm'][0]-wall-main['b_mm']/2
    sec_edge=min(sec_edge_net+geo['secondary_bearing_mm']/2,1.025*sec_edge_net)
    main_ls=[]
    for i,ax in enumerate(geo['main_axis_spans_mm']):
        if i in (0,2):
            net=ax-wall-geo['column_width_mm']/2
            main_ls.append(min(net+geo['main_bearing_mm']/2+geo['column_width_mm']/2,
                               1.025*net+geo['column_width_mm']/2)/1000)
        else: main_ls.append(ax/1000)
    if min(slab_ln,slab_edge,sec_ln,sec_edge,*main_ls)<=0: raise ValueError('净跨或计算跨度非正')
    for a,b in ((slab_ln,slab_edge),(sec_ln,sec_edge)):
        if max(a,b)/min(a,b)>1.1: raise ValueError('计算跨度相差超过10%，不能使用当前系数法')
    if slab_g<=0 or slab_q/slab_g>3 or sec_q/sec_g>3:
        raise ValueError('q/g>3或恒载无效，不满足本算例塑性系数法限制')
    labels=['边跨中','第一内支座','中间跨中','中间支座']
    # Coefficient numerators/denominators are defined once here and carried on
    # the result rows, so the report equations, coefficient diagram and moment
    # table all read the same stored values instead of restating them.
    slab_coeff=[(1,11),(-1,11),(1,16),(-1,14)]
    slab_spans=[slab_edge,slab_edge,slab_ln,slab_ln]
    slab_ms=[num/den*(slab_g+slab_q)*(le/1000)**2 for (num,den),le in zip(slab_coeff,slab_spans)]
    slab_rows=[slab_design(p,n,v) for n,v in zip(labels,slab_ms)]
    slab_rows.extend(slab_design(p,n+'（中带内拱折减）',v*s['arch_factor']) for n,v in zip(labels[2:],slab_ms[2:]))
    for row,(num,den),le in zip(slab_rows,slab_coeff,slab_spans):
        row.update(alpha_num=num,alpha_den=den,alpha=num/den,span_mm=le)
    dist_required=max(0.0015*1000*h,0.15*max(x['As_provided'] for x in slab_rows))
    dd=s['distribution_diameter_mm']
    if dd<6: raise ValueError('分布筋直径不得小于6mm')
    ds=math.floor(min(250,area(dd)*1000/dist_required)/10)*10
    if ds<70: raise ValueError('分布筋间距不足，请增大直径')
    sec_coeff=[(1,11),(-1,11),(1,16),(-1,14)]
    sec_spans=[sec_edge,sec_edge,sec_ln,sec_ln]
    sec_ms=[num/den*(sec_g+sec_q)*(le/1000)**2 for (num,den),le in zip(sec_coeff,sec_spans)]
    sec_bfs=[min(le/3,space) for le in (sec_edge,sec_ln)]
    sec_rows=[beam_design(p,'secondary',n,v,i in (1,3),sec_bfs[0 if i<2 else 1]) for i,(n,v) in enumerate(zip(labels,sec_ms))]
    for row,(num,den),le in zip(sec_rows,sec_coeff,sec_spans):
        row.update(alpha_num=num,alpha_den=den,alpha=num/den,span_mm=le)
    sec_h0=min(x['h0'] for x in sec_rows)
    # Shear coefficients follow the same single-point definition as the slab
    # moments: numerators/denominators live here and travel with each row so the
    # report table, the figure and the equations never restate them.
    sec_vcoeff=[(45,100),(6,10),(55,100),(55,100)]
    sec_vspans=[sec_edge_net,sec_edge_net,sec_ln,sec_ln]
    sec_vs=[num/den*(sec_g+sec_q)*le/1000 for (num,den),le in zip(sec_vcoeff,sec_vspans)]
    sec_shear=[shear(p,'secondary',n,v,sec_h0) for n,v in zip(('边支座','第一内支座左','第一内支座右','中间支座'),sec_vs)]
    for row,(num,den),le in zip(sec_shear,sec_vcoeff,sec_vspans):
        row.update(beta_num=num,beta_den=den,beta=num/den,span_mm=le)
    env=envelope(main_ls,G,Q)
    env['points']=exact_envelope_points(env['cases'])
    positive=[]; negative=[];start=0
    for i,le in enumerate(main_ls):
        xx=(start+le/3,start+2*le/3)
        vals=[moment(c,x) for c in env['cases'] for x in xx]
        positive.append(max(0,max(vals)));negative.append(min(0,min(vals)))
        start+=le
    supp=[]
    for x in (main_ls[0],sum(main_ls[:2])):
        xs=[x] if main['support_moment']=='axis' else [x-geo['column_width_mm']/2000,x+geo['column_width_mm']/2000]
        supp.append(min(moment(c,t) for c in env['cases'] for t in xs))
    main_bf=min(min(main_ls)*1000/3,trib*1000)
    main_rows=[beam_design(p,'main','边跨中',max(positive[0],positive[2]),False,main_bf),
               beam_design(p,'main','中间支座',min(supp),True),
               beam_design(p,'main','中间跨中正弯矩',positive[1],False,main_bf),
               beam_design(p,'main','中间跨中负弯矩',negative[1],True)]
    main_h0=min(x['h0'] for x in main_rows)
    main_vs=[max(abs(c['segments'][idx]['v']) for c in env['cases']) for idx in (0,2,3)]
    main_shear=[shear(p,'main',n,v,main_h0) for n,v in zip(('边支座','第一内支座左','第一内支座右'),main_vs)]
    F=(sec_g+sec_q)*trib # excludes main self-weight
    hang_req=F*1000/(2*m['beam_fy_MPa']*math.sin(math.radians(main['hanger_angle_deg'])))
    hd=main['hanger_diameter_mm']
    if hd<=0: raise ValueError('吊筋直径无效')
    hn=max(2,math.ceil(hang_req/area(hd)))
    if hn%2: hn+=1
    warnings=[
      '本包为课程计算与CAD初稿工具；使用原文的单一荷载组合，未作现行规范全项审查。',
      '板/次梁系数法：规则连续跨、q/g<=3、计算跨度差<=10%；次梁至少5跨。内拱折减仅列为中带候选，平面绘图采用未折减配筋。',
      '主梁模型：三个等轴跨，跨内两个三分点集中荷载，支座只约束竖向位移；恒载全布，活载逐跨开关，共8种。',
      '荷载传递沿用教材g次梁×6m近似，不以次梁各支座反力逐个传递；主梁自重折为跨内集中力。输出反力仅对应模型荷载，不是整层柱设计反力。',
      '统一采用矩形压应力块；T形翼缘按l0/3、梁间距取小，hf/h0<0.1时再限制b+12hf；不进行双筋截面或受压钢筋计算。',
      '梁上部采用控制支座配筋沿梁通长的保守示意，底筋按各跨配筋；未优化截断、弯起、接头、锚固与材料抵抗图。',
      '图中梁纵筋通长线仅表达配筋位置，绝非单根超长钢筋下料长度。钢筋表列截面面积，不输出未经校核的下料总量。',
      '箍筋按最不利剪力统一间距，不将均布箍筋标成抗震加密区；附加吊筋需另核对与附加箍筋的协同及节点容纳。',
      '需人工核对：梁柱刚度比、墙支承与局压、抗震、耐久性/防火保护层、裂缝、挠度、振动、荷载组合、锚固搭接、节点碰撞。',
      '主梁负筋extra_top_mm为与次梁交叉留出的附加距离；实际节点钢筋上下次序和各排形心应再复核。'
    ]
    return dict(project=p['project'],basis=p['basis'],input=p,
      loads=dict(slab_gk=slab_gk,slab_g=slab_g,slab_q=slab_q,secondary_self=sec_self,
      secondary_plaster=sec_plaster,secondary_gk=sec_gk,secondary_g=sec_g,secondary_q=sec_q,
      main_self_line_kN_m=main_self,G_kN=G,Q_kN=Q,slab_q_g=slab_q/slab_g,secondary_q_g=sec_q/sec_g),
      spans=dict(slab_edge_mm=slab_edge,slab_inner_mm=slab_ln,secondary_edge_mm=sec_edge,
      secondary_inner_mm=sec_ln,main_m=main_ls),slab=slab_rows,
      distribution=dict(diameter=dd,spacing=ds,As_required=dist_required,As_provided=area(dd)*1000/ds),
      secondary=sec_rows,secondary_shear=sec_shear,main=main_rows,main_shear=main_shear,
      hanger=dict(F_kN=F,As_required=hang_req,diameter=hd,count=hn,As_provided=hn*area(hd),angle=main['hanger_angle_deg']),
      envelope=env,warnings=warnings)

