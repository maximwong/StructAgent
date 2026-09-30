"""Report-only main-beam geometry, read from the existing model (millimetres)."""
import copy,math
from PIL import Image,ImageDraw,ImageFont
from figures import Canvas,font_path
from slab_report_figures import View,text,clip
from dimension_scene import wall_profile


def layout(r):
    p=r['input'];g=copy.deepcopy(r['dimension_geometry']['main'])
    g.update(slab_h=p['slab']['h_mm'],secondary_h=p['secondary']['h_mm'],secondary_w=p['secondary']['b_mm'],
             web_w=p['main']['b_mm'],h=p['main']['h_mm'],column_w=p['geometry']['column_width_mm'])
    if len(g['axis_mm'])!=4 or g['support_width_mm']!=g['column_w'] or g['depth_mm']!=g['h']:
        raise ValueError('主梁尺寸插图：三跨或支承尺寸记录不一致')
    if not all(math.isfinite(g[k]) and g[k]>0 for k in ('slab_h','secondary_h','secondary_w','web_w','h','column_w')):
        raise ValueError('主梁尺寸插图：尺寸须为正数')
    if not g['slab_h']<g['secondary_h']<g['h']:raise ValueError('主梁尺寸插图：板、次梁、主梁高度关系无效')
    for ch in g['chains']:
        if not math.isclose(ch['left_offset_mm']+ch['clear_mm']+ch['right_offset_mm'],ch['axis_mm'],abs_tol=1e-6):
            raise ValueError('主梁尺寸插图：尺寸链不闭合')
    total=g['axis_mm'][-1];wall=g['wall_axis_to_inner_face_mm'];bearing=g['bearing_mm']
    left=wall-bearing;right=total-left;g['extent']=[left,right]
    # Column height is not supplied: this is an explicitly truncated display window.
    g['column_display_depth']=min(g['h']*.6,500)
    g['column_full_height']=None;g['flange_calculation_width']=None
    g['section_window_halfwidth']=1.1*g['web_w']
    zs=g['h']-g['slab_h'];zb=g['h']-g['secondary_h'];bw=g['secondary_w']
    hidden=[];start=left
    for x in g['intersections_mm']:
        if x-bw/2<start or x+bw/2>right:raise ValueError('主梁尺寸插图：次梁交接位置冲突')
        hidden.extend([([start,zs],[x-bw/2,zs]),([x-bw/2,zs],[x-bw/2,zb]),
                       ([x-bw/2,zb],[x+bw/2,zb]),([x+bw/2,zb],[x+bw/2,zs])]);start=x+bw/2
    hidden.append(([start,zs],[right,zs]));g['hidden_projection']=hidden
    g['intersection_chain']=sorted(set(g['axis_mm']+g['intersections_mm']))
    return g


def dashed(v,a,b,axis=False):
    if hasattr(v,'dash'):
        return v.dash(a,b,axis)
    segment=clip(a,b,v.box)
    if not segment:return
    a,b=[v.pt(p) for p in segment];length=math.dist(a,b)
    if not length:return
    cycle=28 if axis else 14;dash=16 if axis else 8
    def at(t):return [a[j]+(b[j]-a[j])*min(t,length)/length for j in (0,1)]
    for t in range(0,math.ceil(length),cycle):
        v.c.line([at(t),at(t+dash)],1,'#777777')
        if axis and t+22<length:v.c.d.point(at(t+22),fill='#777777')


def longitudinal(v,g):
    left,right=g['extent'];h=g['h'];w=g['column_w'];dep=g['column_display_depth'];total=g['axis_mm'][-1]
    v.line([left,h],[right,h]);v.line([left,0],[left,h]);v.line([right,0],[right,h])
    start=left
    for x in g['axis_mm'][1:-1]:
        a,b=x-w/2,x+w/2
        v.line([start,0],[a,0]);v.line([a,0],[a,-dep]);v.line([b,-dep],[b,0])
        amp=min(w*.07,30)
        v.poly([[a,-dep],[x-w*.12,-dep],[x,-dep+amp],[x+w*.12,-dep-amp],[x+w*.25,-dep],[b,-dep]])
        start=b
    v.line([start,0],[right,0])
    for a,b in g['hidden_projection']:dashed(v,a,b)
    for x in g['axis_mm']:dashed(v,[x,-dep-70],[x,h+100],True)
    regions=[]
    for inner,sign in [(g['wall_axis_to_inner_face_mm'],-1),(total-g['wall_axis_to_inner_face_mm'],1)]:
        edge=inner+sign*(g['bearing_mm']+100)
        region=wall_profile(inner,edge,-dep,h+180,[left,0,right,h],max(35,g['bearing_mm']/6))
        regions.append(region)
        for a,b in region['outlines']+region['hatches']:v.line(a,b,1)
    return regions


def hdim(c,v,a,b,y,size=32):
    pa,pb=v.pt(a),v.pt(b);xa,xb=pa[0],pb[0]
    for p in (pa,pb):c.line([p,(p[0],y+7)],1,'#aaaaaa')
    c.line([(xa,y),(xb,y)],1)
    for xx in (xa,xb):c.line([(xx-4,y+6),(xx+4,y-6)],1)
    text(c,(xa+xb)/2,y-8,f'{abs(b[0]-a[0]):g}',size,'mb')
    c.dimension_records.append({'direction':'x','a':a,'b':b,'value_mm':abs(b[0]-a[0]),'pixels':abs(xb-xa),'scale':v.k})


