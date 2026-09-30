"""Arrange shared real-size bar geometry and dimension scenes in CAD."""
from detail_geometry import MEMBERS,vertices
from dimension_scene import dimension_scene,mechanical_scene
from scene_base import bounds


def moved(items,dx,dy):
    import copy
    result=copy.deepcopy(items)
    for o in result:
        pts=o[2:5] if o[0]=='DIM' else o[2:4] if o[0]=='LINE' else o[3] if o[0]=='POLY' else [o[2]]
        for pt in pts:pt[0]+=dx;pt[1]+=dy
    return result


def add_dimensions(sc,r):
    sc.items=sc.groups['DETAIL'];bottom=bounds(sc.items)[1]-1800
    for m in MEMBERS:
        for scene in [mechanical_scene(r,m)]:
            box=bounds(scene.items);dy=bottom-box[3]
            sc.items.extend(moved(scene.items,0,dy));bottom=box[1]+dy-1800


def bar_table(sc,r):
    sc.group('TABLE');sc.text(0,2400,'编号钢筋：主体按毫米1:1；展开总长对照线亦为1:1',240)
    sc.text(0,1950,'已知弯曲用真实ARC圆弧；经验附加量单列；局部放大不改变主体。',145)
    x=0
    for member,title in MEMBERS.items():
        bars=[b for b in r['bars'] if b['member']==member];maxlen=max(b['length_mm'] for b in bars)
        sc.text(x,1300,title+'（报告主体统一比例1:'+str(r['bar_report_layout'][member]['scale'])+'）',200)
        y=0
        for b in bars:
            data=b['drawing'];box=data['bounds_mm'];height=box[3]-box[1];width=box[2]-box[0]
            # Keep a common baseline irrespective of the category's longest bar.
            sc.text(x,y+750,b['mark']+' '+b['use']+' '+str(b['count'])+'Φ'+str(b['diameter']),125)
            for part in data['components']:
                if part['kind']=='arc':sc.arc([x+part['center'][0]-box[0],y+part['center'][1]-box[1]],part['radius_mm'],part['start_deg'],part['sweep_deg'])
                else:sc.poly([[x+a-box[0],y+z-box[1]] for a,z in vertices(part)],'REBAR')
            sc.dim([x,y],[x+width,y],[x,y-300])
            if height>0:sc.dim([x,y],[x,y+height],[x-350,y],90)
            sc.line(x,y-720,x+data['developed_mm'],y-720,'AXIS')
            sc.items.append(['DIM','DIM',[x,y-720],[x+data['developed_mm'],y-720],[x,y-1000],0,1,100])
            sc.text(x,y-1250,f'展开总长 L={data["developed_mm"]:.3f}；取整 {data["rounded_mm"]:g}',110)
            sc.text(x,y-1480,' + '.join(f'{v:.3f}'.rstrip('0').rstrip('.') for _,v in b['segments']),100)
            for j,note in enumerate(data['notes']):sc.text(x,y-1700-j*210,note,100)
            if b['shape'] in ('l','u','stirrup'):
                parts=data['components'] if width<2000 else [min((part for part in data['components'] if part['kind']=='line'),key=lambda part:abs(part['b'][0]-part['a'][0]))]
                pts=[p for part in parts for p in vertices(part)];xmin=min(a for a,z in pts);ymin=min(z for a,z in pts)
                dw=max(a for a,z in pts)-xmin;dh=max(z for a,z in pts)-ymin
                zoom=max(1,min(4,3200/max(dw,1),800/max(dh,1)));xx=x+maxlen+800
                sc.text(xx,y+950,f'局部 ×{zoom:.2f}；尺寸为真实值',115)
                for part in parts:
                    if part['kind']=='arc':sc.arc([xx+(part['center'][0]-xmin)*zoom,y+(part['center'][1]-ymin)*zoom],part['radius_mm']*zoom,part['start_deg'],part['sweep_deg'])
                    else:sc.poly([[xx+(a-xmin)*zoom,y+(z-ymin)*zoom] for a,z in vertices(part)],'REBAR')
                if dw>0:sc.items.append(['DIM','DIM',[xx,y],[xx+dw*zoom,y],[xx,y-300],0,1/zoom,110])
                if dh>0:sc.items.append(['DIM','DIM',[xx,y],[xx,y+dh*zoom],[xx-250,y],90,1/zoom,110])
            if b['shape']=='hook':
                xx=x+maxlen+800;sc.text(xx,y+600,'180°端钩局部示意（非比例）',110)
                sc.poly([[xx+600,y+250],[xx+800,y+250],[xx+800,y],[xx,y]],'REBAR')
                sc.text(xx,y-300,'半径/尾段未定义；经验增加值单列',100)
            y-=max(3000,height+2600)
        x+=maxlen+5500
