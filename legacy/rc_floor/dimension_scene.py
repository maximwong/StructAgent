"""Physical dimension scenes, also consumed verbatim by the CAD exporter."""
from scene_base import Scene
from detail_geometry import MEMBERS
import math


def _without_rectangle(a,b,rect):
    """Subtract a closed beam rectangle from a line, including its boundary."""
    dx=b[0]-a[0];dy=b[1]-a[1];lo=0.;hi=1.
    for origin,delta,mn,mx in [(a[0],dx,rect[0],rect[2]),(a[1],dy,rect[1],rect[3])]:
        if abs(delta)<1e-10:
            if origin<mn or origin>mx:return [(a,b)]
        else:
            t,u=sorted(((mn-origin)/delta,(mx-origin)/delta))
            lo=max(lo,t);hi=min(hi,u)
    if lo>hi:return [(a,b)]
    def at(t):return [a[0]+t*dx,a[1]+t*dy]
    return [(at(t),at(u)) for t,u in [(0,lo),(hi,1)] if u-t>1e-9]


def wall_profile(inner,edge,bottom,top,beam,spacing):
    """Visible wall window with broken outer edge; no full wall thickness assumed.

    Intersect 45-degree hatch lines with the actual polygon, then subtract the
    beam footprint. Returned primitives are shared unchanged by report and CAD.
    """
    sign=1 if edge>inner else -1
    amp=min(abs(edge-inner)*.08,(top-bottom)*.06)
    mid=(bottom+top)/2
    outer=[[edge,bottom],[edge,mid-amp*2],[edge+sign*amp,mid-amp],
           [edge-sign*amp,mid+amp],[edge,mid+amp*2],[edge,top]]
    polygon=[[inner,bottom]]+outer+[[inner,top]]
    outlines=[];hatches=[]
    edges=list(zip(polygon,polygon[1:]+polygon[:1]))
    for a,b in edges:outlines.extend(_without_rectangle(a,b,beam))
    q=[y-x for x,y in polygon]
    for j in range(math.floor(min(q)/spacing),math.ceil(max(q)/spacing)+1):
        intercept=j*spacing;hits=[]
        for a,b in edges:
            qa=a[1]-a[0];qb=b[1]-b[0]
            # Half-open intersections avoid duplicate polygon vertices.
            if (qa<=intercept<qb) or (qb<=intercept<qa):
                t=(intercept-qa)/(qb-qa);hits.append(a[0]+t*(b[0]-a[0]))
        hits.sort()
        for x1,x2 in zip(hits[::2],hits[1::2]):
            hatches.extend(_without_rectangle([x1,x1+intercept],[x2,x2+intercept],beam))
    return dict(polygon=polygon,beam=beam,outlines=outlines,hatches=hatches)


def _draw_wall(sc,inner,edge,bottom,top,beam,spacing,transform=lambda p:p):
    region=wall_profile(inner,edge,bottom,top,beam,spacing)
    for a,b in region['outlines']+region['hatches']:
        sc.line(*transform(a),*transform(b))
    # Inspection metadata is not serialized into CAD data or calculation results.
    sc.wall_regions.append(region)


