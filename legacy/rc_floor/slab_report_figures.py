"""Slab report illustrations from read-only, millimetre-based placement records."""
import math
from PIL import ImageFont
from figures import Canvas,font_path
from engine import spec
from dimension_scene import wall_profile
from slab_report_geometry import layout


def text(c,x,y,s,size=28,anchor=None):
    f=ImageFont.truetype(font_path(),size)
    c.d.text((x,y),s,font=f,fill='black',anchor=anchor)
    c.text_boxes=getattr(c,'text_boxes',[])+[list(c.d.textbbox((x,y),s,font=f,anchor=anchor))]


def clip(a,b,box):
    lo,hi=0.,1.;dx=b[0]-a[0];dy=b[1]-a[1]
    for v,d,mn,mx in [(a[0],dx,box[0],box[2]),(a[1],dy,box[1],box[3])]:
        if abs(d)<1e-10:
            if v<mn or v>mx:return None
        else:
            s,t=sorted(((mn-v)/d,(mx-v)/d));lo=max(lo,s);hi=min(hi,t)
    if lo>hi:return None
    return ([a[0]+lo*dx,a[1]+lo*dy],[a[0]+hi*dx,a[1]+hi*dy])


class View:
    def __init__(self,c,pixels,world):
        self.c=c;self.box=world
        x,y,w,h=pixels;a,b,d,e=world;self.k=min(w/(d-a),h/(e-b))
        self.ox=x+(w-(d-a)*self.k)/2-a*self.k
        self.oy=y+(h-(e-b)*self.k)/2+e*self.k
    def pt(self,p):return (self.ox+p[0]*self.k,self.oy-p[1]*self.k)
    def line(self,a,b,width=2,color='black'):
        seg=clip(a,b,self.box)
        if seg:self.c.line([self.pt(q) for q in seg],width,color)
    def poly(self,pts,width=2,color='black'):
        for a,b in zip(pts,pts[1:]):self.line(a,b,width,color)
    def rect(self,x1,z1,x2,z2):self.poly([[x1,z1],[x2,z1],[x2,z2],[x1,z2],[x1,z1]],1,'#666666')
    def bar(self,b):self.poly(b['path'],max(2,round(b['diameter']*self.k)))
    def dim(self,a,b,z,label=None):
        for p,q in [([a,0],[a,z]),([b,0],[b,z]),([a,z],[b,z])]:self.line(p,q,1,'#666666')
        for x in (a,b):
            xx,yy=self.pt([x,z]);self.c.line([(xx-4,yy+5),(xx+4,yy-5)],1)
        xx,yy=self.pt([(a+b)/2,z]);text(self.c,xx,yy+7,label or f'{abs(b-a):g}',25,'mt')


def concrete(v,g,side=None):
    h=g['h_mm'];wall=g['wall_face_mm'];total=g['total_mm'];bearing=g['bearing_mm']
    left,right=g['slab_extent_mm'];v.rect(left,0,right,h)
    for x in g['axis_mm'][1:-1]:v.rect(x-g['support_width_mm']/2,-max(h,110),x+g['support_width_mm']/2,0)
    regions=[]
    for inner,sign in [(wall,-1),(total-wall,1)]:
        if side=='left' and sign==1 or side=='right' and sign==-1:continue
        edge=inner+sign*(bearing+max(35,h*.5))
        region=wall_profile(inner,edge,-max(90,h),h+max(90,h),[left,0,right,h],max(12,bearing/6))
        regions.append(region)
        for a,b in region['outlines']+region['hatches']:v.line(a,b,1,'#777777')
    return regions


def leader(c,point,labelpos,label):
    x,y=point;lx,ly=labelpos
    c.line([(x,y),(lx,ly+19 if ly<y else ly-8)],1,'#555555')
    c.d.ellipse((x-3,y-3,x+3,y+3),fill='black')
    text(c,lx,ly,label,28,'mt')


