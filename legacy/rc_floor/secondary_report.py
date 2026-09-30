"""Report-only secondary-beam elevation. No changes to calculation/CAD records."""
import copy
import math
from figures import Canvas
from slab_report_figures import View,text
from dimension_scene import wall_profile


def layout(r):
    p=r['input'];s=p['secondary'];d=r['dimension_geometry']['secondary']
    g=copy.deepcopy(r['drawing_geometry']['secondary'])
    if len(g['axis_mm'])!=6:raise ValueError('次梁插图仅适用于现有五跨模型')
    g.update(h=s['h_mm'],main_h=p['main']['h_mm'],width=s['b_mm'],support=d['support_width_mm'],
             wall=d['wall_axis_to_inner_face_mm'],bearing=d['bearing_mm'],cover=s['cover_mm'],
             stirrup_diameter=s['stirrup_diameter_mm'],total=g['axis_mm'][-1],wall_thickness=None)
    if g['main_h']<=g['h'] or g['support']!=p['main']['b_mm']:
        raise ValueError('次梁插图：主梁支承尺寸记录不一致')
    g['extent']=[g['wall']-g['bearing'],g['total']-g['wall']+g['bearing']]
    g['controls']=[]
    for b in g['bars']:
        original=next(x for x in r['bars'] if x['mark']==b['mark'])
        length=sum(math.dist(a,z) for a,z in zip(b['path_mm'],b['path_mm'][1:]))
        if not math.isclose(length,original['length_mm'],abs_tol=.001):
            raise ValueError(b['mark']+'：路径长度与长度表不一致')
        if b['path_mm']!=original['physical_path_mm'] or (b['count'],b['diameter'])!=(original['count'],original['diameter']):
            raise ValueError(b['mark']+'：最终钢筋记录不一致')
        if not all(g['extent'][0]<=x<=g['extent'][1] and 0<=y<=g['h'] for x,y in b['path_mm']):
            raise ValueError(b['mark']+'：钢筋超出次梁混凝土范围')
        i=int(b['mark'].split('-')[1][1:]);role=b['role']
        if role=='J':continue
        row=r['secondary'][(0 if i in (1,5) else 2) if role=='D' else (1 if i in (1,4) else 3)]
        if (row['count'],row['diameter'])!=(b['count'],b['diameter']):raise ValueError(b['mark']+'：控制截面配筋与最终钢筋不同')
        if row['As_provided']+1e-6<row['As_required']:raise ValueError(b['mark']+'：采用面积小于控制所需面积')
        if not math.isclose(row['As_provided'],b['count']*math.pi*b['diameter']**2/4,abs_tol=.001):
            raise ValueError(b['mark']+'：采用面积与钢筋规格不一致')
        x=(g['axis_mm'][i-1]+g['axis_mm'][i])/2 if role=='D' else g['axis_mm'][i]
        g['controls'].append(dict(mark=b['mark'],role=role,x=x,y=b['path_mm'][0][1],
            name=f'第{i}跨 '+row['name'] if role=='D' else f'第{i}内支座',
            calc=row['As_calc'],required=row['As_required'],provided=row['As_provided'],
            count=b['count'],diameter=b['diameter']))
    return g


def concrete(v,g):
    left,right=g['extent'];h=g['h'];dep=h-g['main_h'];w=g['support']
    v.line([left,h],[right,h],2,'#666666')
    v.line([left,0],[left,h],2,'#666666');v.line([right,0],[right,h],2,'#666666')
    pts=[[left,0]]
    for x in g['axis_mm'][1:-1]:pts.extend([[x-w/2,0],[x-w/2,dep],[x+w/2,dep],[x+w/2,0]])
    pts.append([right,0]);v.poly(pts,2,'#666666')
    regions=[]
    for inner,sign in [(g['wall'],-1),(g['total']-g['wall'],1)]:
        edge=inner+sign*(g['bearing']+100)
        region=wall_profile(inner,edge,-180,h+180,[left,0,right,h],max(35,g['bearing']/5))
        regions.append(region)
        for a,b in region['outlines']+region['hatches']:v.line(a,b,1,'#666666')
    return regions


def bars(v,g):
    for b in g['bars']:
        if b['role']=='J':
            # Dash in physical coordinates: never move the erection bars vertically.
            for a,z in zip(b['path_mm'],b['path_mm'][1:]):
                length=math.dist(a,z)
                for start in range(0,math.ceil(length),100):
                    end=min(length,start+65)
                    v.line([a[j]+(z[j]-a[j])*start/length for j in (0,1)],
                           [a[j]+(z[j]-a[j])*end/length for j in (0,1)],2,'#666666')
        else:v.poly(b['path_mm'],3)
    # Only select stations already present in the common geometry.
    selected=set()
    for a,b in zip(g['axis_mm'],g['axis_mm'][1:]):
        available=[x for x in g['stirrup_stations_mm'] if a<x<b]
        for f in (.12,.15,.18):
            if available:selected.add(min(available,key=lambda x:abs(x-(a+(b-a)*f))))
    for x in selected:v.line([x,g['cover']],[x,g['h']-g['cover']],1,'#999999')
    return sorted(selected)