def dimension_scene(r,member):
    d=r['dimension_geometry'][member];sc=Scene();sc.group('DIMENSIONS');sc.wall_regions=[]
    axis=d['axis_mm'];total=axis[-1];w=d['support_width_mm'];wall=d['wall_axis_to_inner_face_mm'];h=d['depth_mm'];bearing=d['bearing_mm']
    # Annotation spacing is proportional to the sheet extent, geometry stays mm.
    step=total/25;ts=total/100;left=wall-bearing;right=total-left
    sc.text(0,3*step,MEMBERS[member]+'构件尺寸图（mm）',ts*1.15)
    sc.rect(left,0,right-left,h)
    for i,x in enumerate(axis):
        sc.line(x,-2.4*step,x,2.2*step,'AXIS')
        if 0<i<len(axis)-1:sc.rect(x-w/2,-h,w,h)
    for x,sign in [(wall,-1),(total-wall,1)]:
        # Crop/break line: this boundary deliberately does not imply wall thickness.
        edge=x+sign*(bearing+step*.2)
        _draw_wall(sc,x,edge,-step*.6,max(2*step,h+step*.3),
                   [left,0,right,h],min(abs(edge-x)*.65,step*.22))
    for ch in d['chains']:
        a=ch['start_mm'];b=ch['end_mm'];aa=a+ch['left_offset_mm'];bb=b-ch['right_offset_mm']
        sc.dim([aa,0],[bb,0],[aa,-step])
        sc.dim([a,0],[b,0],[a,-2*step])
    sc.text(0,-3*step,'上层：净跨；下层：轴线跨度。小尺寸在下方局部放大图标注。',ts)
    sc.text(0,-3.6*step,'支承墙体（外侧截断，墙厚未给定）；斜线仅表示可见墙体剖面。',ts*.85)
    if member=='main':
        for x in d['intersections_mm']:
            bw=r['input']['secondary']['b_mm'];sc.rect(x-bw/2,h,bw,h*.4);sc.line(x,h,x,step*1.7,'AXIS')
        positions=[0]+d['intersections_mm']+[total]
        # Include main axes so each intersection's physical axis offset is explicit.
        positions=sorted(set(positions+axis))
        for a,b in zip(positions,positions[1:]):sc.dim([a,h],[b,h],[a,step*1.7])
    # Three separate windows: left bearing, inner support and mirrored right bearing.
    pad=max(bearing,w)*.18;stub=max(bearing,w)*.55
    zoom=max(1,int(total*.25/max(bearing+pad+stub,2*w)))
    y=-6.5*step;clip_h=min(h,step*.42/zoom)
    sc.text(0,-4.35*step,f'左端支承 ×{zoom}',ts*.85)
    sc.text(total*.37,-4.35*step,f'内支座 ×{zoom}（局部截取，非全高）',ts*.85)
    sc.text(total*.75,-4.35*step,f'右端支承 ×{zoom}',ts*.85)
    for center,sign in [(total*.15,1),(total*.85,-1)]:
        edge=left-pad;end=wall+stub;mid=(edge+end)/2
        def pt(a,b):return [center+sign*(a-mid)*zoom,y+b*zoom]
        beam=[left,0,end,clip_h]
        sc.poly([pt(left,0),pt(end,0),pt(end,clip_h),pt(left,clip_h)],closed=True)
        _draw_wall(sc,wall,edge,-step*.6/zoom,step*.85/zoom,beam,
                   step*.16/zoom,lambda p:pt(*p))
        sc.line(*pt(0,-step*.6/zoom),*pt(0,step*.85/zoom),'AXIS')
        for a,b,level in [(0,wall,1.4),(left,wall,2.5)]:
            sc.items.append(['DIM','DIM',pt(a,0),pt(b,0),[center,y-level*step],0,1/zoom])
        sc.text(center-total*.13,y-3.4*step,f'轴线至墙内缘 {wall:g}',ts*.8)
        sc.text(center-total*.13,y-4*step,f'端部支承 {bearing:g}（非墙厚）',ts*.8)
    x=total*.5
    def pt(a,b):return [x+a*zoom,y+b*zoom]
    def dim(a,b,level):
        sc.items.append(['DIM','DIM',pt(a,0),pt(b,0),[x,y-level*step],0,1/zoom])
    sc.rect(x-w/2*zoom,y-clip_h*zoom,w*zoom,clip_h*zoom);sc.line(x-w*zoom,y,x+w*zoom,y)
    sc.line(x,y-clip_h*zoom,x,y+clip_h*zoom,'AXIS')
    # Half-widths on staggered levels avoid small-dimension text collisions.
    dim(-w/2,0,1.5);dim(0,w/2,2.2);dim(-w/2,w/2,3.1)
    sc.text(total*.38,y-4*step,f'支座 {w:g}；半宽 {w/2:g} + {w/2:g}',ts*.8)
    sc.text(0,y-5.2*step,'尺寸链：'+ ' + '.join(f'{d["chains"][0][k]:g}' for k in ['left_offset_mm','clear_mm','right_offset_mm'])+f' = {d["chains"][0]["axis_mm"]:g}；支承长度不代表墙厚。',ts*.9)
    # Main drawing dimensions need legible text sizes too (extension in Scene DIM).
    for o in sc.items:
        if o[0]=='DIM':
            if len(o)==6:o.append(1)
            o.append(ts*.8)
    return sc


def mechanical_scene(r,member):
    d=r['dimension_geometry'][member];sc=Scene();sc.group('MECHANICAL')
    Ls=d['mechanical_spans_mm'];total=sum(Ls);step=total/25;size=total/100;y=0
    sc.text(0,step*2.5,MEMBERS[member]+'力学计算简图（计算跨度，mm）',size*1.15)
    sc.line(0,0,total,0);x=0
    for L in Ls:
        sc.poly([[x,0],[x-step*.2,-step*.3],[x+step*.2,-step*.3],[x,0]],'CONC')
        sc.items.append(['DIM','DIM',[x,0],[x+L,0],[x,-step],0,1,size*.85])
        for f in ([1/3,2/3] if member=='main' else [j/7 for j in range(1,7)]):
            a=x+L*f;sc.line(a,step,a,0,'DIM');sc.poly([[a-step*.07,step*.12],[a,0],[a+step*.07,step*.12]],'DIM')
        x+=L
    sc.poly([[x,0],[x-step*.2,-step*.3],[x+step*.2,-step*.3],[x,0]])
    load=(f'G={r["loads"]["G_kN"]:.3f} kN；Q={r["loads"]["Q_kN"]:.3f} kN；每跨三分点作用' if member=='main' else f'g+q={r["loads"][member+"_g"]+r["loads"][member+"_q"]:.3f} kN/m（均布）')
    sc.text(0,step*1.5,load,size)
    return sc