def overview(r,g=None):
    g=g or layout(r);c=Canvas(520,w=1700);total=g['total_mm'];h=g['h_mm']
    text(c,45,20,'五跨代表板带配筋　尺寸 mm',34)
    text(c,45,70,f"板厚 {h:g}；保护层 {g['cover_mm']:g}；B5 分布筋 {spec(r['distribution'])}")
    extent=max(g['bearing_mm']+80,200)
    v=View(c,(60,145,1580,170),(-extent,-h-160,total+extent,h+170))
    c.wall_regions=concrete(v,g)
    for b in g['bars']:
        if b['role']!='corner':v.bar(b)
    for b in g['bars']:
        if b['role']=='bottom':
            x=sum(t[0] for t in b['path'])/2;idx=0 if b['mark']=='B1' else 2
            leader(c,v.pt([x,b['path'][0][1]]),(v.pt([x,0])[0],300),b['mark']+' '+spec(r['slab'][idx]))
        elif b['role']=='top':
            x=g['axis_mm'][b['support']];idx=1 if b['mark']=='B2' else 3
            leader(c,v.pt([x,b['path'][1][1]]),(v.pt([x,0])[0],112),b['mark']+' '+spec(r['slab'][idx]))
    text(c,65,350,'左墙端详图 A',27);text(c,1635,350,'右墙端详图 B',27,'rt')
    text(c,45,398,'支承墙体（外侧截断，墙厚未给定）；墙端另设 B6 构造筋，见节点图。',28)
    text(c,45,440,'分离式配筋：底筋伸入支座，上部负筋独立布置；端钩与支座节点见放大图。',28)
    text(c,45,482,'本图为五跨代表板带，非楼盖全部跨数；上下方向与水平方向采用相同几何比例。',27)
    c.geometry=g
    return c


def end_node(c,r,g,side,xpanel):
    total=g['total_mm'];h=g['h_mm'];wall=g['wall_face_mm'];bearing=g['bearing_mm']
    b6=next(b for b in g['bars'] if b['mark']=='B6' and b['side']==side)
    extent=b6['extension_mm'];low=wall-bearing-60;high=wall+extent+80
    world=(low,-h-40,high,h+85) if side=='left' else (total-high,-h-40,total-low,h+85)
    v=View(c,(xpanel+20,150,720,235),world)
    concrete(v,g,side)
    for b in g['bars']:
        if b['role']=='bottom' or b is b6:v.bar(b)
    text(c,xpanel+20,54,('A 左墙端' if side=='left' else 'B 右墙端')+'　局部放大',31)
    text(c,xpanel+20,101,f"上部 B6 Φ{b6['diameter']:g}@200；下部 B1 {spec(r['slab'][0])}",27)
    inner=wall if side=='left' else total-wall
    end=g['slab_extent_mm'][0 if side=='left' else 1]
    v.dim(min(inner,end),max(inner,end),-h-8,f'支承 {bearing:g}')
    for rec in g['bars']:
        if rec['role']=='bottom' and rec['span']==(1 if side=='left' else 5):
            pt=v.pt(rec['path'][0 if side=='left' else 1]);c.d.ellipse((pt[0]-5,pt[1]-5,pt[0]+5,pt[1]+5),outline='black',width=1)
    text(c,xpanel+20,415,f"B6：墙内 {b6['wall_straight_mm']:g}；伸入板内 {extent:g}；竖段 {b6['drop_mm']:g}",25)
    bottom=next(b for b in g['bars'] if b['role']=='bottom' and b['span']==(1 if side=='left' else 5))
    anchor=bottom['anchors'][0 if side=='left' else 1]
    text(c,xpanel+20,454,f'B1 墙内直段 {anchor:g}；圈点为端钩位置，弯钩另示。',25)
    text(c,xpanel+20,493,'墙外侧为截断边界；支承长度不代表墙厚。',25)