def vdim(c,v,a,b,x):
    pa,pb=v.pt(a),v.pt(b);ya,yb=pa[1],pb[1]
    for p in (pa,pb):c.line([p,(x+6,p[1])],1,'#aaaaaa')
    c.line([(x,ya),(x,yb)],1)
    for yy in (ya,yb):c.line([(x-4,yy+5),(x+4,yy-5)],1)
    value=abs(b[1]-a[1]);font=ImageFont.truetype(font_path(),30);s=f'{value:g}';bb=font.getbbox(s)
    tile=Image.new('RGB',(bb[2]-bb[0]+4,bb[3]-bb[1]+4),'white');ImageDraw.Draw(tile).text((2-bb[0],2-bb[1]),s,font=font,fill='black')
    tile=tile.rotate(90,expand=True);loc=(round(x-tile.width-5),round((ya+yb-tile.height)/2))
    c.image.paste(tile,loc);c.text_boxes.append([*loc,loc[0]+tile.width,loc[1]+tile.height])
    c.dimension_records.append({'direction':'z','a':a,'b':b,'value_mm':value,'pixels':abs(yb-ya),'scale':v.k})


def figure(r):
    g=layout(r);c=Canvas(1500,w=2400);c.geometry=g;c.dimension_records=[]
    text(c,70,16,'主梁构件尺寸图（三跨）',44)
    text(c,70,72,'尺寸 mm；实线为可见轮廓，虚线为板底及次梁交接的遮挡投影。',34)
    total=g['axis_mm'][-1];h=g['h'];wall=g['wall_axis_to_inner_face_mm'];w=g['column_w'];left,right=g['extent']
    v=View(c,(90,240,2220,220),(left-220,-g['column_display_depth']-100,right+220,h+220))
    c.overview_scale=v.k;c.wall_regions=longitudinal(v,g)
    text(c,70,121,'次梁交接轴线分段',30)
    for a,b in zip(g['intersection_chain'],g['intersection_chain'][1:]):hdim(c,v,[a,h],[b,h],208)
    for ch in g['chains']:
        a=ch['start_mm'];b=ch['end_mm'];aa=a+ch['left_offset_mm'];bb=b-ch['right_offset_mm']
        hdim(c,v,[aa,0],[bb,0],510);hdim(c,v,[a,0],[b,0],594)
    text(c,75,633,'上层为净跨，下层为轴线跨度；柱下部截断（非全高）。',31)
    for xx,title in [(70,'A 左端墙支承'),(670,'B 柱支座纵向局部'),(1270,'C 右端墙支承'),(1870,'D 主梁 T 形截面')]:text(c,xx,710,title,33)
    dep=g['column_display_depth'];stub=max(g['bearing_mm'],h*.7)
    wa=(left-140,-dep-70,wall+stub,h+210)
    wc=(total-wall-stub,-dep-70,right+140,h+210)
    x=g['axis_mm'][1];wb=(x-w*1.7,-dep-70,x+w*1.7,h+160)
    views=[]
    for xpanel,world in [(90,wa),(690,wb),(1290,wc)]:
        detail=View(c,(xpanel,812,420,350),world);longitudinal(detail,g);views.append(detail)
        text(c,xpanel,767,f'局部 ×{detail.k/v.k:.2f}',28)
    a,b,cc=views
    hdim(c,a,[0,0],[wall,0],1210);hdim(c,a,[left,0],[wall,0],1280)
    hdim(c,cc,[total-wall,0],[total,0],1210);hdim(c,cc,[total-wall,0],[right,0],1280)
    hdim(c,b,[x-w/2,0],[x,0],1210);hdim(c,b,[x,0],[x+w/2,0],1260);hdim(c,b,[x-w/2,0],[x+w/2,0],1320)
    text(c,670,1340,'柱下部截断，非全高',27)
    # Cross-section is explicitly independent from the longitudinal column view.
    bw=g['web_w'];hs=g['slab_h'];side=g['section_window_halfwidth']
    t=View(c,(1880,812,355,350),(-side-30,-45,side+30,h+70));views.append(t)
    text(c,1870,767,f'截面 ×{t.k/v.k:.2f}；非柱支座',27)
    t.poly([[-side,h],[side,h]]);t.poly([[-side,h-hs],[-bw/2,h-hs],[-bw/2,0],[bw/2,0],[bw/2,h-hs],[side,h-hs]])
    # Broken plate edges express only a visible local window, not effective flange width.
    for sign in (-1,1):
        edge=sign*side;mid=h-hs/2;amp=min(18,hs*.16)
        t.poly([[edge,h],[edge,mid+amp],[edge-sign*amp,mid],[edge+sign*amp,mid-amp],[edge,h-hs]],1)
    dashed(t,[0,-30],[0,h+40],True)
    hdim(c,t,[-bw/2,0],[bw/2,0],1230)
    xr=t.pt([side,h])[0];vdim(c,t,[side,h-hs],[side,h],xr+43);vdim(c,t,[bw/2,0],[side,h],xr+102)
    text(c,1870,1280,'梁总高含板厚',28)
    text(c,1870,1320,'板翼局部截取，非计算翼缘宽',26)
    text(c,70,1380,'端部内层：墙轴线至墙内缘；端部外层：支承长度。二者均不代表墙厚。',31)
    text(c,70,1425,'支承墙体外侧截断，墙厚未给定；局部横竖同比例，尺寸为真实值。',31)
    c.detail_scales=[q.k for q in views]
    for x0,y0,x1,y1 in c.text_boxes:
        if not (0<=x0<x1<=c.w and 0<=y0<y1<=c.h):raise ValueError('主梁尺寸图标注超出画布')
    return c
