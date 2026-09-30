"""Editable CAD from the report's validated millimetre layouts. No design rules."""
import math,copy
from scene_base import Scene,bounds
from slab_report_figures import clip,concrete as slab_concrete
from slab_report_geometry import layout as slab_layout
from secondary_report import layout as secondary_layout,concrete as secondary_concrete
from main_dimension_report import layout as main_layout,longitudinal
from report_support_detail import geometry as support_geometry
from dimension_scene import dimension_scene,mechanical_scene,wall_profile
from figures import slab_coeff_layout,coeff_text
from engine import spec


class View:
    def __init__(self,sc,origin=(0,0),zoom=1,box=(-1e9,-1e9,1e9,1e9)):
        self.sc=sc;self.origin=origin;self.zoom=zoom;self.box=box
    def pt(self,p):return [self.origin[0]+p[0]*self.zoom,self.origin[1]+p[1]*self.zoom]
    def line(self,a,b,width=2,color='black',layer='CONC'):
        seg=clip(a,b,self.box)
        if seg:self.sc.line(*self.pt(seg[0]),*self.pt(seg[1]),layer)
    def poly(self,pts,width=2,color='black',layer='CONC'):
        for a,b in zip(pts,pts[1:]):self.line(a,b,layer=layer)
    def rect(self,x1,y1,x2,y2):self.poly([[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]])
    def dash(self,a,b,axis=False):self.line(a,b,layer='CENTER' if axis else 'HIDDEN')
    def bar(self,b,path='path'):
        # POLY preserves a full millimetre centreline for length inspection.
        pts=b[path]
        if all(self.box[0]<=x<=self.box[2] and self.box[1]<=y<=self.box[3] for x,y in pts):
            self.sc.poly([self.pt(p) for p in pts],'ERECT' if b.get('role')=='J' else 'REBAR')
        else:self.poly(pts,layer='ERECT' if b.get('role')=='J' else 'REBAR')
    def dim(self,a,b,loc,angle=0,size=100):
        self.sc.items.append(['DIM','DIM',self.pt(a),self.pt(b),self.pt(loc),angle,1/self.zoom,size])


def label(sc,x,y,s,size=120,center=False):
    # Conservative centering; actual entities remain standard editable TEXT.
    if center:x-=sum(.6 if ord(c)<128 else 1 for c in s)*size*.4
    sc.text(x,y,s,size)


def stack(sc,group,parts):
    from scaled_cad import moved
    sc.group(group);top=0
    for part in parts:
        a,b,c,d=bounds(part.items);dy=top-d
        sc.items.extend(moved(part.items,0,dy));top=b+dy-2400


def t_section(sc,v,width,height,slab,halfwing,title,width_level=-200,foot_level=-350):
    v.poly([[-halfwing,height],[halfwing,height]])
    v.poly([[-halfwing,height-slab],[-width/2,height-slab],[-width/2,0],[width/2,0],[width/2,height-slab],[halfwing,height-slab]])
    for s in (-1,1):
        x=s*halfwing;m=height-slab/2;amp=min(18,slab*.16)
        v.poly([[x,height],[x,m+amp],[x-s*amp,m],[x+s*amp,m-amp],[x,height-slab]])
    v.dash([0,-60],[0,height+70],True)
    v.dim([-width/2,0],[width/2,0],[0,width_level])
    v.dim([halfwing,height-slab],[halfwing,height],[halfwing+180,height],90)
    v.dim([width/2,0],[halfwing,height],[halfwing+420,0],90)
    x,y=v.pt([-halfwing,height]);label(sc,x,y+500,title,150)
    label(sc,x,y+250,f'局部 ×{v.zoom:g}；梁总高含板厚',100)
    x,y=v.pt([-halfwing,foot_level]);label(sc,x,y,'板翼局部截取，非计算翼缘宽',100)


