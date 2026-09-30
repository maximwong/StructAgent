"""Deterministic black-and-white engineering figures; every label uses results."""
from pathlib import Path
import math
from PIL import Image, ImageDraw, ImageFont
from engine import fmt, spec


def font_path():
    import os
    paths=[Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'/x for x in ['simsun.ttc','simhei.ttf','msyh.ttc']]
    paths += [Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for p in paths:
        if p.exists():return str(p)
    raise RuntimeError('未找到中文字体。请安装宋体、黑体或Noto Sans CJK。')


class Canvas:
    def __init__(self,h=650,w=1600):
        self.image=Image.new('RGB',(w,h),'white');self.d=ImageDraw.Draw(self.image);self.w=w;self.h=h
        self.fonts={n:ImageFont.truetype(font_path(),n) for n in [24,28,32,36,40]}
    def text(self,x,y,t,size=32,anchor=None):self.d.text((x,y),str(t),font=self.fonts[size],fill='black',anchor=anchor)
    def line(self,pts,width=3,fill='black'):self.d.line(pts,fill=fill,width=width)
    def arrow(self,x,y1,y2):
        self.line([(x,y1),(x,y2)],2);self.line([(x-7,y2-12),(x,y2),(x+7,y2-12)],2)
    def support(self,x,y):
        self.line([(x,y),(x-14,y+23),(x+14,y+23),(x,y)],2);self.line([(x-25,y+27),(x+25,y+27)],2)
    def dim(self,x1,x2,y,label):
        self.line([(x1,y),(x2,y)],2)
        for x in [x1,x2]:self.line([(x-5,y-7),(x+5,y+7)],2)
        self.text((x1+x2)/2,y+10,label,28,'mt')
    def save(self,path):self.image.save(path,dpi=(254,254))


def scheme(r,member):
    c=Canvas(450);p=r['input'];sp=r['spans']
    if member=='slab':Ls=[sp['slab_edge_mm']]+[sp['slab_inner_mm']]*3+[sp['slab_edge_mm']];w=r['loads']['slab_g']+r['loads']['slab_q']
    elif member=='secondary':Ls=[sp['secondary_edge_mm']]+[sp['secondary_inner_mm']]*3+[sp['secondary_edge_mm']];w=r['loads']['secondary_g']+r['loads']['secondary_q']
    else:Ls=[x*1000 for x in sp['main_m']];w=0
    scale=1400/sum(Ls);start=100;y=240
    c.line([(start,y),(1500,y)],4)
    c.text(100,35,('g+q='+fmt(w)+' kN/m') if w else 'G='+fmt(r['loads']['G_kN'])+' kN；Q='+fmt(r['loads']['Q_kN'])+' kN')
    c.support(start,y)
    for L in Ls:
        end=start+L*scale
        c.support(end,y);c.dim(start,end,320,fmt(L)+' mm')
        if w:
            for j in range(1,7):c.arrow(start+(end-start)*j/7,145,y-3)
            c.line([(start,145),(end,145)],2)
        else:
            for f in [1/3,2/3]:
                x=start+(end-start)*f;c.arrow(x,130,y-3);c.text(x,95,'G+Q',28,'mt')
        start=end
    return c


def slab_coeff_layout(r):
    """Coefficient-diagram layout read from stored results; never recalculates.

    Returns the five display spans plus the row driving each span mid and each
    internal support. The representative strip is symmetric because the input
    validation pins equal axis spans and one edge/inner calculation span.
    """
    sp=r['spans']
    if r['loads']['slab_q']/r['loads']['slab_g']>3 or max(sp['slab_edge_mm'],sp['slab_inner_mm'])/min(sp['slab_edge_mm'],sp['slab_inner_mm'])>1.1:
        raise ValueError('超出塑性内力重分布系数法适用范围，不绘制弯矩系数示意图。')
    Ls=[sp['slab_edge_mm']]+[sp['slab_inner_mm']]*3+[sp['slab_edge_mm']]
    rows=r['slab']
    mids=[rows[0],rows[2],rows[2],rows[2],rows[0]]
    sups=[rows[1],rows[3],rows[3],rows[1]]
    return Ls,mids,sups


def coeff_text(x):
    sign='' if x['alpha_num']>0 else '-'
    return sign+str(abs(x['alpha_num']))+'/'+str(x['alpha_den'])


def slab_moment_coefficients(r):
    """Continuous-slab moment coefficient diagram in the sample-1 layout."""
    c=Canvas(650);v=r['loads']
    Ls,mids,sups=slab_coeff_layout(r)
    scale=1300/sum(Ls);x0=150;y=310
    k=110/max(max(abs(x['M_kNm']) for x in mids+sups),1e-9)
    xs=[x0]
    for L in Ls:xs.append(xs[-1]+L*scale)
    c.text(60,20,'g+q='+fmt(v['slab_g']+v['slab_q'])+' kN/m（1m宽板带）',32)
    # One continuous slab line through every support; no internal hinges.
    c.line([(x0,y),(xs[-1],y)],5)
    for i,x in enumerate(xs):
        c.support(x,y)
        c.text(x,y+40,'墙支承' if i in (0,5) else '次梁支承',24,'ma')
    # Sketched distribution: ordinates are the stored control moments only.
    for i in range(5):
        a=0.0 if i==0 else sups[i-1]['M_kNm']
        b=0.0 if i==4 else sups[i]['M_kNm']
        m=mids[i]['M_kNm']
        pts=[]
        for j in range(33):
            t=j/32
            val=2*a*(t-.5)*(t-1)-4*m*t*(t-1)+2*b*t*(t-.5)
            pts.append((xs[i]+t*(xs[i+1]-xs[i]),y+val*k))
        c.line(pts,2,'#555555')
    for i,x in enumerate(mids):
        c.text((xs[i]+xs[i+1])/2,y+x['M_kNm']*k+14,coeff_text(x),32,'ma')
    for i,x in enumerate(sups):
        c.text(xs[i+1],y+x['M_kNm']*k-12,coeff_text(x),32,'mb')
    sx=x0
    for L in Ls:
        c.dim(sx,sx+L*scale,520,fmt(L)+' mm');sx+=L*scale
    c.text(60,570,'板带在内支座处连续（非简支拼接）；细线为弯矩分布示意，绘于受拉一侧：跨中板底受拉为正，内支座板顶受拉为负。',24)
    c.text(60,602,'M=αm(g+q)l0²，系数αm与弯矩读取自本次计算结果，与弯矩计算表同源；超过五跨的规则板带按五跨代表区段绘制。',24)
    return c


def plan(r):
    c=Canvas(1150);g=r['input']['geometry'];W=sum(g['main_axis_spans_mm']);H=sum(g['secondary_axis_spans_mm']);k=min(1200/W,850/H);x0=250;y0=100
    for i in range(10):
        x=x0+i*g['secondary_spacing_mm']*k;c.line([(x,y0),(x,y0+H*k)],2)
    for j in range(6):
        y=y0+j*g['secondary_axis_spans_mm'][0]*k;c.line([(x0,y),(x0+W*k,y)],5)
        for i in range(4):
            x=x0+i*g['main_axis_spans_mm'][0]*k;c.d.rectangle((x-7,y-7,x+7,y+7),outline='black',width=3)
    for i in range(3):c.dim(x0+i*W*k/3,x0+(i+1)*W*k/3,y0+H*k+45,fmt(W/3))
    c.text(40,1030,'粗线：主梁；细线：次梁/支承轴；方框：柱/墙支点。尺寸单位mm。',28)
    c.text(x0+W*k+30,400,'5×'+fmt(H/5),28)
    c.text(x0,30,'单向板短跨方向 →',32)
    return c


def patterns(r):
    c=Canvas(1100)
    for i,case in enumerate(r['envelope']['cases']):
        x=90+(i%2)*790;y=160+(i//2)*250
        c.text(x,y-110,'活载 '+case['pattern'],32)
        c.line([(x,y),(x+620,y)],3)
        for s in range(4):c.support(x+s*620/3,y)
        for s,v in enumerate(case['pattern']):
            if v=='1':
                for f in [1/3,2/3]:c.arrow(x+(s+f)*620/3,y-65,y-4)
    return c


def envelope(r,shear=False,material=False):
    c=Canvas(730);env=r['envelope'];total=sum(env['spans']);pts=env['points'];k=1400/total
    maximum=max(abs(t['v']) for ca in env['cases'] for t in ca['segments']) if shear else max(max(abs(t['maximum']),abs(t['minimum'])) for t in pts)
    if material:maximum=max(maximum,max(x['Mu_kNm'] for x in r['main']))
    scale=240/max(maximum,1);base=360
    c.line([(100,base),(1500,base)],2);c.text(40,20,'V / kN' if shear else 'M / kN·m',32)
    for i in range(-2,3):
        value=maximum*i/2;y=base+(value*scale if not shear else -value*scale)
        c.line([(95,y),(1500,y)],1,'#dddddd');c.text(5,y,fmt(value,1),24,'lm')
    for case in env['cases']:
        line=[]
        for s in case['segments']:
            if shear:line.extend([(100+s['x0']*k,base-s['v']*scale),(100+s['x1']*k,base-s['v']*scale)])
            else:line.extend([(100+s['x0']*k,base+s['m0']*scale),(100+s['x1']*k,base+s['m1']*scale)])
        c.line(line,1,'#aaaaaa')
    if shear:
        for key in ['vmax','vmin']:
            line=[]
            for s in env['segments']:line.extend([(100+s['x0']*k,base-s[key]*scale),(100+s['x1']*k,base-s[key]*scale)])
            c.line(line,5)
    else:
        for key in ['maximum','minimum']:c.line([(100+t['x']*k,base+t[key]*scale) for t in pts],5)
    sx=0
    for L in env['spans']:
        c.support(100+sx*k,base);c.dim(100+sx*k,100+(sx+L)*k,640,fmt(L)+' m');sx+=L
    c.support(1500,base)
    if material:
        sx=0;half=r['input']['geometry']['column_width_mm']/2000
        for L in env['spans'][:-1]:
            sx+=L;xa=100+(sx-half)*k;xb=100+(sx+half)*k
            c.d.rectangle((xa,base-250,xb,base+250),fill='#eeeeee',outline='#bbbbbb')
        for a,b,mu in r['material_regions']:
            xa=100+a/1000*k;xb=100+b/1000*k;y=base-mu*scale
            # Dashed material capacity: positive/negative distinction remains monochrome.
            for x in range(int(xa),int(xb),18):c.line([(x,y),(min(x+10,xb),y)],4)
        c.text(650,28,'实线：需求；虚线：抵抗弯矩',28)
        c.text(650,75,'灰带：柱内，梁截面从柱边验算',28)
    else:c.text(720,28,'粗线：包络；细线：各工况',28)
    return c


def sections(r,member):
    c=Canvas(860);p=r['input'];s=p[member];rows=r[member];prefix='CL' if member=='secondary' else 'ZL'
    for i,x in enumerate(rows):
        if member=='main' and i==3:
            event=next((e for e in r['joint_checks'] if e.get('member')=='main' and 'physical_count' in e),None)
            if event:
                x=dict(x,name='中跨上筋搭接区',count=event['physical_count'],diameter=event['diameter'],h0=event['h0_mm'],rows=event['rows'],centres=event['centres'])
        cx=215+i*390;top=170;scale=min(410/s['h_mm'],210/s['b_mm']);w=s['b_mm']*scale;h=s['h_mm']*scale;left=cx-w/2
        c.text(cx,45,x['name'],28,'mt');c.text(cx,95,spec(x),32,'mt')
        c.d.rectangle((left,top,left+w,top+h),outline='black',width=3)
        off=s['cover_mm']*scale;c.d.rectangle((left+off,top+off,left+w-off,top+h-off),outline='black',width=2)
        for px,py in x['centres']:
            rr=max(x['diameter']*scale/2,4);xx=left+px*scale;yy=top+h-py*scale
            c.d.ellipse((xx-rr,yy-rr,xx+rr,yy+rr),fill='black')
        # Uncalculated opposite-face bars are explicitly omitted in this section view.
        c.dim(left,left+w,top+h+35,str(s['b_mm']))
        c.text(cx,710,'h0='+fmt(x['h0'],1),28,'mt');c.text(cx,754,'排布 '+str(x['rows']),28,'mt')
    c.text(40,815,'搭接区承载力只计一组；其余截面仅画计算受力侧钢筋。',28)
    return c


def beam_bars(r,member):
    if member=='secondary':
        from secondary_report import figure
        return figure(r)
    p=r['input'];g=p['geometry'];ax=g[member+'_axis_spans_mm'];N=len(ax);total=sum(ax);k=1400/total;prefix='CL' if member=='secondary' else 'ZL';c=Canvas(710)
    x0=100;top=270;bottom=440;sx=0
    c.d.rectangle((100,top,1500,bottom),outline='black',width=2)
    for i,L in enumerate(ax):
        c.support(100+sx*k,bottom+15)
        bot=next(t for t in r['bars'] if t['mark']==f'{prefix}-D{i+1}')
        c.line([(100+sx*k+6,bottom-20),(100+(sx+L)*k-6,bottom-20)],5)
        c.text(100+(sx+L/2)*k,490,bot['mark']+' '+str(bot['count'])+'Φ'+str(bot['diameter']),24,'mt')
        c.dim(100+sx*k,100+(sx+L)*k,590,fmt(L))
        sx+=L
    c.support(1500,bottom+15)
    for item in r['drawing_geometry'][member]['bars']:
        if item['role']=='D':continue
        idx=int(item['mark'].split('-')[1][1:]);pts=[]
        for xx,yy in item['path_mm']:
            pts.append((100+xx*k,bottom-yy/p[member]['h_mm']*(bottom-top)+(idx%2)*8))
        c.line(pts,4)
        xx=(item['path_mm'][0][0]+item['path_mm'][-1][0])/2
        c.text(100+xx*k,95 if item['role']=='J' else (150 if idx%2 else 195),item['mark']+' '+str(item['count'])+'Φ'+str(item['diameter']),24,'mt')
    for xx in r['drawing_geometry'][member]['stirrup_stations_mm']:
        x=100+xx*k;c.line([(x,top+5),(x,bottom-5)],1,'#aaaaaa')
    shear=r[member+'_shear'];spacing=min(t['spacing'] for t in shear)
    c.text(100,28,prefix+' 截面 '+str(p[member]['b_mm'])+'×'+str(p[member]['h_mm'])+'；普通箍筋 Φ'+str(p[member]['stirrup_diameter_mm'])+'@'+str(spacing),32)
    c.text(100,665,'纵筋端点按实际长度定位；箍筋含搭接区加密，交接处附加箍另计。',28)
    return c


def slab_bars(r):
    from slab_report_figures import overview
    return overview(r)



def generate(r,out):
    from scaled_figures import shapes,dimension_figure
    out=Path(out);out.mkdir(parents=True,exist_ok=True);result={}
    factories={'plan':lambda:plan(r),'patterns':lambda:patterns(r),'moment_envelope':lambda:envelope(r),'shear_envelope':lambda:envelope(r,True),'material':lambda:envelope(r,material=True),'slab_moment_coefficients':lambda:slab_moment_coefficients(r)}
    for member in ['slab','secondary','main']:
        factories[member+'_dimensions']=lambda m=member:dimension_figure(r,m)
        factories[member+'_scheme']=lambda m=member:scheme(r,m)
        if member!='slab':
            factories[member+'_sections']=lambda m=member:sections(r,m)
            factories[member+'_bars']=lambda m=member:beam_bars(r,m)
        files=[]
        for pg in range(len(r['bar_report_layout'][member]['pages'])):
            f=out/(member+f'_shapes_{pg+1}.png');shapes(r,member,pg).save(f);files.append(f)
        result[member+'_shapes']=files
    for name,factory in factories.items():
        path=out/(name+'.png');factory().save(path);result[name]=[path]
    from slab_report_figures import generate as slab_report
    result['slab_bars']=slab_report(r,out)
    return result
