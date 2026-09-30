"""Sample-1 teaching model, traceable calculations and bar geometry (N, mm, MPa)."""
import copy
import math
from pathlib import Path
import json
from legacy_core import run as legacy_run, area, provided_x, layout
from beam_solver import moment, beam
from input_validation import validate_engineering_inputs


def fmt(v, n=3):
    return f'{v:.{n}f}'.rstrip('0').rstrip('.') if isinstance(v,(int,float)) else str(v)


def coeff_label(x):
    """Signed fraction text read from the stored coefficient, never restated."""
    sign='' if x['alpha_num']>0 else '-'
    return sign+str(abs(x['alpha_num']))+'/'+str(x['alpha_den'])


def spec(x):
    return f"Φ{x['diameter']}@{x['spacing']}" if 'spacing' in x else f"{x['count']}Φ{x['diameter']}"


def capacity(x,p,member):
    mat=p['materials']; b=1000 if member=='slab' else p[member]['b_mm']
    fy=mat['slab_fy_MPa'] if member=='slab' else mat['beam_fy_MPa']
    hf=p['slab']['h_mm'] if x['bf']>b else 0
    xx=provided_x(x['As_provided'],fy,mat['fc_MPa'],mat['alpha1'],b,x['bf'],hf)
    if xx<=hf and x['bf']>b:
        mu=mat['alpha1']*mat['fc_MPa']*x['bf']*xx*(x['h0']-xx/2)
    else:
        mu=mat['alpha1']*mat['fc_MPa']*(b*xx*(x['h0']-xx/2)+(x['bf']-b)*hf*(x['h0']-hf/2))
    return xx,mu/1e6