def slab_dimensions(r):
    sc=dimension_scene(r,'slab');d=r['dimension_geometry']['slab'];total=d['axis_mm'][-1];step=total/25
    def inset(o):
        pts=o[2:5] if o[0]=='DIM' else o[2:4] if o[0]=='LINE' else o[3] if o[0]=='POLY' else [o[2]]
        x=sum(p[0] for p in pts)/len(pts);y=sum(p[1] for p in pts)/len(pts)
        return total*.345<x<total*.70 and -11*step<y<-3.95*step
    sc.items[:]=[o for o in sc.items if not inset(o)]
    g=support_geometry(r);H=g['beam_total_height_mm'];h=g['slab_thickness_mm'];w=g['support_width_mm']
    zoom=max(1,min(4,int((5*step-650)/H)));v=View(sc,(total*.5,-5.3*step-H*zoom),zoom)
    t_section(sc,v,w,H,h,1.2*w,'板—次梁完整T形内支座',-420,-570)
    v.dim([-w/2,0],[0,0],[0,-130],size=90);v.dim([0,0],[w/2,0],[0,-270],size=90)
    # Keep the original final dimension-chain note below the enlarged detail.
    for o in sc.items:
        if o[0]=='TEXT' and o[5].startswith('尺寸链：'):o[2][1]=min(o[2][1],bounds(sc.items)[1]-300)
    return sc


def main_dimensions(r):
    g=main_layout(r);sc=Scene();sc.group('D');v=View(sc);longitudinal(v,g)
    h=g['h'];total=g['axis_mm'][-1];w=g['column_w'];wall=g['wall_axis_to_inner_face_mm'];left,right=g['extent']
    label(sc,0,h+2000,'主梁构件尺寸图：三跨；虚线为板底及次梁遮挡投影',180)
    for a,b in zip(g['intersection_chain'],g['intersection_chain'][1:]):v.dim([a,h],[b,h],[a,h+900])
    for ch in g['chains']:
        a,b=ch['start_mm'],ch['end_mm'];v.dim([a+ch['left_offset_mm'],0],[b-ch['right_offset_mm'],0],[a,-1200]);v.dim([a,0],[b,0],[a,-1900])
    label(sc,0,-2600,'柱下部截断（非全高）；墙厚未给定，墙外侧截断。',130)
    base=-6500;zoom=3
    for side,cx in [('left',1700),('right',12600)]:
        world=(left-150,-g['column_display_depth']-100,wall+700,h+200) if side=='left' else (total-wall-700,-g['column_display_depth']-100,right+150,h+200)
        mid=(world[0]+world[2])/2;vv=View(sc,(cx-mid*zoom,base),zoom,world);longitudinal(vv,g)
        a,b=(0,wall) if side=='left' else (total-wall,total);c,d=(left,wall) if side=='left' else (total-wall,right)
        vv.dim([a,0],[b,0],[a,-550]);vv.dim([c,0],[d,0],[c,-850])
        label(sc,cx-1400,base+h*zoom+950,('左' if side=='left' else '右')+'墙端 ×3：内层轴线至内缘，外层支承长度',110)
    x=g['axis_mm'][1];vv=View(sc,(6900-x*zoom,base),zoom,(x-650,-g['column_display_depth']-80,x+650,h+120));longitudinal(vv,g)
    for a,b,y in [(x-w/2,x,-550),(x,x+w/2,-750),(x-w/2,x+w/2,-1000)]:vv.dim([a,0],[b,0],[a,y])
    label(sc,5600,base+h*zoom+950,'柱支座纵向局部 ×3；下部截断，非全高',110)
    t_section(sc,View(sc,(18000,base),4),g['web_w'],h,g['slab_h'],g['section_window_halfwidth'],'主梁T形截面（非柱支座）')
    return sc


