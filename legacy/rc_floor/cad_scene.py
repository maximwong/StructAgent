"""Editable CAD primitives from the report's adopted bars; no design formulas."""
import json,math,shutil
from pathlib import Path
from scene_base import Scene,sexpr,svg,bounds
from engine import fmt,spec

TITLES={'PLAN':'结构平面与板配筋','BEAMS':'梁配筋立面','DETAIL':'截面与构造及力学简图','ENVELOPE':'主梁内力包络','TABLE':'编号钢筋及长度','SLAB':'五跨板带与构造详图','DIMENSIONS':'板次梁主梁尺寸及支座','COEFF':'弯矩系数示意'}


def note(sc,x,y,text,size=140,chars=62):
    for i in range(0,len(text),chars):sc.text(x,y-i//chars*size*1.65,text[i:i+chars],size)


def make_scene(r):
    sc=Scene();p=r['input'];g=p['geometry'];W=sum(g['main_axis_spans_mm']);H=sum(g['secondary_axis_spans_mm']);space=g['secondary_spacing_mm'];cw=g['column_width_mm']
    sc.group('PLAN');sc.text(0,H+2000,p['project']+' 结构平面与板配筋',300)
    sc.text(0,H+1400,'尺寸单位mm；主梁三跨、次梁五跨；板配筋为代表板带，按标注间距布置。',170)
    wall=g['wall_axis_to_inner_face_mm'];sc.rect(-wall,-wall,W+2*wall,H+2*wall);sc.rect(wall,wall,W-2*wall,H-2*wall)
    mx=r['drawing_geometry']['main']['axis_mm'];sy=r['drawing_geometry']['secondary']['axis_mm']
    for j,y in enumerate(sy):
        sc.line(-700,y,W+500,y,'AXIS')
        if j not in (0,len(sy)-1):sc.rect(0,y-p['main']['b_mm']/2,W,p['main']['b_mm'])
        sc.circle(-1000,y,160,'AXIS');sc.text(-1060,y-55,chr(65+j),110)
        for x in mx[1:-1]:
            if j not in (0,len(sy)-1):sc.rect(x-cw/2,y-cw/2,cw,cw)
    for i,x in enumerate(mx):
        sc.line(x,-600,x,H+500,'AXIS');sc.circle(x,-950,160,'AXIS');sc.text(x-40,-1000,str(i+1),110)
    for k in range(1,round(W/space)):
        x=k*space;sc.rect(x-p['secondary']['b_mm']/2,0,p['secondary']['b_mm'],H)
    for a,b in zip(mx,mx[1:]):sc.dim([a,0],[b,0],[a,-1600])
    sc.dim([0,0],[W,0],[0,-2400])
    for a,b in zip(sy,sy[1:]):sc.dim([0,a],[0,b],[-1700,a],90)
    sc.dim([0,0],[0,H],[-2600,0],90)
    for k in range(round(W/space)):
        row=r['slab'][0 if k in (0,round(W/space)-1) else 2];mark='B1' if k in (0,round(W/space)-1) else 'B3';x=k*space;y=1500+(k%3)*700
        sc.poly([[x+140,y+80],[x+140,y],[x+space-140,y],[x+space-140,y+80]],'REBAR');sc.text(x+180,y+130,mark+' '+spec(row),110)
    for k in range(1,round(W/space)):
        idx=1 if k in (1,round(W/space)-1) else 3;bar=next(t for t in r['bars'] if t['mark']=='B'+str(idx+1));ext=bar['segments'][0][1];x=k*space;y=4400
        reach=ext+p['secondary']['b_mm']/2;sc.poly([[x-reach,y-60],[x-reach,y],[x+reach,y],[x+reach,y-60]],'REBAR');sc.text(x-reach,y+130,bar['mark']+' '+spec(r['slab'][idx]),105)
    sc.line(space*.45,700,space*.45,5300,'REBAR');sc.leader(space*.45,3300,2300,3500,'B5 分布筋 '+spec(r['distribution']),110)
    sc.leader(W*.5,sy[1],W*.5+500,sy[1]+700,'ZL '+str(p['main']['b_mm'])+'×'+str(p['main']['h_mm']),150)
    sc.leader(space,sy[2]+1000,space+600,sy[2]+1500,'CL '+str(p['secondary']['b_mm'])+'×'+str(p['secondary']['h_mm']),150)
    sc.text(0,-3100,'板厚'+str(p['slab']['h_mm'])+'；保护层'+str(p['slab']['cover_mm'])+'；B6墙边、B7墙角双向 Φ8@200，长度见编号表。',160)
    sc.text(0,-3500,'代表板带按未折减控制配筋；边界支承及节点仍须人工校核。',150)

    sc.group('BEAMS');sc.text(0,2850,'梁纵筋实际方案及箍筋布置',270)
    for member,y0 in [('main',-4200)]:
        geom=r['drawing_geometry'][member];s=p[member];length=geom['axis_mm'][-1];prefix='CL' if member=='secondary' else 'ZL'
        sc.rect(0,y0,length,s['h_mm']);sc.text(0,y0+s['h_mm']+1300,prefix+' '+str(s['b_mm'])+'×'+str(s['h_mm'])+'；普通双肢箍 Φ'+str(s['stirrup_diameter_mm'])+'@'+str(geom['ordinary_spacing_mm']),160)
        support=p['main']['b_mm'] if member=='secondary' else cw
        for x in geom['axis_mm']:sc.rect(x-support/2,y0-180,support,180)
        for x in geom['stirrup_stations_mm']:sc.line(x,y0+s['cover_mm'],x,y0+s['h_mm']-s['cover_mm'],'STIRRUP')
        for bar in geom['bars']:
            # Congested elevation lines are separated for legibility, x remains physical.
            n=int(bar['mark'].split('-')[1][1:]);dy=0 if bar['role']=='D' else 75*(n%2)
            pts=[[x,y+y0+dy] for x,y in bar['path_mm']];sc.poly(pts,'REBAR')
            a,b=pts[0][0],pts[-1][0];ly=y0-650 if bar['role']=='D' else y0+s['h_mm']+220+(n%2)*350
            if bar['role']=='J':ly=y0+s['h_mm']+850
            sc.text((a+b)/2-350,ly,bar['mark']+' '+str(bar['count'])+'Φ'+str(bar['diameter']),110)
        for i,z in enumerate(geom['lap_zones']):
            y=y0-1500-(i%2)*350;sc.dim([z['start'],y0],[z['end'],y0],[z['start'],y]);sc.text(z['start'],y-230,'搭接区箍筋@'+str(z['spacing']),100)
        for a,b in zip(geom['axis_mm'],geom['axis_mm'][1:]):sc.dim([a,y0],[b,y0],[a,y0-1000])
        if member=='main':
            sus=r['suspension'];sw=p['secondary']['b_mm']
            for a,b in zip(geom['axis_mm'],geom['axis_mm'][1:]):
                for f in [1/3,2/3]:
                    x=a+(b-a)*f
                    for side in [-1,1]:
                        for j in range(sus['per_side']):
                            sx=x+side*(sw/2+(j+.5)*sus['spacing_mm']);sc.line(sx,y0+25,sx,y0+s['h_mm']-25,'REBAR')
            sc.text(0,y0-2450,'交接处另加双肢箍：每侧'+str(sus['per_side'])+'道 Φ'+str(sus['diameter'])+'@'+str(sus['spacing_mm'])+'；总计'+str(sus['count'])+'道。',140)
    sc.text(0,-7700,'立面纵筋竖向错开仅为辨识；水平端点按计算结果。实际排布见截面，连接与锚固见编号表。',150)

    sc.group('DETAIL');sc.text(0,2500,'梁控制截面及搭接节点',270)
    for mi,member in enumerate(['secondary','main']):
        s=p[member];y0=-mi*3500
        for i,row in enumerate(r[member]):
            x0=i*1800;row=dict(row)
            if member=='main' and i==3:
                ev=next((x for x in r['joint_checks'] if x.get('member')=='main' and 'physical_count' in x),None)
                if ev:row.update(name='中跨上筋搭接区',count=ev['physical_count'],diameter=ev['diameter'],centres=ev['centres'],rows=ev['rows'],h0=ev['h0_mm'])
            scale=2;sc.rect(x0,y0,s['b_mm']*scale,s['h_mm']*scale);c=s['cover_mm']*scale;sc.rect(x0+c,y0+c,s['b_mm']*scale-2*c,s['h_mm']*scale-2*c,'STIRRUP')
            for x,y in row['centres']:sc.circle(x0+x*scale,y0+y*scale,row['diameter']*scale/2)
            sc.text(x0,y0+s['h_mm']*scale+400,('CL ' if mi==0 else 'ZL ')+row['name'],120);sc.text(x0,y0+s['h_mm']*scale+150,spec(row),120)
            sc.items.append(['DIM','DIM',[x0,y0],[x0+s['b_mm']*scale,y0],[x0,y0-200],0,.5]);sc.items.append(['DIM','DIM',[x0,y0],[x0,y0+s['h_mm']*scale],[x0-220,y0],90,.5])
            sc.text(x0,y0-520,'h0='+fmt(row['h0'],1)+'；排布'+str(row['rows']),100)
    note(sc,0,-4500,'截面放大2倍，DIM显示真实尺寸；仅绘计算受力侧钢筋。搭接区计入实际双倍钢筋，承载力仅计一组。')
    sc.text(0,-5300,'板构造：B6墙边、B7墙角两个方向 Φ8@200；伸出和弯折长度见编号表。',140)
    sus=r['suspension'];sc.text(0,-5800,'主次梁交接附加箍筋：范围 '+fmt(sus['range_mm'])+'mm，附加承载力 '+fmt(sus['capacity_kN'])+'kN。',140)

    sc.group('ENVELOPE');env=r['envelope'];total=sum(env['spans']);kx=18000/total
    sc.text(0,3500,'主梁内力包络及负筋抵抗范围',270)
    for shear,base in [(False,0),(True,-7500)]:
        maxv=max(abs(t['v']) for ca in env['cases'] for t in ca['segments']) if shear else max(max(abs(t['maximum']),abs(t['minimum'])) for t in env['points'])
        ky=2200/max(maxv,1);sc.line(0,base,18000,base,'AXIS');sc.text(0,base+2700,'V / kN' if shear else 'M / kN·m 正弯矩向下',160)
        for ca in env['cases']:
            pts=[]
            for t in ca['segments']:
                pts.extend([[t['x0']*kx,base+(t['v'] if shear else -t['m0'])*ky],[t['x1']*kx,base+(t['v'] if shear else -t['m1'])*ky]])
            sc.poly(pts,'AXIS')
        if shear:
            for key in ['vmin','vmax']:sc.poly([[t[k]*kx,base+t[key]*ky] for t in env['segments'] for k in ['x0','x1']],'ENV')
        else:
            for key in ['minimum','maximum']:sc.poly([[t['x']*kx,base-t[key]*ky] for t in env['points']],'ENV')
            for a,b,mu in r['material_regions']:
                xa=a/1000*kx;xb=b/1000*kx
                for xx in range(int(xa),int(xb),250):sc.line(xx,base+mu*ky,min(xx+140,xb),base+mu*ky,'REBAR')
        for j in [-1,1]:sc.text(-1200,base+j*2200,fmt(maxv*j*(1 if shear else -1),1),125)
        start=0
        for L in env['spans']:
            sc.line(start*kx,base-120,start*kx,base+120,'DIM');sc.text((start+L/2)*kx,base-3200,fmt(L)+'m',150);start+=L
    sc.text(0,-11600,'细线为各工况，红色为包络；弯矩虚线为负筋抵抗范围。横轴为计算跨度。',145)

    from scaled_cad import add_dimensions,bar_table
    add_dimensions(sc,r);bar_table(sc,r)
    from cad_sync import sync
    sync(sc,r)
    return sc


def export_drawing(r,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);sc=make_scene(r)
    from cad_sync import offsets as layout_offsets
    offsets=layout_offsets(sc.groups)
    # Keep the legacy data contract so old RF commands remain usable.
    with (out/'floor_data.dat').open('w',encoding='ascii') as f:
        f.write('(\n"RCFLOOR-1"\n')
        f.write('('+sexpr('OFFSETS')+' '+ ' '.join(sexpr([k]+v) for k,v in offsets.items())+')\n')
        for name,items in sc.groups.items():
            f.write('('+sexpr(name)+'\n'+'\n'.join(sexpr(o) for o in items)+')\n')
        f.write(')\n')
    payload={'version':'RCFLOOR-SCENE-2','groups':sc.groups,'offsets':offsets}
    (out/'drawing_scene.json').write_text(json.dumps(payload,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    bodies=[]
    for name,items in sc.groups.items():
        content=svg(items,TITLES[name]);(out/(name.lower()+'.svg')).write_text(content,encoding='utf-8');bodies.append('<h2>'+TITLES[name]+'</h2>'+content)
    (out/'preview.html').write_text('<!doctype html><meta charset="utf-8"><title>楼盖CAD预览</title><style>body{font-family:Microsoft YaHei;background:white;margin:30px}svg{width:100%;max-height:1100px;border:1px solid #ddd;margin-bottom:40px}</style><h1>与CAD共用图元数据的预览</h1><p>预览尺寸线简化显示，DWG中为真正DIM对象。</p>'+''.join(bodies),encoding='utf-8')
    shutil.copyfile(Path(__file__).with_name('RCFLOOR.lsp'),out/'RCFLOOR.lsp')
    return payload