def check_input(p):
    validate_engineering_inputs(p)
    if len(p['geometry']['secondary_axis_spans_mm'])!=5:
        raise ValueError('第一阶段固定次梁五跨、主梁三跨，改变跨数需第二阶段。')
    if p['report']['anchor_ribbed_factor']<40 or p['report']['anchor_plain_factor']<34:
        raise ValueError('本教学构造配置锚固系数下限：带肋40d、光圆34d；不能通过降低系数消除不足。')
    if p['report']['lap_factor']<1.6:
        raise ValueError('接头面积百分率按100%保守取值，搭接系数不得小于1.6。')
    if not 1/3 <= p['report']['top_extension_ratio'] <= .45:
        raise ValueError('次梁支座伸出比例限1/3至0.45。')
    for key in ['anchor_ribbed_factor','anchor_plain_factor','lap_factor','max_stock_mm','top_extension_ratio','stirrup_hook_tail_d','stirrup_bend_inner_d']:
        v=p['report'][key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
            raise ValueError('构造参数无效：'+key)
    if p['report']['stirrup_hook_tail_d']<10 or p['report']['stirrup_bend_inner_d']<4:
        raise ValueError('箍筋构造限值：平直段≥10d，弯曲内径≥4d。')
    if p['geometry']['slab_bearing_mm']<=2*p['slab']['cover_mm']:
        raise ValueError('板支承长度不足。')


class Chapter:
    def __init__(self,title): self.title=title; self.items=[]
    def text(self,s): self.items.append({'type':'text','text':s})
    def eq(self,label,formula,substitution,result,unit=''):
        self.items.append(dict(type='equation',label=label,formula=formula,substitution=substitution,result=result,unit=unit))
    def table(self,title,headers,rows): self.items.append(dict(type='table',title=title,headers=headers,rows=rows))
    def matrix(self,title,groups,rows): self.items.append(dict(type='matrix',title=title,groups=groups,rows=rows))
    def figure(self,key,caption): self.items.append(dict(type='figure',key=key,caption=caption))
    def sub(self,title): self.items.append(dict(type='heading',text=title))


def bar_schedule(r):
    p=r['input'];g=p['geometry'];opt=p['report'];bars=[];events=[]
    def add(mark,member,use,d,count,pieces,segments,notes='',shape='straight',position=None):
        total=sum(v for _,v in segments)
        if min(v for _,v in segments)<-1e-8 or total<=0: raise ValueError(mark+' 钢筋几何长度非正')
        if math.ceil(total/10)*10>opt['max_stock_mm']: raise ValueError(mark+' 单根取整长度超过设置原材长度，需专项接头方案')
        bars.append(dict(mark=mark,member=member,use=use,diameter=d,count=count,pieces=pieces,
                         segments=segments,length_mm=total,rounded_mm=math.ceil(total/10)*10,
                         notes=notes,shape=shape,position=position))
    # Slab: representative strip bars, not a floor-wide quantity take-off.
    h=p['slab']['h_mm'];cover=p['slab']['cover_mm'];space=g['secondary_spacing_mm'];bw=p['secondary']['b_mm']
    for i,x in enumerate(r['slab'][:4]):
        d=x['diameter'];hook=6.25*d
        if i in (0,2):
            net=space-bw if i==2 else space-g['wall_axis_to_inner_face_mm']-bw/2
            available=(g['slab_bearing_mm']-cover if i==0 else bw-cover)
            anch=max(5*d,bw/2 if i==2 else 5*d)
            if anch>available or anch>bw-cover: raise ValueError('板底筋支承内直段不足')
            seg=[('净跨',net),('左支座直段',anch),('右支座直段',max(5*d,bw/2)),('两端180度弯钩增加',2*hook)]
            shape='hook'
        else:
            ext=max(r['spans']['slab_inner_mm']/4,opt['anchor_plain_factor']*d)
            drop=max(0,h-2*cover-d)
            seg=[('左伸出',ext),('支座宽',bw),('右伸出',ext),('两端竖段',2*drop)]
            shape='u'
        add('B'+str(i+1),'slab',x['name'],d,1,1,seg,f"按{spec(x)}布置；长度为单根。弯折示意尺寸与加工弯曲调整需对应。",shape)
    dd=r['distribution']['diameter'];net=g['secondary_axis_spans_mm'][0]-p['main']['b_mm']
    add('B5','slab','分布钢筋',dd,1,1,[('净长',net),('两端5d直段',10*dd),('两端弯钩增加',12.5*dd)],spec(r['distribution']),'hook')
    for mark,ratio,use in [('B6',1/7,'墙边构造筋'),('B7',1/4,'墙角双向构造筋')]:
        d=8;ext=max(r['spans']['slab_inner_mm']*ratio,opt['anchor_plain_factor']*d)
        add(mark,'slab',use,d,1,1,[('伸入板内',ext),('墙内直段',g['slab_bearing_mm']-cover),('端部竖段',max(0,h-2*cover-d))],
            'Φ8@200；墙角两个方向分别布置。','l')
    for member,prefix in [('secondary','CL'),('main','ZL')]:
        s=p[member];N=5 if member=='secondary' else 3;ax=g[member+'_axis_spans_mm'];b_support=p['main']['b_mm'] if member=='secondary' else g['column_width_mm'];bearing=g[member+'_bearing_mm'];c=s['cover_mm'];sd=s['stirrup_diameter_mm']
        # All bottom bars extend into supports; never terminate in a span.
        for i in range(N):
            x=r[member][0 if i in (0,N-1) else 2];d=x['diameter']
            edge_shear=r[member+'_shear'][0]
            anch=(10 if edge_shear['V_kN']>edge_shear['Vc_kN'] else 5)*d
            need_internal=10 if any(v['V_kN']>v['Vc_kN'] for v in r[member+'_shear'][1:]) else 5
            internal=max(need_internal*d,b_support/2)
            if internal>b_support-c: raise ValueError(prefix+' 底筋在中间支座内直锚不足，需修改支座或设计弯锚。')
            end=bearing-c-sd-d/2
            if i in (0,N-1) and anch>end: raise ValueError(prefix+' 底筋墙端直锚不足，需修改支承。')
            net=ax[i]-(g['wall_axis_to_inner_face_mm'] if i==0 else b_support/2)-(g['wall_axis_to_inner_face_mm'] if i==N-1 else b_support/2)
            left=anch if i==0 else internal;right=anch if i==N-1 else internal
            add(f'{prefix}-D{i+1}',member,f'第{i+1}跨底筋',d,x['count'],1,[('净跨',net),('左锚入',left),('右锚入',right)],'不在跨内截断；中间支座未利用下部钢筋受压强度。')
        extents=[]
        for i in range(N-1):
            x=r[member][1 if member=='main' or i in (0,N-2) else 3];d=x['diameter'];la=max(opt['anchor_ribbed_factor']*d,.14*p['materials']['beam_fy_MPa']/p['materials']['ft_MPa']*d,200)
            lap=max(opt['lap_factor']*la,300)
            if member=='secondary':
                left=max((r['spans']['secondary_edge_mm'] if i==0 else r['spans']['secondary_inner_mm'])*opt['top_extension_ratio'],la)
                right=max((r['spans']['secondary_edge_mm'] if i==N-2 else r['spans']['secondary_inner_mm'])*opt['top_extension_ratio'],la)
                points=dict(method='系数法全组负筋统一伸出，不采用范例分组短筋',left_mm=left,right_mm=right,la_mm=la,lap_mm=lap)
            else:
                sx=sum(r['spans']['main_m'][:i+1]);limits=[sum(r['spans']['main_m'][:i]),sum(r['spans']['main_m'][:i+2])]
                # Every envelope segment is affine. Search all breakpoints, no sampling truncation.
                xx=sorted({t for seg in r['envelope']['segments'] for t in (seg['x0'],seg['x1'])})
                out=[]
                for sign,bound in [(-1,limits[0]),(1,limits[1])]:
                    physical_span=ax[i if sign<0 else i+1]
                    mapping=physical_span/(abs(sx-bound)*1000)
                    roots=[]
                    for case in r['envelope']['cases']:
                        for seg in case['segments']:
                            if abs(seg['v'])>1e-12:
                                z=seg['x0']-seg['m0']/seg['v']
                                if seg['x0']-1e-9<=z<=seg['x1']+1e-9:roots.append(z)
                    candidates=sorted(set(xx+roots+[bound]),key=lambda z:abs(z-sx))
                    zero=next((z for z in candidates if (z-sx)*sign>0 and (z-bound)*sign<=1e-8 and min(moment(case,z) for case in r['envelope']['cases'])>=-1e-6),None)
                    h0=x['h0'];ld=1.2*la+h0
                    if zero is None:
                        length=physical_span/2+lap/2-b_support/2
                        out.append((length,None,'相邻支座负筋在跨中搭接，按100%接头取1.6la'))
                    else:
                        zdist=abs(sx-zero)*1000*mapping-b_support/2
                        length=max(zdist+max(20*d,la),ld,la)
                        out.append((length,zdist,'包络零点外延max(20d,la)，并满足支座边缘外延1.2la+h0'))
                left,right=out[0][0],out[1][0]
                points=dict(method='全组钢筋截断；计算坐标按分跨比例映射至物理轴网',left_mm=left,right_mm=right,left_zero_mm=out[0][1],right_zero_mm=out[1][1],left_rule=out[0][2],right_rule=out[1][2],la_mm=la,lap_mm=lap,ld_mm=1.2*la+x['h0'])
            if left>=ax[i]-b_support or right>=ax[i+1]-b_support: raise ValueError(prefix+' 负筋伸出超出相邻跨，需专项连续配筋方案')
            extents.append((left,right,x,points))
            add(f'{prefix}-F{i+1}',member,f'第{i+1}内支座负筋',d,x['count'],1,[('左梁边伸出',left),('支座宽',b_support),('右梁边伸出',right)],points['method'],position=points)
        # Erection/negative span bars connect support groups; overlap is calculated explicitly.
        for i in range(N):
            if i==0 or i==N-1:
                d=12;n=2;la=max(opt['anchor_ribbed_factor']*d,.14*p['materials']['beam_fy_MPa']/p['materials']['ft_MPa']*d)
                straight=bearing-c-sd-d/2;vertical=max(0,la-straight)
                if vertical>s['h_mm']-2*(c+sd+d):raise ValueError(prefix+' 架立筋端部弯锚竖段放不下，请增加支承长度或梁高')
                extension=extents[0][0] if i==0 else extents[-1][1]
                clear=ax[i]-g['wall_axis_to_inner_face_mm']-b_support/2-extension
                add(f'{prefix}-J{i+1}',member,f'第{i+1}跨端部架立筋',d,n,1,[('至负筋端部净长',clear),('非受力搭接',150),('墙内直段',straight),('补足锚固竖段',vertical)],'带肋筋，按直段加竖段记录几何展开；90度弯曲调整另列加工复核。','l')
            else:
                left,right=extents[i-1][1],extents[i][0];gap=ax[i]-b_support-left-right
                if gap<=0:
                    required=max(extents[i-1][3]['lap_mm'],extents[i][3]['lap_mm'])
                    # axis and calculation span differ slightly; extend symmetrically for the real overlap.
                    if member=='main' and -gap<required:
                        extra=(required+gap)/2
                        for support,side in [(i-1,2),(i,0)]:
                            item=next(t for t in bars if t['mark']==f'{prefix}-F{support+1}')
                            name,v=item['segments'][side];item['segments'][side]=(name,v+extra)
                            item['length_mm']+=extra;item['rounded_mm']=math.ceil(item['length_mm']/10)*10
                            if item['rounded_mm']>opt['max_stock_mm']:raise ValueError('搭接调整后负筋取整长度超过原材长度')
                            item['position']['right_mm' if side==2 else 'left_mm']+=extra
                        gap=-required
                    events.append(dict(member=member,span=i+1,overlap_mm=-gap,required_mm=required,method='两侧支座钢筋直接搭接；不再重复配置跨中上筋',pass_check=(-gap>=required-1e-6)))
                    if -gap<required-1e-6:raise ValueError(prefix+' 相邻支座负筋搭接不足')
                else:
                    x=r['main'][3] if member=='main' else dict(diameter=12,count=2)
                    d=x['diameter'];n=x['count'];lap=150 if member=='secondary' else max(300,opt['lap_factor']*max(opt['anchor_ribbed_factor']*d,.14*p['materials']['beam_fy_MPa']/p['materials']['ft_MPa']*d))
                    add(f'{prefix}-J{i+1}',member,f'第{i+1}跨上部连接筋',d,n,1,[('两侧负筋间净长',gap),('左搭接',lap),('右搭接',lap)],'次梁为非受力架立搭接；主梁为受拉钢筋搭接。')
        # Stirrup centreline: rounded rectangle + two 135-degree arcs and straight tails.
        d=sd;B=s['b_mm']-2*c-d;H=s['h_mm']-2*c-d;rad=(max(opt['stirrup_bend_inner_d']*d, max(t['diameter'] for t in r[member]))+d)/2
        if min(B,H)<2*rad:raise ValueError(prefix+' 箍筋弯曲半径放不下')
        tail=max(opt['stirrup_hook_tail_d']*d,75)
        seg=[('中心线直段',2*(B+H)-8*rad),('四角圆弧',2*math.pi*rad),('两个135度弯钩弧长',1.5*math.pi*rad),('两端平直段',2*tail)]
        add(prefix+'-G',member,'封闭箍筋单根',d,1,1,seg,'按中心线理想圆弧展开。弯曲内径受纵筋直径控制；不沿用范例固定100或120mm增加值。','stirrup')
        rho=p['materials']['ft_MPa'];fyv=p['materials']['stirrup_fy_MPa']
        events.append(dict(member=member,method='搭接范围箍筋',spacing_mm=min(100,5*min(t['diameter'] for t in r[member])),diameter=d))
    return bars,events


def calculate(p):
    p=copy.deepcopy(p);check_input(p)
    if not p['report']['allow_arch']:p['slab']['arch_factor']=1.0
    r=legacy_run(p)
    r['warnings']=[
        '固定样例1教学模型；板及次梁按系数法，主梁按三跨三分点集中荷载弹性分析。',
        '单一指定荷载组合；沿用次梁线荷载乘分担跨度的教学荷载传递近似，不作为整层柱墙反力。',
        '配筋按组内同一直径自动选择；主梁负筋采用全组伸出与搭接方案，不复刻范例的混合直径分批截断。',
        '本工具校核承载力、相对受压区高度、排布、材料包络、搭接区域容纳及长度；不代替工程全项审查。',
        '仍需人工校核裂缝挠度、抗震、耐久性、防火、砌体局压、锚固区横向约束、节点三维碰撞及加工弯曲调整。'
    ]
    if area(8)*1000/200 < max(x['As_provided'] for x in r['slab'])/3:
        raise ValueError('默认Φ8@200板构造筋不足受力筋面积的1/3，本阶段需调整板截面或另定构造筋方案。')
    if p['main']['h_mm']<=p['secondary']['h_mm']:
        raise ValueError('本阶段主梁高度必须大于次梁高度。')
    for member in ['slab','secondary','main']:
        for x in r[member]:
            xx,mu=capacity(x,p,member);x.update(x_provided=xx,Mu_kNm=mu)
            if mu+1e-6<abs(x['M_kNm']):raise ValueError(member+' 实配承载力不足')
    # Additional stirrups suspend the reaction from the secondary beam.
    F=r['hanger']['F_kN'];sd=p['main']['stirrup_diameter_mm'];legs=p['main']['stirrup_legs'];fyv=p['materials']['stirrup_fy_MPa']
    n=math.ceil(F*1000/(legs*area(sd)*fyv));n=2*math.ceil(n/2)
    width=2*(p['main']['h_mm']-p['secondary']['h_mm'])+3*p['secondary']['b_mm']
    if width<=0:raise ValueError('主梁高度必须大于次梁高度，附加箍筋范围无效')
    spacing=math.floor(min(width/n,100)/10)*10
    if spacing<50:raise ValueError('附加箍筋间距小于50mm，请加大直径')
    r['suspension']=dict(F_kN=F,count=n,per_side=n//2,range_mm=width,spacing_mm=spacing,diameter=sd,capacity_kN=n*legs*area(sd)*fyv/1000)
    r['bars'],r['joint_checks']=bar_schedule(r)
    for event in r['joint_checks']:
        if event.get('member')=='main' and event.get('pass_check'):
            x=r['main'][1];s=p['main'];lay=layout(s['b_mm'],s['h_mm'],s['cover_mm'],s['stirrup_diameter_mm'],x['diameter'],2*x['count'],True,s['extra_top_mm'],p['detailing']['aggregate_mm'],p['detailing']['maximum_rows'])
            if not lay:raise ValueError('主梁中跨100%搭接的双倍钢筋无法在两排内排下，需增大梁宽或另定错开接头方案。')
            # At a lap, credit only one group, at the less favourable row.
            trial=copy.deepcopy(x);trial['h0']=min(y for _,y in lay['centres'])
            xx,mu=capacity(trial,p,'main')
            if xx/trial['h0']>p['materials']['xi_elastic_limit']:raise ValueError('主梁搭接区按不利内排钢筋验算超筋。')
            event.update(h0_mm=trial['h0'],capacity_kNm=mu,diameter=x['diameter'],physical_count=2*x['count'],rows=lay['rows'],centres=lay['centres'])
    r['support']=support_state(r)
    r['material_regions']=material_regions(r)
    from geometry import enrich
    enrich(r)
    r['chapters']=build_chapters(r)
    return r


def support_state(r):
    """Axis moment, governing shear and the V0*b_column/2 value at the first inner support."""
    g=r['input']['geometry'];cases=r['envelope']['cases'];axis_x=r['spans']['main_m'][0]
    axis=min(moment(c,axis_x) for c in cases)
    v0=max(abs(c['segments'][2]['v']) for c in cases)
    return dict(axis_kNm=axis,v0_kN=v0,b_mm=g['column_width_mm'],reduction_kNm=v0*g['column_width_mm']/2000,
                design_kNm=r['main'][1]['M_kNm'],mode=r['input']['main']['support_moment'])


def material_regions(r):
    """Conservative fully developed top-steel ranges, in analysis millimetres."""
    g=r['input']['geometry'];ax=g['main_axis_spans_mm'];ls=[x*1000 for x in r['spans']['main_m']]
    def to_calc(x):
        start=0;out=0
        for a,b in zip(ax,ls):
            if x<=start+a:return out+(x-start)/a*b
            start+=a;out+=b
        return out+(x-start)
    regions=[]
    for i in range(2):
        item=next(b for b in r['bars'] if b['mark']==f'ZL-F{i+1}');q=item['position'];center=sum(ax[:i+1]);half=g['column_width_mm']/2
        regions.append([to_calc(center-half-q['left_mm']+q['la_mm']),to_calc(center+half+q['right_mm']-q['la_mm']),r['main'][1]['Mu_kNm']])
    # Lap is >=1.6la for identical support groups. Their combined development
    # exceeds one full group throughout the lap; do not count twice the steel.
    if any(t.get('member')=='main' and t.get('pass_check') for t in r['joint_checks']):
        ev=next(t for t in r['joint_checks'] if t.get('member')=='main' and t.get('pass_check'))
        f1=next(b for b in r['bars'] if b['mark']=='ZL-F1')['position'];f2=next(b for b in r['bars'] if b['mark']=='ZL-F2')['position']
        half=g['column_width_mm']/2
        left=to_calc(sum(ax[:2])-half-f2['left_mm']);right=to_calc(ax[0]+half+f1['right_mm'])
        regions=[[regions[0][0],left,r['main'][1]['Mu_kNm']],[left,right,ev['capacity_kNm']],[right,regions[-1][1],r['main'][1]['Mu_kNm']]]
    elif regions[0][1]<regions[1][0]:
        regions.append([regions[0][1],regions[1][0],r['main'][3]['Mu_kNm']])
    # Envelope is piecewise affine. Check its breakpoints, material transitions
    # and column faces; axis sections inside columns are deliberately excluded.
    points={x['x']*1000 for x in r['envelope']['points']}
    points.update(x for a,b,_ in regions for x in [a,b])
    points.update(x+delta for a,b,_ in regions for x in [a,b] for delta in [-1e-4,1e-4])
    centers=[ls[0],sum(ls[:2])];half=g['column_width_mm']/2
    for center in centers:points.update([center-half,center+half])
    checks=[]
    for x in sorted(points):
        if x<0 or x>sum(ls) or any(abs(x-c)<half-1e-6 for c in centers):continue
        demand=max(0,-min(moment(c,x/1000) for c in r['envelope']['cases']))
        supplied=max([mu for a,b,mu in regions if a-1e-6<=x<=b+1e-6]+[0])
        if demand>supplied+1e-5:raise ValueError(f'主梁上筋材料图在{x:.1f}mm处不足：需求{demand:.3f}，可用{supplied:.3f}kN·m')
        checks.append(dict(x_mm=x,demand_kNm=demand,capacity_kNm=supplied))
    r['material_checks']=checks
    return regions


def build_chapters(r):
    p=r['input'];g=p['geometry'];l=p['loads'];m=p['materials'];sp=r['spans'];v=r['loads'];chs=[]
    def chapter(title):
        c=Chapter(title);chs.append(c);return c
    c=chapter('一 板的设计')
    c.text('本说明书按样例1的规则单向板肋梁楼盖教学模型复算。板采用1m宽板带，次梁五跨，主梁三跨。计算中间值保留全精度，正文显示值统一舍入。钢筋配置根据当前输入重新选择。')
    c.text('板的厚度一般应该由设计计算确定，即满足承载能力、刚度和裂缝控制的要求，还应满足使用要求、施工方便和经济方面的因素。对于单向板：民用建筑楼板的最小厚度不应小于60mm，工业建筑楼板的最小板厚不应小于70mm；对于双向板无论是工业建筑还是民用建筑均不应小于80mm。板的内力计算采用塑性内力重分布方法得到，板厚按不验算挠度的刚度条件确定。')
    c.eq('板厚初选','h≈l/40～l/30',f"{g['secondary_spacing_mm']}/40～{g['secondary_spacing_mm']}/30",f"{fmt(g['secondary_spacing_mm']/40)}～{fmt(g['secondary_spacing_mm']/30)}，采用{p['slab']['h_mm']}",'mm')
    c.text('上式为不需要验算刚度的最小截面高度要求，l0为单向板短边的计算跨度，即次梁的间距。当前长短跨比='+fmt(g['secondary_axis_spans_mm'][0]/g['secondary_spacing_mm'])+'，程序限定不小于3，可按单向板设计。板厚经验比值仅用于初选，不代替裂缝、挠度及振动验算。')
    c.figure('plan','结构布置及代表性计算构件')
    c.sub('1 板的荷载计算')
    terms=[('板自重',p['slab']['h_mm'],l['concrete_kN_m3']),('面层',l['finish_mm'],l['finish_kN_m3']),('板底抹灰',l['plaster_mm'],l['plaster_kN_m3'])]
    for name,t,d in terms:c.eq(name,'gk=tγ/1000',f'{t}×{d}/1000',t*d/1000,'kN/m²')
    c.eq('恒载标准值','gk=Σtiγi/1000','+'.join(fmt(t*d/1000) for _,t,d in terms),v['slab_gk'],'kN/m²')
    for label,formula,sub,val in [('恒载设计值','g=γGgk',f"{l['gamma_g']}×{fmt(v['slab_gk'],6)}",v['slab_g']),('活载设计值','q=γQqk',f"{l['gamma_q']}×{l['live_kN_m2']}",v['slab_q']),('合计','w=g+q',f"{fmt(v['slab_g'])}+{fmt(v['slab_q'])}",v['slab_g']+v['slab_q'])]:c.eq(label,formula,sub,val,'kN/m²')
    c.text('取1m板带宽度计算：g+q='+fmt(v['slab_g'])+'+'+fmt(v['slab_q'])+'='+fmt(v['slab_g']+v['slab_q'])+'kN/m，即1m宽板带上面荷载kN/m²换算为相同数值的线荷载kN/m。')
    c.eq('系数法活恒载比','q/g',f"{fmt(v['slab_q'])}/{fmt(v['slab_g'])}",v['slab_q_g'])
    c.text('说明：根据《建筑结构荷载规范》的规定，恒荷载分项系数一般取1.3，活荷载分项系数一般情况下取1.5。本次输入取γG='+fmt(l['gamma_g'])+'、γQ='+fmt(l['gamma_q'])+'，活载标准值'+fmt(l['live_kN_m2'])+'kN/m²。当q/g≤3时，说明板的弯矩调幅可以达到30%，可采用塑性内力重分布系数计算内力。')
    c.sub('2 板计算简图')
    net=g['secondary_spacing_mm']-g['wall_axis_to_inner_face_mm']-p['secondary']['b_mm']/2
    c.text('板按塑性内力重分布计算时，板的长宽比不小于3，可以按单向板设计。各跨的计算跨度为：当板与支座整体浇筑时，其计算跨度取净跨；当板支承于砖墙上时，板的边跨等于净跨加板厚的一半（ln+h/2）和净跨加板在边支座上的支承长度的一半（ln+a/2）两者的较小者。中间跨计算跨度取净跨。')
    c.eq('中间跨','l0=l轴-b次',f"{g['secondary_spacing_mm']}-{p['secondary']['b_mm']}",sp['slab_inner_mm'],'mm')
    c.eq('边跨','l0=min(ln+h/2,ln+a/2)',f"min({fmt(net)}+{p['slab']['h_mm']}/2,{fmt(net)}+{g['slab_bearing_mm']}/2)",sp['slab_edge_mm'],'mm')
    c.text('其中a='+fmt(g['slab_bearing_mm'])+'mm为板在墙上的支承长度，'+fmt(p['secondary']['b_mm'])+'mm为次梁的宽度，'+fmt(p['slab']['h_mm'])+'mm为板的厚度。故板的计算简图如下。')
    c.figure('slab_dimensions','板构件尺寸图及端支承局部')
    c.figure('slab_scheme','五跨代表板带计算简图')
    c.sub('3 板的内力计算')
    c.text('连续板跨数超过五跨时按五跨计算，不超过五跨时按实际跨数计算。中间跨与边跨的计算跨度相差不超过10%时，可以按照等跨连续板计算内力；对于不等跨（跨度相差不超过10%）的连续板，支座弯矩取相邻两跨的较大跨度计算，也可以取相邻两跨计算跨度的平均值，但跨内弯矩仍按本跨的计算跨度计算。当活载和恒载q/g≤3时采用样例1的塑性内力重分布系数，超过五跨的规则板带按五跨代表区段计算。')
    c.eq('跨度差','δ=|l边-l中|/l中',f"|{fmt(sp['slab_edge_mm'])}-{fmt(sp['slab_inner_mm'])}|/{fmt(sp['slab_inner_mm'])}",100*abs(sp['slab_edge_mm']/sp['slab_inner_mm']-1),'%')
    c.text('下图按当前计算模型绘制连续板弯矩系数：正弯矩系数标注于各跨跨中，负弯矩系数标注于内支座上方，左右对称；板线在内支座处连续。图中系数、荷载与跨度读取自本次计算结果，与下方弯矩计算表及逐项算式同源，不另行取值。')
    c.figure('slab_moment_coefficients','连续板弯矩系数示意图')
    rows=[]
    for x in r['slab'][:4]:
        co=coeff_label(x)
        rows.append([x['name'],co,fmt(x['span_mm']),f"({co})×({fmt(v['slab_g'])}+{fmt(v['slab_q'])})×({fmt(x['span_mm'])}/1000)²",('+' if x['M_kNm']>=0 else '')+fmt(x['M_kNm'],5)])
    c.table('板弯矩计算表 1m宽板带',['控制截面','弯矩系数 αm','计算跨度 l0 mm','代入 M=αm(g+q)l0²','弯矩 M kN·m/m'],rows)
    c.text('本表按1m宽板带计算：面荷载kN/m²在1m板带上换算为同数值线荷载kN/m，弯矩单位为kN·m/m（每米宽板带）。支座弯矩计算跨度与现有模型一致：第一内支座取边跨l0='+fmt(sp['slab_edge_mm'])+'mm，中间支座取中间跨l0='+fmt(sp['slab_inner_mm'])+'mm。输入限定等跨，模型左右对称，对称控制截面合并列示；若实际数值不同将分别列出。计算保留未取整值，表中仅显示时按统一位数舍入。')
    for x in r['slab'][:4]:
        co=coeff_label(x)
        c.eq(x['name'],'M=α(g+q)l0²',f"({co})×({fmt(v['slab_g'])}+{fmt(v['slab_q'])})×({fmt(x['span_mm'])}/1000)²",x['M_kNm'],'kN·m/m')
    c.sub('4 板正截面承载力计算')
    c.text('板中受力钢筋一般采用'+m['slab_steel']+'级钢筋，所以fy='+fmt(m['slab_fy_MPa'])+'N/mm²；混凝土强度等级采用'+m['concrete']+'，其轴心抗压强度fc='+fmt(m['fc_MPa'],2)+'N/mm²。板的正截面承载力计算如下表所示，表中的Ⅰ-Ⅰ板带是指板的边带，Ⅱ-Ⅱ板带是指板的中带。Ⅱ-Ⅱ板带在Ⅰ-Ⅰ板带的基础上下降'+fmt(100*(1-p['slab']['arch_factor']))+'%，是考虑板的内拱作用将计算弯矩降低。由于弯矩是取1m板带计算的，因此下表中的b=1000mm，而得到的钢筋就是1m板带内钢筋的计算值。')
    c.text('板的配筋可以采用分离式和弯起式两种：分离式配筋设计比较简单，施工方便；弯起式配筋钢筋锚固好，用钢量少，适用于有振动荷载的情况，施工比较麻烦。本设计采用分离式配筋方案。板的正截面承载力计算表的编制方式与样例1一致：Ⅰ-Ⅰ板带与Ⅱ-Ⅱ板带并列，中带按内拱折减后的弯矩计算配筋。')
    c.text('板内钢筋的构造要求主要有：')
    for line in [
      '（1）受力钢筋的间距不超过200mm，也不得小于70mm。当板厚超过150mm时，受力钢筋的间距不宜超过1.5h，且不宜大于250mm；',
      '（2）伸入支座的受力钢筋面积不少于跨中受力钢筋面积的1/3，且钢筋间距不超过400mm；多跨连续板采用分离式配筋时，跨中正弯矩钢筋宜全部伸入支座，支座负弯矩钢筋向跨内的延伸长度应覆盖负弯矩图并满足钢筋的锚固要求。简支板或连续板下部纵向受力钢筋伸入支座的锚固长度不应小于5d（d为下部纵向钢筋的直径），当连续板内温度、收缩应力较大时，伸入支座的锚固长度宜适当增加；',
      '（3）当按单向板设计时，除沿受力方向布置受力钢筋外，尚应在垂直于受力方向布置分布钢筋，单位长度上分布钢筋的截面面积不宜小于单位宽度上受力钢筋截面面积的15%，且不宜小于该方向板截面面积的0.15%，分布钢筋的间距不宜大于250mm，直径不宜小于6mm；',
      '（4）主梁上应该设置垂直于主梁方向的构造钢筋，以承担板和主梁连接处实际存在的负弯矩，其截面面积不少于受力钢筋面积的1/3，间距不应大于200mm，直径不宜小于Φ8，该构造钢筋伸入板内的长度从梁边算起不宜小于板计算跨度的1/4；',
      '（5）不论是受力方向还是非受力方向的板伸入砖墙内时，应于板中设置直径不少于Φ8、间距不宜大于200mm的构造钢筋，以负担此处板中实际存在的负弯矩：嵌固在砌体墙内的现浇混凝土板，其上部与板边垂直的构造钢筋伸入板内的长度，从墙边算起不宜小于板短边跨度的七分之一；在两边嵌固于墙内的板角部分，应配置双向上部构造钢筋，该钢筋伸入板内的长度从墙边算起不宜小于板短边跨度的四分之一；沿板的受力方向配置的上部构造钢筋，其截面面积不宜小于该方向跨中受力钢筋截面面积的三分之一；沿非受力方向配置的上部构造钢筋，可根据经验适当减少。']:
        c.text(line)
    c.text('满足上述要求可以不绘制构件的材料图。当前输入采用中带内拱折减系数'+fmt(p['slab']['arch_factor'])+'（'+('已允许采用，中带弯矩按折减系数降低' if p['slab']['arch_factor']!=1 else '未采用，中带与边带取相同弯矩')+'）；钢筋有效高度按保护层及实际选中直径重算，不固定使用范例的h0=60mm。')
    flexure_trace(c,r,'slab')
    d=r['distribution'];c.eq('分布筋需求','Asd=max(0.0015bh,0.15As主)',f"max(0.0015×1000×{p['slab']['h_mm']},0.15×{fmt(max(x['As_provided'] for x in r['slab']))})",d['As_required'],'mm²/m')
    c.eq('分布筋实配','As=πd²×1000/(4s)',f"π×{d['diameter']}²×1000/(4×{d['spacing']})",d['As_provided'],'mm²/m')
    c.text('板受力筋间距限制70至200mm；厚度超过150mm时上限取min(1.5h,250)。分布筋间距≤250mm，直径≥6mm，且应布置在受力钢筋的内侧以提高受力钢筋的有效高度。当前分布筋为'+spec(r['distribution'])+'，配筋率'+fmt(100*d['As_provided']/(1000*p['slab']['h_mm']),4)+'%，满足最小配筋率0.15%的要求，且单位长度分布钢筋截面面积大于单位宽度受力钢筋截面面积的15%。')
    c.text('构造钢筋的伸出长度：采用分离式配筋且q/g<3时，支座处承受负弯矩的钢筋直钩距次梁边缘取a=l0/4='+fmt(sp['slab_inner_mm']/4)+'mm；受力方向和非受力方向的板伸入砖墙内时设置Φ8@200构造钢筋，伸出墙边缘的距离取c=l0/7='+fmt(sp['slab_inner_mm']/7)+'mm；在墙体交叉处，配置同规格构造钢筋，伸出墙面距离取c=l0/4='+fmt(sp['slab_inner_mm']/4)+'mm。程序对上述构造伸出长度同时取不小于光圆钢筋锚固长度'+fmt(p['report']['anchor_plain_factor'])+'d，故表中构造钢筋的伸出长度不小于按比例计算的数值。板一般不进行斜截面抗剪承载力计算。')
    c.figure('slab_bars','板配筋及编号钢筋示意')
    c.sub('5 各根钢筋长度的计算')
    c.text('板钢筋按分离式配筋布置：下部正弯矩钢筋全部伸入支座，支座负弯矩钢筋向跨内延伸，伸出长度同时满足构造比例与锚固要求；板底受力钢筋两端设180°弯钩，构造钢筋端部设竖段。各编号钢筋的用途、形状、逐段尺寸及展开总长如下。')
    length_trace(c,r,'slab',summary=False)
    c=chapter('二 次梁的设计')
    c.text('次梁按塑性内力重分布方法计算。在设计次梁之前，需要先确定主梁的截面尺寸。根据经验，主梁的高度为 h≥(1/14～1/8)l0，取主梁的截面尺寸为 b×h='+fmt(p['main']['b_mm'])+'mm×'+fmt(p['main']['h_mm'])+'mm，其中l0为主梁的计算跨度。')
    c.eq('截面初选','h≈l/18～l/12',f"{g['secondary_axis_spans_mm'][0]}/18～{g['secondary_axis_spans_mm'][0]}/12",f"采用{p['secondary']['b_mm']}×{p['secondary']['h_mm']}",'mm')
    c.text('上式为不需要验算刚度的最小截面高度要求，l0为次梁的计算跨度。次梁的宽度根据经验 b≥(1/3～1/2)h，取b='+fmt(p['secondary']['b_mm'])+'mm。截面尺寸先按经验确定，再根据计算结果调整，并应满足不需要验算裂缝宽度和变形的要求。')
    c.sub('1 次梁的荷载计算')
    s=p['secondary'];S=g['secondary_spacing_mm']/1000
    c.eq('梁自重','g自=b(h-h板)γc',f"{s['b_mm']/1000}×{(s['h_mm']-p['slab']['h_mm'])/1000}×{l['concrete_kN_m3']}",v['secondary_self'],'kN/m')
    c.eq('两侧抹灰','g灰=2(h-h板)t灰γ灰',f"2×{(s['h_mm']-p['slab']['h_mm'])/1000}×{l['plaster_mm']/1000}×{l['plaster_kN_m3']}",v['secondary_plaster'],'kN/m')
    c.eq('恒载标准值','gk=g板kS+g自+g灰',f"{fmt(v['slab_gk'],6)}×{S}+{fmt(v['secondary_self'],6)}+{fmt(v['secondary_plaster'],6)}",v['secondary_gk'],'kN/m')
    c.eq('恒载设计值','g=γGgk',f"{l['gamma_g']}×{fmt(v['secondary_gk'],6)}",v['secondary_g'],'kN/m')
    c.eq('活载设计值','q=γQqkS',f"{l['gamma_q']}×{l['live_kN_m2']}×{S}",v['secondary_q'],'kN/m')
    c.sub('2 次梁的计算简图')
    net=g['secondary_axis_spans_mm'][0]-g['wall_axis_to_inner_face_mm']-p['main']['b_mm']/2
    c.text('各跨的计算跨度为：当次梁与支座整体浇筑时，其计算跨度取净跨；当次梁支承于砖墙上时，次梁的边跨等于净跨加次梁在边支座上的支承长度的一半（ln+a/2）与净跨的1.025倍两者的较小者。中间跨计算宽度取净跨。')
    c.text('主梁的支座为柱和墙体，其高跨比为'+fmt(p['main']['h_mm'])+'mm/'+fmt(g['main_axis_spans_mm'][0])+'mm＝1/'+fmt(g['main_axis_spans_mm'][0]/p['main']['h_mm'],1)+'；次梁在整体结构中仅边支座为墙体，其高跨比较大，主梁与次梁的高跨比之比远大于1，在主梁与次梁的正交梁系中绝大部分荷载分配给主梁，次梁分配的荷载很少，故可以忽略不计。因此主梁比次梁的线刚度大很多，可以认为次梁支承于主梁，主梁为次梁的支座。')
    c.eq('边跨','l0=min(ln+a/2,1.025ln)',f"min({fmt(net)}+{g['secondary_bearing_mm']}/2,1.025×{fmt(net)})",sp['secondary_edge_mm'],'mm')
    c.eq('中跨','l0=l轴-b主',f"{g['secondary_axis_spans_mm'][0]}-{p['main']['b_mm']}",sp['secondary_inner_mm'],'mm')
    c.text('其中a='+fmt(g['secondary_bearing_mm'])+'mm为次梁在墙上的支承长度，'+fmt(p['main']['b_mm'])+'mm为主梁的宽度。故次梁的计算简图如下。')
    c.figure('secondary_dimensions','次梁构件尺寸图及端支承局部')
    c.figure('secondary_scheme','次梁跨度与荷载简图')
    c.sub('3 次梁的内力计算')
    c.text('连续梁跨数超过五跨时按五跨计算，不超过五跨时按实际跨数计算。中间跨与边跨的计算跨度相差不超过10%时，可以按照等跨连续梁计算内力；对于不等跨（跨度相差不超过10%）的连续梁，支座弯矩取相邻两跨的较大跨度计算，也可以取相邻两跨计算跨度的平均值。当活载和恒载q/g≤3时，弯矩系数和剪力系数按塑性内力重分布取值如下表。弯矩用计算跨度，支座剪力用对应净跨。')
    c.text('系数法适用检查：q/g='+fmt(v['secondary_q_g'])+'≤3，跨度差='+fmt(100*abs(sp['secondary_edge_mm']/sp['secondary_inner_mm']-1))+'%≤10%。')
    c.text('次梁的弯矩计算如下表所示。')
    c.matrix('次梁弯矩计算表',table_columns(r['secondary']),[
        ('弯矩系数 α',[coeff_label(x) for x in r['secondary']]),
        ('弯矩 M=α(g+q)l0² (kN·m)',['('+coeff_label(x)+')×('+fmt(v['secondary_g'])+'+'+fmt(v['secondary_q'])+')×('+fmt(x['span_mm'])+'/1000)²='+('+' if x['M_kNm']>=0 else '')+fmt(x['M_kNm'],3) for x in r['secondary']]),
    ])
    c.text('次梁的剪力计算如下表所示。')
    c.matrix('次梁剪力计算表',table_columns(r['secondary_shear']),[
        ('剪力系数 β',[format(x['beta'],'g') for x in r['secondary_shear']]),
        ('剪力 V=β(g+q)ln (kN)',[format(x['beta'],'g')+'×('+fmt(v['secondary_g'])+'+'+fmt(v['secondary_q'])+')×'+fmt(x['span_mm'])+'/1000='+fmt(x['V_kN'],3) for x in r['secondary_shear']]),
    ])
    c.text('表中弯矩系数取边跨中1/11、第一内支座-1/11、中间跨中1/16、中间支座-1/14；剪力系数取边支座0.45、第一内支座左0.6、第一内支座右0.55、中间支座0.55。支座弯矩计算跨度：第一内支座取边跨l0='+fmt(sp['secondary_edge_mm'])+'mm，中间支座取中间跨l0='+fmt(sp['secondary_inner_mm'])+'mm；支座剪力取对应净跨。')
    for x in r['secondary']:c.eq(x['name'],'M=α(g+q)l0²',f"({coeff_label(x)})×({fmt(v['secondary_g'])}+{fmt(v['secondary_q'])})×({fmt(x['span_mm'])}/1000)²",x['M_kNm'],'kN·m')
    for x in r['secondary_shear']:c.eq(x['name'],'V=β(g+q)ln',f"{format(x['beta'],'g')}×({fmt(v['secondary_g'])}+{fmt(v['secondary_q'])})×{fmt(x['span_mm'])}/1000",x['V_kN'],'kN')
    c.text('次梁的活荷载与恒载比值不超过3，且各跨跨度相对误差不超过20%，所以决定纵向钢筋的弯起和切断时可不必作结构的内力包络图及材料图，直接采用规定的配筋方案。')
    c.sub('4 次梁的配筋计算')
    bf_e,b_sn=sp['secondary_edge_mm']/3,g['secondary_spacing_mm']-p['secondary']['b_mm']
    c.text('次梁在跨中按T形截面计算。由于次梁与板整体现浇，在跨中，板可以作为次梁的翼缘宽度。翼缘宽度的取值：（1）计算跨度的1/3；（2）按梁肋净距sn考虑为sn+b（b为梁腹板的宽度）；（3）按翼缘高度hf′考虑：当hf′/h0<0.1时取b+12hf′，否则hf′/h0≥0.1，不考虑该项影响。其有效翼缘宽度取上述三者的较小者。据此得到次梁跨中T形截面的有效翼缘宽度为：')
    c.text('边跨：hf′/h0='+fmt(p['slab']['h_mm'])+'/'+fmt(min(x['h0'] for x in r['secondary']))+'='+fmt(p['slab']['h_mm']/min(x['h0'] for x in r['secondary']),2)+('≥0.1，不考虑第（3）项的影响' if p['slab']['h_mm']/min(x['h0'] for x in r['secondary'])>=0.1 else '<0.1，尚应按b+12hf′限制')+'，于是 bf′=min(l0/3, sn+b)=min('+fmt(bf_e)+','+fmt(b_sn)+'+'+fmt(p['secondary']['b_mm'])+')='+fmt(min(bf_e,b_sn+p['secondary']['b_mm']))+'mm；取bf′='+fmt(r['secondary'][0]['bf'])+'mm。')
    c.text('中间跨：bf′=min(l0/3, sn+b)=min('+fmt(sp['secondary_inner_mm']/3)+','+fmt(b_sn)+'+'+fmt(p['secondary']['b_mm'])+')='+fmt(min(sp['secondary_inner_mm']/3,b_sn+p['secondary']['b_mm']))+'mm；取bf′='+fmt(r['secondary'][2]['bf'])+'mm。')
    c.text('次梁高度为'+fmt(p['secondary']['h_mm'])+'mm，取h0按保护层、箍筋直径及实际选中钢筋直径和排数计算，翼缘厚度为板厚hf′='+fmt(p['slab']['h_mm'])+'mm。判断T形截面类型：当α1fcbf′hf′(h0-hf′/2)大于该截面的弯矩设计值时，中和轴在翼缘内，为第一类T形截面；否则为第二类T形截面，先扣除翼缘突出部分的抗弯贡献再求腹板压区。支座截面按矩形截面计算，截面尺寸为b×h='+fmt(p['secondary']['b_mm'])+'mm×'+fmt(p['secondary']['h_mm'])+'mm。次梁正截面强度计算和斜截面计算见下表。')
    flexure_trace(c,r,'secondary');shear_trace(c,r,'secondary')
    c.figure('secondary_sections','次梁各控制截面的实际排筋')
    c.figure('secondary_bars','次梁纵筋布置及钢筋编号')
    c.sub('5 各根钢筋长度的计算')
    c.text('伸入砖墙内的钢筋面积不宜小于跨中钢筋的一半并且不能少于两根，而且伸入支座内的长度不能小于las。当中间支座负弯矩承载力计算不需要设置受压钢筋，且不会出现正弯矩时，一般将下部纵向受力钢筋伸到支座的中心线，且不少于las；当支座边缘剪力V≥0.7ftbh0时，螺纹钢筋的支座锚固长度取las=10d，V<0.7ftbh0时取5d。本方案下部纵向受力钢筋不在跨内截断，全部伸入支座。封口箍筋末端做成135°弯钩；本说明书按中心线理想圆弧展开计算箍筋与弯钩长度，并另列两端平直段，不沿用范例固定取100、130、160、190mm的增加值。')
    length_trace(c,r,'secondary',summary=False)
    c=chapter('三 主梁的设计')
    c.text('主梁在楼盖中是最重要的支承构件，一般配筋率较高；加上主梁的挠度就是次梁各支座的沉降，如采用塑性理论设计，将由于主梁的挠度大而使得整个楼盖变形过大，因此主梁一般按弹性方法计算。主梁采用恒定EI的三跨连续梁弹性分析，支座限制竖向位移、允许转动。沿用范例梁柱刚度假设；不作为框架计算。跨内两个等值三分点荷载，恒载全布，活载逐跨开关。主梁的截面尺寸为b×h='+fmt(p['main']['b_mm'])+'mm×'+fmt(p['main']['h_mm'])+'mm（见次梁的设计）。')
    c.sub('1 主梁的荷载计算')
    trib=g['secondary_axis_spans_mm'][0]/1000
    c.text('由次梁的荷载计算得到：恒载设计值为g='+fmt(v['secondary_g'])+'kN/m，活载设计值q='+fmt(v['secondary_q'])+'kN/m。主梁自重和抹灰为均布荷载，由于其在整个荷载中所占比重较小，折算为集中荷载计算，计算简单，误差不大。')
    c.eq('次梁传来恒载','G次=g次L次',f"{fmt(v['secondary_g'],6)}×{trib}",v['secondary_g']*trib,'kN')
    c.eq('主梁自重及抹灰折算','G自=γG[bγc+2t灰γ灰](h-h板)S',f"{l['gamma_g']}×[{p['main']['b_mm']/1000}×{l['concrete_kN_m3']}+2×{l['plaster_mm']/1000}×{l['plaster_kN_m3']}]×{(p['main']['h_mm']-p['slab']['h_mm'])/1000}×{S}",v['main_self_line_kN_m']*l['gamma_g']*S,'kN')
    c.eq('每个集中恒载','G=G次+G自',f"{fmt(v['secondary_g']*trib)}+{fmt(v['main_self_line_kN_m']*l['gamma_g']*S)}",v['G_kN'],'kN')
    c.eq('每个集中活载','Q=q次L次',f"{fmt(v['secondary_q'])}×{trib}",v['Q_kN'],'kN')
    c.text('注意由于主梁与板整体浇筑，主梁的高度包括板厚在内，故重算自重时减去板厚。沿用样例的g次×分担宽度荷载传递近似及主梁自重集中化；支座处直接承受的剩余自重不影响本梁跨内弯矩，但须另计柱墙竖向荷载。本报告反力仅对应所列跨内集中荷载，不代表完整楼层柱反力。')
    c.sub('2 主梁的计算简图')
    net=g['main_axis_spans_mm'][0]-g['wall_axis_to_inner_face_mm']-g['column_width_mm']/2
    c.text('假设主梁的线刚度比柱的线刚度大得多（要求梁柱线刚度之比超过4，否则应该按框架结构计算），主梁的中间支座按铰支座考虑，程序中即支座只限制竖向位移、允许转动。主梁的端部支承在砖墙上，支承长度为'+fmt(g['main_bearing_mm'])+'mm。各跨的计算跨度为：主梁中间跨计算跨度取中心线之间的距离；当主梁一端支承于砖墙上、另一端支承于柱上时，主梁的边跨等于净跨、主梁在边支座上支承长度a的一半与柱宽b的一半（ln+a/2+b/2）和净跨的1.025倍加柱宽的一半（1.025ln+b/2）中的较小者。')
    c.eq('边跨','l0=min(ln+a/2+b柱/2,1.025ln+b柱/2)',f"min({fmt(net)}+{g['main_bearing_mm']}/2+{g['column_width_mm']}/2,1.025×{fmt(net)}+{g['column_width_mm']}/2)",sp['main_m'][0]*1000,'mm')
    c.text('其中主梁在外墙上的支承长度为'+fmt(g['main_bearing_mm'])+'mm，柱的宽度为'+fmt(g['column_width_mm'])+'mm。三个计算跨度（mm）：'+', '.join(fmt(L*1000) for L in sp['main_m'])+'。次梁荷载位于计算跨度的1/3及2/3；物理轴网和计算简图位置区别在钢筋定位时作跨度比例映射。')
    c.figure('main_dimensions','主梁构件尺寸图及端支承局部')
    c.figure('main_scheme','主梁计算简图')
    c.sub('3 主梁的内力计算')
    c.text('连续梁跨数超过五跨时按五跨计算，不超过五跨时按实际跨数计算；本设计主梁仅有三跨。中间跨与边跨的计算跨度相差不超过10%，可以按照等跨连续梁计算内力。范例按 M=k1Gl0+k2Ql0 查表系数法考虑恒载①、活载②③④⑤共五种受力情况（①恒载满布且对称，②活载作用于两边跨，③活载作用于中间跨，④⑤分别为活载作用于左侧和右侧两边跨的反对称情况）。本程序采用Euler–Bernoulli梁单元直接求解，每跨在两个集中荷载点处分段，支座竖向位移为零，恒载全布、活载逐跨开关，共8种活载组合，与范例的五种受力情况等效，但不依赖查表系数精度，并完整保留各工况的内力过程。')
    c.text('弯矩、剪力按各控制截面列出全部工况值与最不利组合；完整工况保留在附录及results.json中。')
    c.eq('单元刚度','ke=(EI/L³)K','K=[12,6L,-12,6L; 6L,4L²,-6L,2L²; -12,-6L,12,-6L; 6L,2L²,-6L,4L²]','EI取统一单位刚度；内力不受其共同倍数影响')
    c.eq('自由节点平衡','Kff uf=Ff','约束支座竖向位移后，消元求自由位移；fe=ke ue','由杆端力求M、V和支座反力')
    c.figure('patterns','八种活载布置 恒载始终存在')
    xs=[sp['main_m'][0]/3,2*sp['main_m'][0]/3,sp['main_m'][0],sp['main_m'][0]+sp['main_m'][1]/3,sp['main_m'][0]+2*sp['main_m'][1]/3,sum(sp['main_m'][:2])]
    c.table('主梁弯矩计算表 kN·m',['工况','左跨1/3','左跨2/3','B轴线','中跨1/3','中跨2/3','C轴线'],[[q['pattern']]+[fmt(moment(q,x)) for x in xs] for q in r['envelope']['cases']])
    c.text('弯矩表中控制截面取各跨三分点（集中荷载作用点）及支座轴线，正弯矩为使梁下部受拉的弯矩，负弯矩为使梁上部受拉的弯矩；支座截面的配筋弯矩另按柱边截面取值。')
    c.table('主梁剪力计算表 kN',['工况']+['段'+str(i+1) for i in range(9)],[[q['pattern']]+[fmt(t['v'],2) for t in q['segments']] for q in r['envelope']['cases']])
    c.text('剪力表中每一跨划分为三个单元段，段1、段2、段3分别为边跨左段、中段、右段，段4至段6为中间跨，段7至段9为右跨；各段的剪力为常值，可直接用于箍筋与支座锚固的验算。为便于核对平衡条件，各工况支座反力与平衡残差一并列于附录。')
    c.figure('moment_envelope','主梁弯矩包络 正弯矩向下')
    c.figure('shear_envelope','主梁剪力包络')
    c.sub('4 截面强度计算')
    xx=sp['main_m'][0];half=g['column_width_mm']/2000
    rows=[]
    for case in r['envelope']['cases']:
        for side,pos in [('左',xx-half),('右',xx+half)]:
            rows.append([case['pattern'],side,fmt(moment(case,xx)),fmt(moment(case,pos)),fmt(1000*pos)])
    mb=p['main']['b_mm'];mb_bf=min(min(sp['main_m'])*1000/3,trib*1000)
    c.text('（1）主梁跨中截面按T形截面计算，其翼缘宽度取下列二者较小者：bf′=l/3='+fmt(min(sp['main_m'])*1000)+'/3='+fmt(min(sp['main_m'])*1000/3)+'mm；bf′=b+sn='+fmt(trib*1000)+'mm；取bf′='+fmt(mb_bf)+'mm。判别T形截面类型：当α1fcbf′hf′(h0-hf′/2)大于该截面弯矩设计值时，中和轴在翼缘内，为第一类T形截面，否则为第二类T形截面。')
    c.text('（2）支座截面和在负弯矩作用下的跨中截面按矩形截面计算，截面尺寸为'+fmt(mb)+'mm×'+fmt(p['main']['h_mm'])+'mm。主梁中间支座宽度为柱宽，b='+fmt(g['column_width_mm'])+'mm。考虑支座弯矩较大且主梁布置两排纵筋，并布置在次梁主筋的下面，取h0按保护层、箍筋直径、实际选中钢筋直径与排数计算。第（1）（2）条与范例取值原则一致，具体数值按本次计算结果重算。')
    flexure_trace(c,r,'main');shear_trace(c,r,'main')
    c.text('按同一工况在柱边求弯矩，再从全部工况选最小值，不将最大剪力与另一工况的最大弯矩拼接。截面腹板宽取梁宽，柱宽只参与计算位置。下表列出第一内支座（B支座）各工况左右柱边的边缘弯矩明细，供核对上表支座设计弯矩。')
    c.table('B支座逐工况边缘弯矩',['工况','柱边','轴线M','柱边M','坐标mm'],rows)
    c.sub('5 主梁吊筋计算')
    su=r['suspension'];asv=p['main']['stirrup_legs']*area(su['diameter'])
    c.text('由次梁传递给主梁的全部集中荷载设计值由次梁传来的恒载与活载组成，不包括主梁的自重在内。吊筋与附加箍筋的构造要求：吊筋宜采用45°弯起，下部水平段锚固长度不小于20d并不少于梁宽两侧各50mm，上部水平段不宜小于20d；附加箍筋应在次梁两侧对称布置，间距不宜大于100mm，直径不小于主梁箍筋直径。本方案采用附加箍筋承担次梁传来的集中力，不另计斜吊筋承载力。附加箍筋数量在原抗剪箍筋之外增加。')
    c.eq('次梁集中力','F=(g次+q次)L次',f"({fmt(v['secondary_g'])}+{fmt(v['secondary_q'])})×{trib}",su['F_kN'],'kN')
    c.eq('附加箍筋需求','n≥F/(n肢Asv1fyv)',f"{fmt(su['F_kN']*1000)}/({p['main']['stirrup_legs']}×{fmt(area(su['diameter']))}×{m['stirrup_fy_MPa']})",su['count'],'道，向上取偶数')
    c.eq('布置范围','s0=2(h主-h次)+3b次',f"2×({p['main']['h_mm']}-{p['secondary']['h_mm']})+3×{p['secondary']['b_mm']}",su['range_mm'],'mm')
    c.text(f"交接处两侧各{su['per_side']}道附加双肢Φ{su['diameter']}箍筋，间距{su['spacing_mm']}mm；总承载力{fmt(su['capacity_kN'])}kN≥F。两侧实际范围合计不超过计算s0。范例按斜吊筋计算并实配2Φ16，本程序改用附加箍筋承担同一集中力，附加箍筋的范围与数量均满足上述构造与受力要求；实际选用时应再核对附加箍筋与原抗剪箍筋的协同及节点容纳。")
    c.sub('6 主梁的配筋示意图');c.figure('main_sections','主梁各控制截面实际配筋');c.figure('main_bars','主梁纵筋布置及搭接关系')
    c.sub('7 鸭筋设置');c.text('抗剪箍筋满足截面抗剪与构造条件，交接处另设附加箍筋，因此本方案不设置专门抗剪鸭筋，不用图示斜线代替未经计算的钢筋。')
    c.sub('8 钢筋的构造要求')
    c.text('有关钢筋的构造要求如下，其中与本方案做法不同的条目按本方案的实际做法说明。')
    for line in [
      '（1）纵筋的弯起应满足三方面的要求：①保证正截面的承载力要求，始弯点必须位于该纵筋强度充分利用点以外，即抵抗弯矩图包在设计弯矩包络图外面；②保证斜截面的受剪承载力，弯起钢筋应覆盖计算斜截面到相邻集中荷载作用点的范围；③保证斜截面的受弯承载力，受拉区内始弯点应设在该钢筋不需要充分利用的截面以外，距离不小于h0/2。本方案正弯矩纵筋全部采用直筋伸入支座、不设弯起钢筋，本条不适用。',
      '（2）纵筋的切断：①下部受拉纵筋不宜在跨中截面截断，应该伸入支座；②上部负弯矩钢筋可以切断，截面切断的位置和根数应由抵抗弯矩图确定，实际切断点应延伸到理论切断点截面以外不小于20d，且实际切断点到充分利用点的距离不小于ld。本程序支座负筋全组伸出，截断点同时满足零弯矩包络点外20d与充分利用位置外1.2la+h0，不采用分批截断方案。',
      '（3）下部纵向钢筋伸入梁端支座的锚固长度应大于las：当V≥0.7ftbh0时，光圆钢筋las≥15d、月牙肋钢筋las≥12d、螺纹钢筋las≥10d；当V<0.7ftbh0时las≥5d。如果锚固长度不能满足要求，应采取加焊横向锚固钢筋、锚固钢板或将钢筋端部焊接在梁端预埋件上等锚固措施。',
      '（4）下部纵向钢筋伸入支座内的锚固长度las：当计算中不利用支座边缘下部纵筋的强度时，不论剪力大小，其伸入支座的锚固长度应符合（3）的规定；当计算中充分利用其抗拉强度时，伸入支座的锚固长度不应小于受拉钢筋的最小锚固长度la；当充分利用其抗压强度时，不应小于0.7la。',
      '（5）架立钢筋与受力钢筋的搭接长度：当d≤10mm时为100mm，否则为150mm。如果考虑架立钢筋的受力，应满足受力搭接要求，即受拉区不小于1.2la且大于300mm，受压区不小于0.85la且大于200mm。',
      '（6）架立钢筋在支座处的锚固：简支梁的架立钢筋一般伸入梁端；考虑其受力时应满足纵向受拉钢筋的最小锚固长度la。梁嵌固在砖砌体内时，可利用架立钢筋做构造负筋，此时架立钢筋宜采用2Φ12，伸入支座的长度不小于la；梁简支在砖砌体上或梁端上部砌体不高时，架立钢筋伸入梁端不做负筋。',
      '（7）箍筋：梁内箍筋末端应做成135°弯钩，平直段长度不小于10d；箍筋最小直径与最大间距按梁高及是否需计算配箍确定，搭接范围内箍筋间距另加密，主次梁交接处另设附加箍筋。']:
        c.text(line)
    c.text('本方案的具体做法：纵筋不在跨内截断下部钢筋。支座负筋全组伸出，截断点同时满足零弯矩包络点外20d及充分利用位置外1.2la+h0。无零点的中跨由两侧负筋搭接连续覆盖。搭接系数按100%接头保守取'+fmt(p['report']['lap_factor'],2)+'，搭接范围另将箍筋间距限制为min(100,5d纵)。')
    c.text('锚固基准取max(输入系数×d,0.14fy/ft×d,200mm)，带肋输入系数不小于'+fmt(p['report']['anchor_ribbed_factor'])+'。端部构造筋弯锚记录直段和补足竖段；本教学模型未对节点三维碰撞、砌体局压和锚固区劈裂作专项分析。')
    joint_rows=[]
    for t in r['joint_checks']:
        label=('主梁' if t['member']=='main' else '次梁')
        if 'overlap_mm' in t:
            joint_rows.append([label+'第'+str(t['span'])+'跨',t['method']+'；搭接'+fmt(t['overlap_mm'])+'mm，要求≥'+fmt(t['required_mm'])+'mm。搭接实有'+str(t['physical_count'])+'根，排布'+str(t['rows'])+'；承载力只计一组且按内排h0='+fmt(t['h0_mm'])+'mm，Mu='+fmt(t['capacity_kNm'])+'kN·m。'])
        else:joint_rows.append([label+'搭接范围','箍筋Φ'+str(t['diameter'])+'，间距≤'+fmt(t['spacing_mm'])+'mm。'])
    c.table('连接部位构造记录',['部位','处理'],joint_rows)
    c.sub('9 跨中 支座实际承担弯矩计算')
    c.text('采用实配钢筋的压区平衡计算实际承载力，不采用范例的M×As实/As算线性放大。全组负筋不分批截断，因此不将总承载力按钢筋面积比例拆分。')
    for x in r['main']:
        c.eq(x['name']+'实配压区','x实由α1fc压区面积=fyAs实求得',f"As实={fmt(x['As_provided'])}，fy={m['beam_fy_MPa']}，fc={m['fc_MPa']}",x['x_provided'],'mm')
        c.eq(x['name']+'实配承载力','Mu=ΣCi(h0-yi)/10⁶',f"x实={fmt(x['x_provided'])}，h0={fmt(x['h0'])}，b有效={fmt(x['bf'])}",x['Mu_kNm'],'kN·m')
    c.figure('material','主梁负弯矩包络与材料抵抗弯矩范围')
    c.sub('10 各根钢筋长度计算')
    c.text('主梁纵向受力钢筋按支座负筋全组伸出、下部纵筋伸入支座不截断的方式布置；相邻支座负筋在中跨搭接连续覆盖，端部构造筋弯锚并记录直段与补足竖段。各编号钢筋的用途、形状、逐段尺寸及展开总长如下，汇总表见附录。')
    length_trace(c,r,'main',summary=False)
    c=chapter('附录 参数 工况与差异记录')
    c.sub('编号钢筋长度汇总')
    c.text('下列汇总表按板、次梁、主梁分别列出编号钢筋的用途、组内根数、单根几何长度与向上取整长度。长度为代表构件的单根长度，不是整层采购总量；弯折形状的水平宽度不等于展开总长。')
    for member,label in [('slab','板'),('secondary','次梁'),('main','主梁')]:
        items=[x for x in r['bars'] if x['member']==member]
        c.table(label+'编号钢筋长度汇总',['编号','用途','直径mm','组内根数','单根mm','向上取整mm'],
                [[x['mark'],x['use'],x['diameter'],x['count'],fmt(x['length_mm'],1),x['rounded_mm']] for x in items])
    c.sub('主梁各工况反力与平衡')
    c.text('为便于核对平衡条件，下表列出8种活载布置下主梁各支座的反力及平衡残差（残差为反力之和减外荷载之和，正常应为零）。')
    c.table('主梁各工况反力与平衡',['活载布置','左端','B支座','C支座','右端','残差kN'],[[q['pattern']]+[fmt(t) for t in q['reactions']]+[fmt(q['equilibrium_error'],9)] for q in r['envelope']['cases']])
    c.sub('输入参数');flatten=[]
    def walk(o,path=''):
        for k,vv in o.items():
            if isinstance(vv,dict):walk(vv,path+k+'.')
            else:flatten.append([path+k,str(vv)])
    walk(p);c.table('本次输入完整记录',['参数','数值'],flatten)
    c.sub('主梁单元内力完整记录')
    for q in r['envelope']['cases']:
        c.table('活载布置 '+q['pattern'],['段','x0 m','x1 m','M0 kN·m','M1 kN·m','V kN'],[[i+1]+[fmt(t[k],5) for k in ['x0','x1','m0','m1','v']] for i,t in enumerate(q['segments'])])
    c.sub('样例1纠错及方法差异')
    corrections=[('第3页','抹灰0.012×16=0.192；全精度恒载2.592。原稿2.60是舍入，12.86为遗留值。'),('第11页','1.025×5755=5898.875，非5900；按实际输入取较小跨度。'),('第13页','T形判别仍引用旧弯矩72.48及47.73；改用本次结果。'),('第15页','10×16=160，不是180。'),('第20至22页','完整枚举8种活载；保留左右对称性但不复制旧表数值。'),('第23页','支座腹板宽取梁宽250，不把柱宽300当梁宽；柱边弯矩按同工况计算。'),('第24页','统一采用Vc=0.7ftbh0及Vs=1.25fyvAsvh0/s；原稿的1.5及C25材料值不沿用。'),('第24至25页','要求至少7道却两侧各3道不一致；取向上偶数，并校核总承载力。'),('第27页','实际承载力由实配钢筋平衡计算，替代面积比近似。'),('第28至30页','不混用旧配筋数值、不同直径平均锚固系数及不同箍筋增加长度；全部随输入计算。')]
    c.table('逐项差异',['范例位置','处理'],corrections)
    c.sub('适用范围与人工校核')
    c.text('本次程序内检查通过不等于工程规范全项合格。仍需核对荷载组合、板内拱条件、梁柱刚度假设、砌体局压、抗震、耐久性与防火、裂缝、挠度、振动、锚固区横向约束、节点碰撞及加工弯曲调整。长度表为教学配筋方案的几何展开，不提供未经复核的全楼下料总量。')
    c.text('格式及教学取值来源：用户提供《样例1-设计说明书1.pdf》，30页。规范现行名称为《混凝土结构设计标准》GB/T 50010-2010（2024年版）；本程序不声称完成该标准全项校核。住建部公告检索来源：https://www.mohurd.gov.cn/gongkai/zhengce/zhengcefilelib/202405/20240523_778180.html 。')
    return [dict(title=c.title,items=c.items) for c in chs]


def material_line(p,member):
    """Material and section constants, printed once per member as sample 1 does."""
    m=p['materials'];slab=member=='slab'
    steel=m['slab_steel'] if slab else m['beam_steel']
    fy=m['slab_fy_MPa'] if slab else m['beam_fy_MPa']
    b=1000 if slab else p[member]['b_mm']
    text=(f"{m['concrete']} 混凝土，fc={fmt(m['fc_MPa'],2)}N/mm²，ft={fmt(m['ft_MPa'],3)}N/mm²，"
          f"{steel} 级受力钢筋，fy={fmt(fy)}N/mm²，α1={fmt(m['alpha1'],2)}，b={b}mm，h={p[member]['h_mm']}mm，"
          f"保护层c={p[member]['cover_mm']}mm，箍筋{m['stirrup_steel']}级fyv={fmt(m['stirrup_fy_MPa'])}N/mm²。")
    return text


def ratio_cell(x,b,h):
    """Provided reinforcement ratio checked against the computed minimum ratio."""
    return f"{fmt(100*x['As_provided']/(b*h),2)}%≥{fmt(100*x['As_min']/(b*h),2)}%"


def table_columns(rows):
    """Header groups for the capacity tables: the first column carries row labels."""
    return [('截面',None)]+[(x['name'],None) for x in rows]


def capacity_table(c,r,member):
    """Sample-format flexural capacity table, sections as columns and items as rows."""
    p=r['input'];m=p['materials'];slab=member=='slab'
    b=1000 if slab else p[member]['b_mm'];h=p[member]['h_mm'];unit='mm²/m' if slab else 'mm²'
    rows=r[member]
    if slab:
        # Rows 0-3 are the edge band; rows 4-5 repeat the two inner sections as
        # the middle band with the arch reduction, so the table keeps the two
        # tiers of sample 1 (I-I band over II-II band).
        if len(rows)!=6: raise ValueError('板配筋结果行数异常，无法按Ⅰ-Ⅰ/Ⅱ-Ⅱ板带列表')
        data=[rows[0],rows[1],rows[2],rows[4],rows[3],rows[5]]
        groups=[('截面',None),('边跨中',None),('第一内支座',None),
                ('中间跨中',['Ⅰ-Ⅰ板带','Ⅱ-Ⅱ板带']),('中间支座',['Ⅰ-Ⅰ板带','Ⅱ-Ⅱ板带'])]
    else:
        data=rows;groups=table_columns(rows)
    def al(x): return abs(x['M_kNm'])*1e6/(m['alpha1']*m['fc_MPa']*x['bf']*x['h0']**2)
    cells=[]
    if member=='main':
        sup=main_support(r)
        index=[x['name'] for x in data].index('中间支座')
        axis=['-']*len(data);v0=['-']*len(data)
        axis[index]=fmt(sup['axis_kNm'],3);v0[index]=fmt(sup['reduction_kNm'],3)
        cells.append(('弯矩 M (kN·m)',[('+' if x['M_kNm']>=0 else '')+fmt(x['M_kNm'],3) for x in data]))
        cells.append(('其中轴线弯矩 M轴 (kN·m)',axis))
        cells.append(('V0·b柱/2 (kN·m)',v0))
    else:
        cells.append((f'弯矩 M (kN·m{"/m" if slab else ""})',
                      [('+' if x['M_kNm']>=0 else '')+fmt(x['M_kNm'],3) for x in data]))
    cells.extend([
        ('b(bf′)、h0 (mm)',[f"{fmt(x['bf'])}, {fmt(x['h0'])}" for x in data]),
        ('αs', [fmt(al(x),4) for x in data]),
        ('ξ=1-√(1-2αs)',[fmt(x['xi'],4) for x in data]),
        (f'As计算 ({unit})',[fmt(x['As_calc'],1) for x in data]),
        ('选配钢筋',[spec(x) for x in data]),
        (f'实配面积 ({unit})',[fmt(x['As_provided'],1) for x in data]),
        ('实配配筋率 (%)',[ratio_cell(x,b,h) for x in data]),
    ])
    c.matrix({'slab':'板截面承载力计算','secondary':'次梁正截面承载力计算','main':'主梁正截面承载力计算'}[member],groups,cells)


def main_support(r):
    """Axis moment, governing shear and the V0*b/2 reduction at the first inner support."""
    return r['support']


def shear_table(c,r,member):
    p=r['input'];m=p['materials'];s=p[member];rows=r[member+'_shear']
    def bound(v,limit): return f'{fmt(limit,1)}'+('>V' if limit>=v else '<V')
    c.matrix(('次梁' if member=='secondary' else '主梁')+'斜截面承载力计算',table_columns(rows),[
        ('剪力 V (kN)',[fmt(x['V_kN'],2) for x in rows]),
        ('b、h0 (mm)',[f"{s['b_mm']}, {fmt(x['h0'])}" for x in rows]),
        ('0.25fcb·h0 (kN)',[bound(x['V_kN'],x['Vmax_kN']) for x in rows]),
        ('0.7ftb·h0 (kN)',[bound(x['V_kN'],x['Vc_kN']) for x in rows]),
        ('选配箍筋',[f"{x['legs']}Φ{x['diameter']}" for x in rows]),
        ('Asv=nAsv1 (mm²)',[fmt(x['Asv'],1) for x in rows]),
        ('s=1.25fyvAsvh0/(V-Vc) (mm)',['按构造' if x['s_strength_mm'] is None else fmt(x['s_strength_mm'],1) for x in rows]),
        ('实际箍筋间距 (mm)',[str(x['spacing']) for x in rows]),
    ])


def flexure_trace(c,r,member):
    p=r['input'];m=p['materials'];slab=member=='slab';b=1000 if slab else p[member]['b_mm'];h=p[member]['h_mm'];fy=m['slab_fy_MPa'] if slab else m['beam_fy_MPa']
    c.text('材料与截面：'+material_line(p,member))
    c.text('计算式：矩形或第一类T形截面αs=|M|/(α1fcb有效h0²)，ξ=1-√(1-2αs)，As=α1fcb有效ξh0/fy。第二类T形先扣除翼缘突出部分的抗弯贡献，再求腹板压区。')
    for index,x in enumerate(r[member]):
        if member=='slab' and index>=4 and p['slab']['arch_factor']==1:
            c.text(x['name']+'：本次未采用内拱折减，M、h0及配筋计算与对应边带相同，结果列入下表。')
            continue
        c.text(x['name']+'，'+x['section_type']+'，选用'+spec(x)+'。')
        c.eq('有效高度','h0=h-a实',f"{h}-{fmt(h-x['h0'])}",x['h0'],'mm')
        if x['bf']>b:
            c.eq('有效翼缘宽度','bf=min(l0/3,梁间距；hf/h0<0.1时还取b+12hf)',f"hf/h0={p['slab']['h_mm']}/{fmt(x['h0'])}；据本截面跨度及间距取小",x['bf'],'mm')
            lim=m['alpha1']*m['fc_MPa']*x['bf']*p['slab']['h_mm']*(x['h0']-p['slab']['h_mm']/2)/1e6
            c.eq('T形类别判别','M界=α1fcbfhf(h0-hf/2)/10⁶',f"{m['alpha1']}×{m['fc_MPa']}×{fmt(x['bf'])}×{p['slab']['h_mm']}×({fmt(x['h0'])}-{p['slab']['h_mm']}/2)/10⁶",lim,'kN·m')
        c.eq('弯矩系数','αs=|M|10⁶/(α1fcb有效h0²)',f"{fmt(abs(x['M_kNm']),6)}×10⁶/({m['alpha1']}×{m['fc_MPa']}×{fmt(x['bf'])}×{fmt(x['h0'])}²)",abs(x['M_kNm'])*1e6/(m['alpha1']*m['fc_MPa']*x['bf']*x['h0']**2))
        if x['section_type']!='第二类T形':
            al=abs(x['M_kNm'])*1e6/(m['alpha1']*m['fc_MPa']*x['bf']*x['h0']**2)
            c.eq('相对受压区高度','ξ=1-√(1-2αs)',f"1-√(1-2×{fmt(al,8)})",x['xi'])
            c.eq('受力钢筋','As=α1fcb有效ξh0/fy',f"{m['alpha1']}×{m['fc_MPa']}×{fmt(x['bf'])}×{fmt(x['xi'],8)}×{fmt(x['h0'])}/{fy}",x['As_calc'],'mm²')
        else:
            hf=p['slab']['h_mm'];cf=m['alpha1']*m['fc_MPa']*(x['bf']-b)*hf;mf=cf*(x['h0']-hf/2)/1e6
            c.eq('突出翼缘抗弯贡献','Mf=α1fc(bf-b)hf(h0-hf/2)/10⁶',f"{m['alpha1']}×{m['fc_MPa']}×({fmt(x['bf'])}-{b})×{hf}×({fmt(x['h0'])}-{hf}/2)/10⁶",mf,'kN·m')
            ab=(abs(x['M_kNm'])-mf)*1e6/(m['alpha1']*m['fc_MPa']*b*x['h0']**2)
            c.eq('腹板压区','ξ=1-√(1-2α腹)',f"α腹=({fmt(abs(x['M_kNm']))}-{fmt(mf)})×10⁶/({m['alpha1']}×{m['fc_MPa']}×{b}×{fmt(x['h0'])}²)={fmt(ab,8)}",x['xi'])
            c.eq('总受力钢筋','As=[α1fcbξh0+Cf]/fy',f"({m['alpha1']}×{m['fc_MPa']}×{b}×{fmt(x['xi'],8)}×{fmt(x['h0'])}+{fmt(cf)})/{fy}",x['As_calc'],'mm²')
        c.eq('最小钢筋','Asmin=max(0.002,0.45ft/fy)bh',f"max(0.002,0.45×{m['ft_MPa']}/{fy})×{b}×{h}",x['As_min'],'mm²')
        c.eq('实配面积','As实=nπd²/4 或 πd²1000/(4s)',spec(x),x['As_provided'],'mm²/m' if slab else 'mm²')
        c.text('验算：As实≥max(As算,Asmin)；ξ计算='+fmt(x['xi'],4)+'，ξ实配='+fmt(x['xi_provided'],4)+'，限值='+fmt(m['xi_elastic_limit'] if member=='main' else m['xi_plastic_limit'])+'。实配Mu='+fmt(x['Mu_kNm'])+'kN·m≥|M|。'+('排布='+str(x['rows'])+'，净距要求='+fmt(x['clear_mm'])+'mm。' if not slab else ''))
    limit=m['xi_elastic_limit'] if member=='main' else m['xi_plastic_limit']
    c.text('说明：表中αs=|M|·10⁶/(α1fcb有效h0²)，b有效为矩形截面宽度或T形截面有效翼缘宽度，h0按实际选中钢筋直径及排数重算；'
           'As最小按max(0.002,0.45ft/fy)·b·h计算，当As计算小于As最小或受钢筋间距构造限值时，配筋由最小配筋率与构造要求控制；'
           '实配配筋率按As实/(b·h)计算并与最小配筋率Asmin/(b·h)比较。'
           +('表中按1m宽板带列出，As与实配面积均为每米板宽的数值。' if slab else '')
           +'所有控制截面的相对受压区高度ξ计算值与实配值均应不超过限值'+fmt(limit)+'：'
           +('主梁按弹性理论计算，限值取'+fmt(limit)+'以保证不出现超筋梁' if member=='main' else '次梁按塑性内力重分布计算，限值取0.35以保证塑性内力重分布的实现条件')
           +'；不满足时说明截面尺寸太小，必须加大截面尺寸或提高混凝土强度等级。')
    if member=='main':
        sup=main_support(r)
        design=abs(sup['design_kNm']);approx=abs(sup['axis_kNm'])-sup['reduction_kNm']
        c.text('支座截面按矩形截面计算；考虑支座弯矩较大且布置两排纵筋，支座设计弯矩按柱边截面取值。'
               '第一内支座轴线弯矩'+fmt(sup['axis_kNm'],3)+'kN·m，减去V0·b柱/2='+fmt(sup['reduction_kNm'],3)+'kN·m'
               '（V0取第一内支座左侧全部工况的最大剪力'+fmt(sup['v0_kN'],2)+'kN，b柱='+fmt(sup['b_mm'])+'mm）后为'
               +fmt(approx,3)+'kN·m；程序直接取各工况柱边截面的最小值'+fmt(sup['design_kNm'],3)+'kN·m作为配筋弯矩，'
               '不将不同工况的弯矩与剪力拼接，两者相差'+fmt(abs(design-approx)/design*100,2)+'%，取较不利者。')
    capacity_table(c,r,member)


def shear_trace(c,r,member):
    p=r['input'];m=p['materials'];s=p[member]
    c.text('斜截面承载力按V≤0.25fcbh0验算截面尺寸上限，并按V≤0.7ftbh0+1.25fyvAsvh0/s配置箍筋；'
           '当V≤0.7ftbh0时说明截面剪力很小，可按构造要求配置箍筋，即满足最小箍筋直径、最大箍筋间距和最小配箍率要求即可。'
           '设计剪力取各控制截面的最不利值，h0取同组纵向钢筋的最小值，偏于安全。')
    c.text('箍筋强度按'+m['stirrup_steel']+'级取fyv='+fmt(m['stirrup_fy_MPa'])+'N/mm²。最小箍筋直径要求：h≤800mm时dmin=6mm，h>800mm时dmin=8mm；'
           '最大箍筋间距按梁高及是否需计算配箍取值：150<h≤300时取150mm（V>0.7ftbh0）或200mm（V≤0.7ftbh0），'
           '300<h≤500时取200mm或300mm，500<h≤800时取250mm或350mm。'
           '本说明书统一采用Vc=0.7ftbh0与Vs=1.25fyvAsvh0/s，不沿用范例的1.5系数；箍筋沿全梁长采用同一间距，便于施工。')
    for x in r[member+'_shear']:
        c.text(x['name']+' 斜截面验算，V='+fmt(x['V_kN'])+'kN。采用各控制截面最小h0，保守计算。')
        for label,factor,val in [('截面上限',.25,x['Vmax_kN']),('混凝土抗剪',.7,x['Vc_kN'])]:
            f=m['fc_MPa'] if factor==.25 else m['ft_MPa'];c.eq(label,'V=系数×f×b×h0/1000',f"{factor}×{f}×{s['b_mm']}×{fmt(x['h0'])}/1000",val,'kN')
        c.eq('箍筋面积','Asv=nπd²/4',f"{x['legs']}×π×{x['diameter']}²/4",x['Asv'],'mm²')
        if x['s_strength_mm'] is None:c.text('V≤Vc，按构造及最小配箍率配置。')
        else:c.eq('强度控制间距','s≤1.25fyvAsvh0/[(V-Vc)1000]',f"1.25×{m['stirrup_fy_MPa']}×{fmt(x['Asv'])}×{fmt(x['h0'])}/[({fmt(x['V_kN'])}-{fmt(x['Vc_kN'])})×1000]",x['s_strength_mm'],'mm')
        c.eq('最小配箍率','ρsv,min=0.24ft/fyv',f"0.24×{m['ft_MPa']}/{m['stirrup_fy_MPa']}",x['rho_min'])
        c.eq('选用间距','s向下取10mm整=min(s强度,s配箍率,s构造,s输入)',f"min({fmt(x['s_strength_mm']) if x['s_strength_mm'] is not None else '不限'},{fmt(x['s_rho_mm'])},{x['s_code_mm']},{s['max_stirrup_spacing_mm']})",x['spacing'],'mm')
        c.text('选用'+spec(x)+'双肢箍筋；抗剪承载力='+fmt(x['capacity_kN'])+'kN≥V。')
    shear_table(c,r,member)
    c.text('说明：表中0.25fcbh0一栏用于验算截面尺寸是否符合要求，若截面剪力超过该值，说明截面尺寸太小，必须加大截面尺寸或提高混凝土强度等级；'
           '0.7ftbh0一栏为构造配箍界限。s=1.25fyvAsvh0/(V-Vc)为强度控制间距，实际箍筋间距同时满足强度、最小配箍率ρsv≥0.24ft/fyv、'
           '最大箍筋间距及输入上限，向下取10mm整数。配箍率验算：ρsv=Asv/(b·s)='
           +fmt(r[member+'_shear'][0]['Asv'])+'/('+fmt(s['b_mm'])+'×'+str(r[member+'_shear'][0]['spacing'])+')='
           +fmt(100*r[member+'_shear'][0]['Asv']/(s['b_mm']*r[member+'_shear'][0]['spacing']),4)+'%≥ρsv,min='
           +fmt(100*r[member+'_shear'][0]['rho_min'],4)+'%，满足要求。')


def length_trace(c,r,member,summary=True):
    rows=[x for x in r['bars'] if x['member']==member]
    for x in rows:
        c.text(x['mark']+' '+x['use']+' '+str(x['count'])+'Φ'+str(x['diameter']))
        if x['position']:
            pos=x['position'];labels={'method':'方法','left_mm':'左端伸出mm','right_mm':'右端伸出mm','la_mm':'锚固长度mm','lap_mm':'受拉搭接mm','ld_mm':'充分利用位置外伸mm','left_zero_mm':'左零点距梁边mm','right_zero_mm':'右零点距梁边mm','left_rule':'左端规则','right_rule':'右端规则'}
            c.text('定位计算：'+'；'.join(labels.get(k,k)+'='+('无零点，保持连续' if v is None else fmt(v)) for k,v in pos.items()))
        c.eq('单根展开长度','L=各直段+圆弧+搭接锚固段',' + '.join(fmt(v) for _,v in x['segments']),x['length_mm'],'mm')
        c.text('分段：'+'；'.join(n+'='+fmt(v)+'mm' for n,v in x['segments'])+'。'+x['notes'])
    if summary:c.table('编号钢筋长度汇总',['编号','用途','直径mm','组内根数','单根mm','向上取整mm'],[[x['mark'],x['use'],x['diameter'],x['count'],fmt(x['length_mm'],1),x['rounded_mm']] for x in rows])
    c.figure(member+'_shapes','编号钢筋真实尺寸及展开总长对照')