def secondary_scene(r):
    g=secondary_layout(r);sc=Scene();sc.group('BEAMS');v=View(sc);secondary_concrete(v,g)
    h=g['h'];label(sc,0,h+2300,f"次梁五跨构造配筋 {g['width']:g}×{h:g}；面积 mm^2",220)
    for b in g['bars']:v.bar(b,'path_mm')
    for row in g['controls']:
        x=row['x'];y=h+1700 if row['role']=='F' else -1200
        for j,t in enumerate([row['name'],f"计算 {row['calc']:.1f}；控制 {row['required']:.1f}",f"采用 {row['provided']:.1f}",f"{row['mark']} {row['count']}Φ{row['diameter']}"]):label(sc,x,y-j*250,t,145,True)
        sc.line(x,row['y'],x,y-1000 if row['role']=='F' else y+200,'DIM')
    stations=g['stirrup_stations_mm']
    for a,b in zip(g['axis_mm'],g['axis_mm'][1:]):
        for f in (.12,.15,.18):
            x=min(stations,key=lambda q:abs(q-(a+(b-a)*f)));v.line([x,g['cover']],[x,h-g['cover']],layer='STIRRUP')
        v.dim([a,0],[b,0],[a,-2900],size=130)
    for z in g['lap_zones']:
        sc.poly([[z['start'],-650],[z['start'],-500],[z['end'],-500],[z['end'],-650]],'DIM')
        label(sc,(z['start']+z['end'])/2,-450,f"@{z['spacing']:g}",90,True)
    label(sc,0,-3600,'箍筋示意，未逐根绘出；普通区 Φ'+str(g['stirrup_diameter'])+'@'+str(g['ordinary_spacing_mm'])+'；短括线为搭接区。',140)
    label(sc,0,-4000,'；'.join(b['mark']+' '+str(b['count'])+'Φ'+str(b['diameter']) for b in g['bars'] if b['role']=='J'),130)
    label(sc,0,-4400,'架立/连接筋用虚线；投影重合不表示焊接。墙厚未知；端弯加工调整见长度表。',130)
    for title,cx,mid,box in [('左墙端',2500,700,(g['extent'][0]-100,-250,1700,h+180)),('第一内支座',13000,g['axis_mm'][1],(g['axis_mm'][1]-900,h-g['main_h']-100,g['axis_mm'][1]+900,h+120))]:
        zoom=4;vv=View(sc,(cx-mid*zoom,-8500),zoom,box);secondary_concrete(vv,g)
        for b in g['bars']:vv.bar(b,'path_mm')
        label(sc,cx-2500,-8500+h*zoom+1100,title+' ×4（右墙端镜像）；钢筋端点依照实际记录',140)
    return sc


