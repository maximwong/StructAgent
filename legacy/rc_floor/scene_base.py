"""Translate calculation results into reviewable CAD primitives and SVG sheets.

AutoLISP reads the non-executable data file and creates model-space entities.
No reinforcement fabrication lengths or bar-bending schedule are inferred.
"""
import html
import json
import math
from pathlib import Path

LAYERS={'CONC':'混凝土','REBAR':'钢筋','STIRRUP':'箍筋','DIM':'标注','TEXT':'文字','AXIS':'轴线','ENV':'内力包络','CENTER':'点划轴线','HIDDEN':'遮挡轮廓','ERECT':'架立筋'}


class Scene:
    def __init__(self): self.groups={};self.items=[]
    def group(self,name): self.items=[];self.groups[name]=self.items
    def line(self,x1,y1,x2,y2,layer='CONC'): self.items.append(['LINE',layer,[x1,y1],[x2,y2]])
    def poly(self,pts,layer='CONC',closed=False): self.items.append(['POLY',layer,bool(closed),pts])
    def rect(self,x,y,w,h,layer='CONC'): self.poly([[x,y],[x+w,y],[x+w,y+h],[x,y+h]],layer,True)
    def circle(self,x,y,r,layer='REBAR'): self.items.append(['CIRCLE',layer,[x,y],r])
    def arc(self,center,r,start,sweep,layer='REBAR'):self.items.append(['ARC',layer,list(center),r,start,sweep])
    def text(self,x,y,text,size=125,rotation=0): self.items.append(['TEXT','TEXT',[x,y],size,rotation,text])
    def dim(self,p1,p2,loc,angle=0): self.items.append(['DIM','DIM',p1,p2,loc,angle])
    def leader(self,x,y,tx,ty,text,size=125):
        self.poly([[x,y],[tx,ty],[tx+max(300,len(text)*size*.62),ty]],'DIM')
        self.poly([[x,y],[x+75,y+35],[x+35,y+75]],'DIM',True)
        self.text(tx,ty+size*.3,text,size)


def spec(row,slab=False):
    return ('Φ%d@%d'%(row['diameter'],row['spacing']) if slab else '%dΦ%d'%(row['count'],row['diameter']))


def rows_text(row):
    return '%d排(%s)'%(len(row['rows']),'+'.join(map(str,row['rows'])))


def lisp_string(s):
    # ASCII exchange: AutoCAD text entities interpret \U+XXXX as Unicode glyphs.
    out=''
    for c in s:
        if ord(c)>127: out+='\\U+%04X'%ord(c)
        elif c in '\\"': out+='\\'+c
        else: out+=c
    return '"'+out.replace('\\U+','\\\\U+')+'"'


def sexpr(x):
    if isinstance(x,bool): return 'T' if x else 'nil'
    if isinstance(x,str):return lisp_string(x)
    if isinstance(x,(int,float)):return '%.8f'%x
    return '('+' '.join(sexpr(v) for v in x)+')'


def bounds(items):
    xx=[];yy=[]
    for o in items:
        if o[0] in ('LINE','DIM'):pts=o[2:5] if o[0]=='DIM' else o[2:4]
        elif o[0]=='POLY':pts=o[3]
        elif o[0] in ('CIRCLE','ARC'):pts=[[o[2][0]-o[3],o[2][1]-o[3]],[o[2][0]+o[3],o[2][1]+o[3]]]
        else:
            width=len(o[5])*o[3]*.75
            pts=[o[2],[o[2][0]+(o[3] if o[4] else width),o[2][1]+(width if o[4] else o[3])]]
        for x,y in pts:xx.append(x);yy.append(y)
    return min(xx)-500,min(yy)-500,max(xx)+500,max(yy)+500


def svg(items,title):
    xmin,ymin,xmax,ymax=bounds(items)
    out=['<svg xmlns="http://www.w3.org/2000/svg" viewBox="%g %g %g %g">'%(xmin,-ymax,xmax-xmin,ymax-ymin),
         '<title>'+html.escape(title)+'</title>','<rect x="%g" y="%g" width="%g" height="%g" fill="white"/>'%(xmin,-ymax,xmax-xmin,ymax-ymin)]
    colors={'CONC':'#334155','REBAR':'#b91c1c','STIRRUP':'#0f766e','DIM':'#64748b','TEXT':'#172033','AXIS':'#b4bac4','ENV':'#b91c1c','CENTER':'#888888','HIDDEN':'#666666','ERECT':'#444444'}
    for o in items:
        kind,layer=o[:2];color=colors[layer];sw=12 if layer in ('REBAR','ENV') else 7
        pattern={'CENTER':'250 60 1 60','HIDDEN':'100 60','ERECT':'65 35'}.get(layer)
        dash=(' stroke-dasharray="'+pattern+'"') if pattern else ''
        def line(a,b):
            return '<line x1="%g" y1="%g" x2="%g" y2="%g" stroke="%s" stroke-width="%g"%s/>'%(a[0],-a[1],b[0],-b[1],color,sw,dash)
        def text(pt,t,size,rotation=0):
            return '<text x="%g" y="%g" font-size="%g" font-family="Microsoft YaHei,SimSun,sans-serif" fill="%s" transform="rotate(%g %g %g)">%s</text>'%(pt[0],-pt[1],size,color,-rotation,pt[0],-pt[1],html.escape(t))
        if kind=='LINE':out.append(line(o[2],o[3]))
        elif kind=='POLY':
            pts=o[3]+([o[3][0]] if o[2] else [])
            out.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="%g"%s/>'%(' '.join('%g,%g'%(x,-y) for x,y in pts),color,sw,dash))
        elif kind=='CIRCLE':out.append('<circle cx="%g" cy="%g" r="%g" fill="none" stroke="%s" stroke-width="%g"/>'%(o[2][0],-o[2][1],o[3],color,sw))
        elif kind=='ARC':
            cx,cy=o[2];r=o[3];a=math.radians(o[4]);b=math.radians(o[4]+o[5])
            out.append('<path d="M %g %g A %g %g 0 %d 0 %g %g" fill="none" stroke="%s" stroke-width="%g"/>'%(cx+r*math.cos(a),-cy-r*math.sin(a),r,r,int(o[5]>180),cx+r*math.cos(b),-cy-r*math.sin(b),color,sw))
        elif kind=='TEXT':out.append(text(o[2],o[5],o[3],o[4]))
        elif kind=='DIM':
            a,b,loc,angle=o[2:6];factor=o[6] if len(o)>6 else 1
            if angle==0:
                aa=[a[0],loc[1]];bb=[b[0],loc[1]];value=abs(b[0]-a[0])*factor;tp=[(a[0]+b[0])/2,loc[1]+70]
            else:
                aa=[loc[0],a[1]];bb=[loc[0],b[1]];value=abs(b[1]-a[1])*factor;tp=[loc[0]-70,(a[1]+b[1])/2]
            out.extend((line(a,aa),line(b,bb),line(aa,bb),text(tp,('%.3f'%value).rstrip('0').rstrip('.'),o[7] if len(o)>7 else 110,angle)))
    return '\n'.join(out+['</svg>'])