def details(r,g=None):
    g=g or layout(r);c=Canvas(1800,w=1700);h=g['h_mm'];width=g['support_width_mm']
    end_node(c,r,g,'left',40);end_node(c,r,g,'right',900)
    c.line([(45,550),(1655,550)],1,'#bbbbbb')
    text(c,60,578,'C 第一内支座节点　局部放大（中间支座同类，采用 B4）',31)
    top=next(b for b in g['bars'] if b['role']=='top' and b['support']==1)
    a,b=top['path'][1][0],top['path'][2][0];center=g['axis_mm'][1]
    text(c,60,627,f"B2 {spec(r['slab'][1])}；左伸出 {top['extensions'][0]:g} + 支座 {width:g} + 右伸出 {top['extensions'][1]:g}",28)
    v=View(c,(90,688,1520,245),(a-100,-max(h,100)-30,b+100,h+70))
    concrete(v,g)
    for rec in g['bars']:
        if rec['role']=='bottom' or rec is top:v.bar(rec)
    v.dim(center-width/2,center+width/2,-max(h,100)-10,f'支座 {width:g}')
    # Explicit bar-end symbol; it is an annotation, never a gap/extension in the path.
    for rec in g['bars']:
        if rec['role']=='bottom' and rec['span'] in (1,2):
            px,py=v.pt(rec['path'][1 if rec['span']==1 else 0])
            c.d.ellipse((px-6,py-6,px+6,py+6),outline='black',width=1)
    text(c,60,964,'底筋分别伸入支座，圈点为端点；上下筋投影相交不表示连接或同一根钢筋。',27)
    bottom=next(t for t in g['bars'] if t['role']=='bottom' and t['span']==1)
    text(c,60,1007,f"端钩按长度表单列附加量：B1 两端共 {bottom['allowance_mm']:g} mm；未确定弧半径及尾段。",26)
    # Explicitly symbolic local hook, separated from all true-scale geometry.
    c.line([(115,1090),(200,1090)],3)
    c.d.arc((185,1060,215,1090),270,90,fill='black',width=3)
    c.line([(200,1060),(160,1060)],3)
    text(c,265,1065,'180°端钩局部示意（非比例）；经验增加值不作为已知圆弧长度。',25)
    c.line([(45,1140),(1655,1140)],1,'#bbbbbb')
    text(c,60,1170,'D B5 分布筋　平面局部',30)
    text(c,890,1170,'E B7 墙角双向筋　上部平面局部',30)
    # Actual spacing, cropped segments. Break ticks label the unshown remainder.
    mainspace=r['slab'][0]['spacing'];dist=g['distribution']['spacing']
    size=max(2.7*mainspace,2.7*dist);vp=View(c,(80,1270,590,280),(0,0,size,size))
    for j in range(3):
        y=(j+.3)*mainspace
        vp.line([0,y],[size,y],2)
        x=(j+.3)*dist;vp.line([x,0],[x,size],3)
    text(c,60,1220,'B5 '+spec(r['distribution'])+'，与受力筋垂直',26)
    text(c,60,1540,'竖线：B5；横线：板底受力筋。',25)
    text(c,60,1582,'上下、左右边缘均为局部截取；不表示钢筋端点。',25)
    text(c,60,1624,'支承内直段、弯钩增加量及总长见 B5 长度表。',25)
    # Corner plane: outer sides deliberately broken and hatched, no wall thickness.
    corner=next(b for b in g['bars'] if b['role']=='corner' and b['side']=='left')
    reach=corner['extension_mm'];inside=corner['wall_straight_mm'];end=reach+70
    vp=View(c,(920,1260,650,290),(-bearing_for(g),-bearing_for(g),end,end))
    region=wall_profile(0,-bearing_for(g),-bearing_for(g),end,[-inside,0,end,end],max(15,g['bearing_mm']/6))
    for aa,bb in region['outlines']+region['hatches']:vp.line(aa,bb,1,'#888888')
    # Rotated second wall; exclude the slab footprint and its return into the wall.
    for aa,bb in region['outlines']+region['hatches']:vp.line([aa[1],aa[0]],[bb[1],bb[0]],1,'#888888')
    vp.line([0,0],[end,0],1);vp.line([0,0],[0,end],1)
    for j in range(2):
        station=40+200*j
        if station<end:
            vp.line([-inside,station],[reach,station],3)
            vp.line([station,-inside],[station,reach],3)
    text(c,890,1220,f"B7 Φ{corner['diameter']:g}@200；两个方向分别布置",26)
    text(c,890,1582,f'各向伸入板内 {reach:g}；墙内直段 {inside:g} mm。',25)
    text(c,890,1624,'竖向弯折见编号表；墙厚未给定，外侧截断。',25)
    text(c,60,1700,'各节点独立放大，节点内横纵同尺度；尺寸及钢筋位置均读取本次计算记录。',27)
    text(c,60,1745,'端钩局部示意不按比例；准确的加工弯曲尺寸仍需结合钢筋加工要求确定。',26)
    c.geometry=g
    return c


def bearing_for(g):return g['bearing_mm']+35


def generate(r,out):
    from pathlib import Path
    import json
    out=Path(out);g=layout(r)
    result=[]
    for name,canvas in [('slab_bars',overview(r,g)),('slab_bars_details',details(r,g))]:
        for box in getattr(canvas,'text_boxes',[]):
            if box[0]<0 or box[1]<0 or box[2]>canvas.w or box[3]>canvas.h:
                raise ValueError('板配筋插图标注超出图框：'+name+' '+str(box))
        if name=='slab_bars':
            path=out/(name+'.png');canvas.save(path);result.append(path)
        else:
            # Split only on the blank separator; no geometric rescaling on either sheet.
            for suffix,box in [('nodes',(0,0,1700,1140)),('plan',(0,1141,1700,1800))]:
                path=out/(name+'_'+suffix+'.png');canvas.image.crop(box).save(path,dpi=(254,254));result.append(path)
    (out/'slab_report_layout.json').write_text(json.dumps(g,ensure_ascii=False,indent=2),encoding='utf-8')
    return result