def slab_scenes(r):
    g=slab_layout(r);sc=Scene();sc.group('SLAB');v=View(sc);slab_concrete(v,g);h=g['h_mm'];total=g['total_mm']
    label(sc,0,1900,'五跨代表板带配筋（非楼盖全部跨数）',200)
    for b in g['bars']:
        if b['role']=='corner':continue
        v.bar(b)
        if b['role'] in ('bottom','top'):
            i=(0 if b['mark']=='B1' else 2) if b['role']=='bottom' else (1 if b['mark']=='B2' else 3)
            x=(b['path'][0][0]+b['path'][-1][0])/2;y=-700 if b['role']=='bottom' else 650
            label(sc,x,y,b['mark']+' '+spec(r['slab'][i]),100,True)
    label(sc,0,1400,f"板厚 {h:g}；保护层 {g['cover_mm']:g}；B5 {spec(r['distribution'])}",130)
    label(sc,0,-1200,'分离式配筋；底筋伸入支座，负筋跨支座；墙厚未给定，外侧截断。',110)
    for a,b in zip(g['axis_mm'],g['axis_mm'][1:]):v.dim([a,0],[b,0],[a,-1700],size=100)
    # Left and right wall nodes share the report's exact B1/B6 paths.
    for side,cx in [('left',1700),('right',8500)]:
        sign=1 if side=='left' else -1;wall=g['wall_face_mm'] if sign==1 else total-g['wall_face_mm'];reach=next(b['extension_mm'] for b in g['bars'] if b['mark']=='B6')
        box=(g['slab_extent_mm'][0]-80,-max(h,110)-40,wall+reach+80,h+100) if sign==1 else (wall-reach-80,-max(h,110)-40,g['slab_extent_mm'][1]+80,h+100)
        mid=(box[0]+box[2])/2;vv=View(sc,(cx-mid*4,-5000),4,box);slab_concrete(vv,g,side)
        for b in g['bars']:
            if b['role']=='bottom' or b['mark']=='B6' and b['side']==side:vv.bar(b)
        end=g['slab_extent_mm'][0 if side=='left' else 1];vv.dim([end,0],[wall,0],[end,-h-180])
        label(sc,cx-1600,-3700,('左' if side=='left' else '右')+'墙端 ×4；B6 Φ8@200；B1端钩增加量另列',110)
    top=next(b for b in g['bars'] if b['role']=='top' and b['support']==1);x=g['axis_mm'][1];w=g['support_width_mm']
    box=(top['path'][0][0]-100,-max(h,110)-70,top['path'][-1][0]+100,h+70);vv=View(sc,(-x*4,-9000),4,box);slab_concrete(vv,g)
    for b in g['bars']:
        if b['role']=='bottom' or b is top:vv.bar(b)
    for a,b,y in [(top['path'][1][0],x-w/2,-h-160),(x-w/2,x+w/2,-h-320),(x+w/2,top['path'][2][0],-h-160)]:vv.dim([a,0],[b,0],[a,y])
    label(sc,-2700,-7800,'第一内支座 ×4：B2 '+spec(r['slab'][1])+'；其余中间支座采用B4',130)
    label(sc,-2700,-11000,'上下筋投影相交不表示连接。端钩经验增加量不作为已知弧长。',110)
    for i,mark in enumerate(('B1','B3','B5')):
        b=next(x for x in r['bars'] if x['mark']==mark);extra=sum(v for n,v in b['segments'] if '弯钩' in n)
        label(sc,5300,-8200-i*350,f'{mark} 两端弯钩经验附加 {extra:g} mm',110)
    sc.poly([[5600,-10100],[6000,-10100],[6000,-9900],[5700,-9900]],'REBAR');label(sc,5300,-10500,'端钩局部示意（非比例），半径及尾段未定',100)
    # B5 local plane with actual spacings, using the same stations as the report.
    y0=-19000;ms=r['slab'][0]['spacing'];ds=g['distribution']['spacing'];size=max(2.7*ms,2.7*ds);vv=View(sc,(1000,y0),4)
    for j in range(3):
        vv.line([0,(j+.3)*ms],[size,(j+.3)*ms],layer='REBAR');vv.line([(j+.3)*ds,0],[(j+.3)*ds,size],layer='STIRRUP')
    vv.dim([.3*ds,0],[1.3*ds,0],[0,-120]);label(sc,1000,y0+size*4+500,'B5 分布筋 '+spec(r['distribution'])+'：平面局部 ×4',130)
    label(sc,1000,y0-1100,'四边局部截取，不表示钢筋端点；支承内直段与附加量见长度表。',100)
    b=next(b for b in g['bars'] if b['role']=='corner' and b['side']=='left');reach=b['extension_mm'];inside=b['wall_straight_mm'];end=reach+70;crop=g['bearing_mm']+35;vv=View(sc,(7000,y0),4)
    reg=wall_profile(0,-crop,-crop,end,[-inside,0,end,end],max(15,g['bearing_mm']/6))
    for a,z in reg['outlines']+reg['hatches']:
        vv.line(a,z);vv.line([a[1],a[0]],[z[1],z[0]])
    vv.line([0,0],[end,0]);vv.line([0,0],[0,end])
    for j in range(2):
        s=40+200*j
        if s<end:vv.line([-inside,s],[reach,s],layer='REBAR');vv.line([s,-inside],[s,reach],layer='REBAR')
    label(sc,6400,y0+end*4+500,f"B7 Φ{b['diameter']:g}@200 双向筋：平面局部 ×4",130)
    label(sc,6400,y0-1200,f'各向墙内直段 {inside:g}；伸入板内 {reach:g}；竖向弯折见编号表。',110)
    return sc


