"""Dimension chains and bar centreline components shared by all renderers (mm).

This module describes the existing teaching length model; it never selects steel
or adjusts a fabrication length. Unknown bends remain explicitly schematic.
"""
import math
from itertools import accumulate

MEMBERS={'slab':'板','secondary':'次梁','main':'主梁'}
SCALES=(10,20,25,50,75,100,150,200,250,500,1000)


def line(a,b,label=''):
    return dict(kind='line',a=list(a),b=list(b),label=label,length_mm=math.dist(a,b))


def arc(c,r,start,sweep,label=''):
    return dict(kind='arc',center=list(c),radius_mm=r,start_deg=start,sweep_deg=sweep,
                label=label,length_mm=abs(math.radians(sweep))*r)


def vertices(part):
    if part['kind']=='line':return [part['a'],part['b']]
    # Chord sagitta <= .02 mm; analytical length remains in the shared record.
    r=part['radius_mm'];angle=math.radians(part['sweep_deg'])
    n=max(8,math.ceil(abs(angle)/(2*math.acos(max(-1,1-.02/r)))))
    return [[part['center'][0]+r*math.cos(math.radians(part['start_deg'])+angle*i/n),
             part['center'][1]+r*math.sin(math.radians(part['start_deg'])+angle*i/n)] for i in range(n+1)]


def bar_geometry(bar,r):
    seg=bar['segments'];shape=bar['shape'];p=r['input'];parts=[];allowances=[];notes=[]
    if shape=='stirrup':
        s=p[bar['member']];d=bar['diameter'];B=s['b_mm']-2*s['cover_mm']-d;H=s['h_mm']-2*s['cover_mm']-d
        rad=seg[1][1]/(2*math.pi);tail=seg[3][1]/2
        parts=[line((rad,0),(B-rad,0),'底直段'),arc((B-rad,rad),rad,-90,90,'右下角'),
               line((B,rad),(B,H-rad),'右直段'),arc((B-rad,H-rad),rad,0,90,'右上角'),
               line((B-rad,H),(rad,H),'顶直段'),arc((rad,H-rad),rad,90,90,'左上角'),
               line((0,H-rad),(0,rad),'左直段'),arc((rad,rad),rad,180,90,'左下角')]
        for i in range(2):
            center=[B+4*rad+tail, i*(2*rad+tail+30)+rad]
            a=arc(center,rad,0,135,'135°弯钩');parts.append(a);end=vertices(a)[-1]
            parts.append(line(end,(end[0]-tail/math.sqrt(2),end[1]-tail/math.sqrt(2)),'弯钩尾直段'))
        notes=['箍身与两端弯钩分解表示；接缝位置未定义。',f'中心线 B={B:g}，H={H:g}，R={rad:g}；尾直段各{tail:g}。']
    elif 'physical_path_mm' in bar:
        pts=bar['physical_path_mm'];xmin=min(x for x,y in pts);ymin=min(y for x,y in pts)
        pts=[[x-xmin,y-ymin] for x,y in pts]
        parts=[line(a,b) for a,b in zip(pts,pts[1:])]
        if shape=='l':notes=['按现有直段＋竖段模型；90°弯曲加工调整未计。']
    elif shape=='straight':parts=[line((0,0),(bar['length_mm'],0),'直筋')]
    elif shape=='hook':
        allowances=[dict(label=n,length_mm=v) for n,v in seg if '弯钩' in n]
        x=0
        for n,v in seg:
            if '弯钩' in n:continue
            parts.append(line((x,0),(x+v,0),n));x+=v
        notes=['两端180°弯钩缺少半径/尾段定义，仅另附局部示意。',
               '弯钩增加值 '+f'{sum(a["length_mm"] for a in allowances):g} mm 为经验附加量，不是圆弧长度。']
    elif shape=='u':
        h=seg[-1][1]/2;x=0;parts=[line((0,0),(0,h),'左竖段')]
        for n,v in seg[:-1]:parts.append(line((x,h),(x+v,h),n));x+=v
        parts.append(line((x,h),(x,0),'右竖段'));notes=['直段模型，弯曲加工调整未计。']
    elif shape=='l':
        h=seg[-1][1];x=0;parts=[line((0,0),(0,h),'端部竖段')]
        for n,v in seg[:-1]:parts.append(line((x,h),(x+v,h),n));x+=v
        notes=['直段模型，弯曲加工调整未计。']
    else:raise ValueError('未定义的钢筋几何：'+shape)
    pts=[v for part in parts for v in vertices(part)]
    box=[min(x for x,y in pts),min(y for x,y in pts),max(x for x,y in pts),max(y for x,y in pts)]
    length=sum(a['length_mm'] for a in parts)+sum(a['length_mm'] for a in allowances)
    if not math.isclose(length,bar['length_mm'],abs_tol=1e-6):raise ValueError(bar['mark']+'几何与长度记录不闭合')
    return dict(components=parts,allowances=allowances,bounds_mm=box,
                developed_mm=bar['length_mm'],rounded_mm=bar['rounded_mm'],notes=notes,
                comparison_line=[[0,0],[bar['length_mm'],0]])


