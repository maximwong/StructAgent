"""Fixed physical-size report renderers for shared dimension/bar geometry."""
import math
from PIL import ImageFont
from figures import Canvas,font_path
from detail_geometry import MEMBERS,vertices
from dimension_scene import dimension_scene
from scene_base import bounds


def dimension_figure(r,member):
    if member=='main':
        from main_dimension_report import figure
        return figure(r)
    scene=dimension_scene(r,member);items=scene.items
    xmin,ymin,xmax,ymax=bounds(items);k=1600/(xmax-xmin);c=Canvas(math.ceil((ymax-ymin)*k)+80,w=1700)
    def pt(p):return ((p[0]-xmin)*k+50,(ymax-p[1])*k+20)
    for o in items:
        typ=o[0]
        if typ=='LINE':c.line([pt(o[2]),pt(o[3])],2)
        elif typ=='POLY':c.line([pt(p) for p in o[3]+([o[3][0]] if o[2] else [])],2)
        elif typ=='TEXT':
            size=max(24,round(o[3]*k));c.d.text(pt(o[2]),o[5],font=ImageFont.truetype(font_path(),size),fill='black',anchor='ls')
        elif typ=='DIM':
            a,b,loc,angle=o[2:6];aa=[a[0],loc[1]];bb=[b[0],loc[1]]
            for u,v in [(a,aa),(b,bb),(aa,bb)]:c.line([pt(u),pt(v)],1)
            for v in [aa,bb]:
                x,y=pt(v);c.line([(x-5,y+7),(x+5,y-7)],2)
            x,y=pt([(a[0]+b[0])/2,loc[1]])
            value=abs(a[0]-b[0])*(o[6] if len(o)>6 else 1)
            c.text(x,y-10,f'{value:g}',28,'mb')
    if member=='slab':
        from report_support_detail import replace_slab_support
        replace_slab_support(c,r,pt,k)
    return c


def shapes(r,member,page):
    layout=r['bar_report_layout'][member];marks=layout['pages'][page]
    bars=[next(b for b in r['bars'] if b['mark']==mark) for mark in marks]
    c=Canvas(100+len(bars)*500,w=1700);k=10/layout['scale']
    c.text(45,20,f'{MEMBERS[member]}编号钢筋　统一比例 1:{layout["scale"]}　尺寸 mm　图宽170mm',32)
    for i,b in enumerate(bars):
        y=85+i*500;g=b['drawing'];box=g['bounds_mm'];origin=[65,y+210]
        c.text(45,y,b['mark']+' '+b['use']+' '+str(b['count'])+'Φ'+str(b['diameter']),32)
        def draw_parts(ox,oy,scale):
            for part in g['components']:
                c.line([(ox+(xx-box[0])*scale,oy-(yy-box[1])*scale) for xx,yy in vertices(part)],3)
        draw_parts(*origin,k)
        # Small parts retain their true primary size; enlargement is separately labelled.
        width=box[2]-box[0];height=box[3]-box[1]
        if b['shape'] in ('l','u','stirrup') and height>0:
            detail_parts=g['components'] if width*k<300 else [min((part for part in g['components'] if part['kind']=='line'),key=lambda part:abs(part['b'][0]-part['a'][0]))]
            if b['shape']=='stirrup':detail_parts=g['components'][-2:]
            pts=[p for part in detail_parts for p in vertices(part)];x0=min(x for x,z in pts);y0=min(z for x,z in pts)
            dw=max(x for x,z in pts)-x0;dh=max(z for x,z in pts)-y0
            mult=max(1,min(8,300/max(dw*k,1),100/max(dh*k,1)))
            c.text(1240,y+320,f'局部 ×{mult:.2f}（非主体）',24)
            if dw==0:c.text(1280,y+410,f'竖段 {dh:g} mm',24)
            for part in detail_parts:c.line([(1240+(xx-x0)*k*mult,y+465-(yy-y0)*k*mult) for xx,yy in vertices(part)],3)
        if b['shape']=='hook':
            c.text(1240,y+320,'端钩局部示意（非比例）',24)
            c.line([(1280,y+375),(1330,y+375),(1330,y+410),(1220,y+410)],3)
            c.text(1240,y+440,'半径与尾段待定',24)
        # This line expresses total developed length, not the bar's shape width.
        yline=y+255;end=65+g['developed_mm']*k
        c.line([(65,yline),(end,yline)],2,'#555555')
        for xx in (65,end):c.line([(xx,yline-6),(xx,yline+6)],2)
        c.text(65,y+270,f'展开总长对照线 L={g["developed_mm"]:.3f}；取整={g["rounded_mm"]:g}',28)
        formula=' + '.join(f'{v:.3f}'.rstrip('0').rstrip('.') for _,v in b['segments'])+f' = {b["length_mm"]:.3f}'
        c.text(65,y+312,formula,28)
        notes=g['notes'] or ['主体按中心线实际长度绘制；各分段名称见本节长度计算。']
        yy=y+353
        for note in notes:
            for start in range(0,len(note),45):
                c.text(65,yy,note[start:start+45],24);yy+=30
        c.line([(45,y+475),(1650,y+475)],1,'#cccccc')
    return c