def coefficients(r,member):
    if member=='slab':Ls,mids,sups=slab_coeff_layout(r)
    else:
        sp=r['spans'];Ls=[sp['secondary_edge_mm']]+[sp['secondary_inner_mm']]*3+[sp['secondary_edge_mm']]
        rows=r['secondary'];mids=[rows[0],rows[2],rows[2],rows[2],rows[0]];sups=[rows[1],rows[3],rows[3],rows[1]]
    sc=Scene();sc.group('C');total=sum(Ls);size=max(100,total/110)
    label(sc,0,5*size,('板' if member=='slab' else '次梁')+'弯矩系数示意（本次结果）',size*1.3)
    sc.line(0,0,total,0);x=0
    moment_scale=size*1.5/max(abs(row['M_kNm']) for row in mids+sups)
    for i,L in enumerate(Ls):
        sc.poly([[x,0],[x-100,-150],[x+100,-150],[x,0]])
        a=0.0 if i==0 else sups[i-1]['M_kNm'];b=0.0 if i==4 else sups[i]['M_kNm'];m=mids[i]['M_kNm']
        points=[]
        for j in range(33):
            t=j/32;val=2*a*(t-.5)*(t-1)-4*m*t*(t-1)+2*b*t*(t-.5)
            points.append([x+t*L,-val*moment_scale])
        sc.poly(points,'ENV')
        label(sc,x+L/2,-m*moment_scale-size*1.4,coeff_text(mids[i]),size,True)
        if i:label(sc,x,-a*moment_scale+size*.4,coeff_text(sups[i-1]),size,True)
        sc.items.append(['DIM','DIM',[x,0],[x+L,0],[x,-4*size],0,1,size*.8]);x+=L
    sc.poly([[x,0],[x-100,-150],[x+100,-150],[x,0]])
    label(sc,0,-6*size,'M=αm(g+q)l0^2；系数读取计算结果；正负系数分别对应跨中与支座。',size*.75)
    label(sc,0,-7.5*size,'细线为控制弯矩插值示意，非弹性包络；内支座板带连续。',size*.75)
    return sc


def sync(sc,r):
    from scaled_cad import moved
    secondary=secondary_scene(r);sc.groups['BEAMS'].extend(moved(secondary.items,0,15000))
    stack(sc,'SLAB',[slab_scenes(r)])
    dims=[slab_dimensions(r),dimension_scene(r,'secondary'),main_dimensions(r)]
    for scene in dims:
        for o in scene.items:
            if o[1]=='AXIS':o[1]='CENTER'
    stack(sc,'DIMENSIONS',dims)
    stack(sc,'COEFF',[coefficients(r,'slab'),coefficients(r,'secondary')])
    sc.items=sc.groups['TABLE']


def offsets(groups):
    # Existing five groups remain together; extra report figures occupy a new column.
    result={'PLAN':[0,0]};low=bounds(groups['PLAN'])[1]
    for key in ('BEAMS','DETAIL'):
        a,b,c,d=bounds(groups[key]);dy=low-2000-d;result[key]=[0,dy];low=b+dy
    right=max(bounds(groups[k])[2] for k in ('PLAN','BEAMS','DETAIL'))+6000
    result.update(ENVELOPE=[right,13000],TABLE=[right,-3000])
    extra=max(bounds(groups[k])[2]+result[k][0] for k in ('ENVELOPE','TABLE'))+6000;top=25000
    for key in ('SLAB','DIMENSIONS','COEFF'):
        a,b,c,d=bounds(groups[key]);dy=top-d;result[key]=[extra-a,dy];top=b+dy-2400
    return result