def figure(r):
    g=layout(r);c=Canvas(1600,w=2400);c.geometry=g
    text(c,70,16,'次梁配筋构造示意（五跨）',44)
    text(c,70,73,f"截面 {g['width']:g}×{g['h']:g} mm；中间主梁支承 {g['support']:g}×{g['main_h']:g} mm；面积单位 mm²",34)
    # Physical geometry uses the same scale in both directions.
    margin=max(g['bearing']+200,500);world=(-margin,-300,g['total']+margin,g['h']+300)
    v=View(c,(80,340,2240,95),world);c.overview_scale=v.k
    c.wall_regions=concrete(v,g);c.representative_stations=bars(v,g)
    for row in g['controls']:
        xx,yy=v.pt([row['x'],row['y']]);top=125 if row['role']=='F' else 475
        for j,t in enumerate([row['name'],f"计算 {row['calc']:.1f}",f"控制 {row['required']:.1f}",
                               f"采用 {row['provided']:.1f}",f"{row['mark']}  {row['count']}Φ{row['diameter']}"]):
            text(c,xx,top+j*38,t,36,'mt')
        end=top+193 if row['role']=='F' else top-10
        c.line([(xx,yy),(xx,end)],1,'#888888')
    for i,x in enumerate(g['axis_mm'][1:-1],1):
        xx,yy=v.pt([x,g['h']-g['main_h']]);text(c,xx,yy+10,'主梁',25,'mt')
    for a,b in zip(g['axis_mm'],g['axis_mm'][1:]):
        xa=v.pt([a,0])[0];xb=v.pt([b,0])[0];c.dim(xa,xb,709,f'{b-a:g}')
    # Zones stay at true x coordinates; their separate bracket is annotation only.
    for z in g['lap_zones']:
        xa=v.pt([z['start'],0])[0];xb=v.pt([z['end'],0])[0]
        c.line([(xa,459),(xa,451),(xb,451),(xb,459)],2)
        text(c,(xa+xb)/2,426,f"@{z['spacing']:g}",22,'mt')
    text(c,70,775,'左墙端放大 A（右端按实际记录镜像）',36)
    text(c,1250,775,'第一内支座放大 B',36)
    # Equal physical scales within each viewport. Titles state actual enlargement.
    a=View(c,(90,875,1000,330),(g['extent'][0]-140,-240,g['wall']+1400,g['h']+180))
    x=g['axis_mm'][1];reach=max(g['support']*2,800)
    b=View(c,(1280,875,1000,330),(x-reach,-g['main_h']+g['h']-100,x+reach,g['h']+120))
    for view,px in [(a,90),(b,1280)]:
        concrete(view,g);bars(view,g)
        text(c,px,817,f'局部 ×{view.k/v.k:.2f}，横竖同比例',28)
    # Leaders terminate at the actual bar paths, never at invented ends.
    j1=next(t for t in g['bars'] if t['mark']=='CL-J1');d1=next(t for t in g['bars'] if t['mark']=='CL-D1')
    for bar,label,px in [(j1,'CL-J1 架立筋',180),(d1,'CL-D1 底筋',670)]:
        point=a.pt(bar['path_mm'][0]);c.line([point,(px,1220)],1,'#777777');text(c,px,1230,label,32,'mt')
    text(c,1250,1230,'负筋 CL-F1 跨支座连续；底筋各自锚入。',31)
    text(c,1250,1274,'轮廓下凸为主梁，梁顶与次梁齐平。',31)
    erection=[f"{z['mark']} {z['count']}Φ{z['diameter']}" for z in g['bars'] if z['role']=='J']
    text(c,70,1334,'架立/连接筋：'+'；'.join(erection),29)
    close=sorted({z['spacing'] for z in g['lap_zones']})
    text(c,70,1380,f"箍筋 Φ{g['stirrup_diameter']:g}@{g['ordinary_spacing_mm']:g}（普通区）；搭接区 "+'/'.join(f'@{n:g}' for n in close)+'（范围见整体图短括线）。',31)
    text(c,70,1424,'箍筋示意，未逐根绘出；支承墙体外侧截断，墙厚未给定。',31)
    text(c,70,1468,'实线为受力纵筋，灰虚线为架立/连接筋；投影重合不表示焊接。端部弯曲加工调整沿用长度表说明。',30)
    text(c,70,1512,'计算＝承载力所需面积；控制＝计入最小配筋后的面积；采用＝本次最终配筋面积。',30)
    text(c,70,1556,'整体与局部均不拉伸几何；搭接及锚固数值详见同份说明书的编号钢筋长度记录。',30)
    c.detail_scales=[a.k,b.k]
    for x0,y0,x1,y1 in c.text_boxes:
        if not (0<=x0<x1<=c.w and 0<=y0<y1<=c.h):raise ValueError('次梁插图标注超出画布')
    return c