def enrich_details(r):
    p=r['input'];g=p['geometry'];dims={};layout={}
    for m in MEMBERS:
        spans=[g['secondary_spacing_mm']]*5 if m=='slab' else g[m+'_axis_spans_mm']
        axis=[0]+list(accumulate(spans));w=p['secondary']['b_mm'] if m=='slab' else (p['main']['b_mm'] if m=='secondary' else g['column_width_mm'])
        wall=g['wall_axis_to_inner_face_mm'];chains=[]
        for i,L in enumerate(spans):
            a=wall if i==0 else w/2;b=wall if i==len(spans)-1 else w/2
            chains.append(dict(axis_mm=L,left_offset_mm=a,clear_mm=L-a-b,right_offset_mm=b,
                               start_mm=axis[i],end_mm=axis[i+1]))
        calc=([r['spans']['slab_edge_mm']]+[r['spans']['slab_inner_mm']]*3+[r['spans']['slab_edge_mm']]) if m=='slab' else ([r['spans']['secondary_edge_mm']]+[r['spans']['secondary_inner_mm']]*3+[r['spans']['secondary_edge_mm']] if m=='secondary' else [v*1000 for v in r['spans']['main_m']])
        dims[m]=dict(axis_mm=axis,chains=chains,support_width_mm=w,wall_axis_to_inner_face_mm=wall,
                     bearing_mm=g[m+'_bearing_mm'],wall_thickness_mm=None,depth_mm=p[m]['h_mm'],
                     mechanical_spans_mm=calc,intersections_mm=([a+L*f for a,L in zip(axis,spans) for f in (1/3,2/3)] if m=='main' else []))
        bars=[b for b in r['bars'] if b['member']==m]
        for b in bars:b['drawing']=bar_geometry(b,r)
        maxw=max(max(b['length_mm'],b['drawing']['bounds_mm'][2]-b['drawing']['bounds_mm'][0]) for b in bars)
        maxh=max(b['drawing']['bounds_mm'][3]-b['drawing']['bounds_mm'][1] for b in bars)
        scale=next((n for n in SCALES if maxw/n<=145 and maxh/n<=16),None)
        if scale is None:raise ValueError(MEMBERS[m]+'钢筋超出报告支持的绘图比例')
        # Every sheet uses the same physical width and pixel-to-mm mapping.
        layout[m]=dict(scale=scale,width_mm=170,pixels_per_mm=10,bars_per_page=3,
                       max_width_mm=maxw,max_height_mm=maxh,
                       pages=[ [b['mark'] for b in bars[i:i+3]] for i in range(0,len(bars),3)])
    r['dimension_geometry']=dims;r['bar_report_layout']=layout
    return r
