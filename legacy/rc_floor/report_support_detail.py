"""Report-only replacement of the slab's inner-support inset (reference PDF p4).

The original shared dimension scene and all CAD primitives remain untouched.
All section coordinates below are millimetres. The user's final reference requires
the full T section, with slab thickness and total beam depth dimensioned separately.
"""
import math
from PIL import Image,ImageDraw,ImageFont
from figures import font_path


def geometry(r):
    d=r['dimension_geometry']['slab'];p=r['input'];w=d['support_width_mm'];h=p['slab']['h_mm']
    beam_h=p['secondary']['h_mm']
    if not all(math.isfinite(v) and v>0 for v in (w,h,beam_h)) or beam_h<=h:
        raise ValueError('板内支座局部图：板厚、次梁宽高无效')
    if not math.isclose(w,p['secondary']['b_mm'],abs_tol=1e-6):
        raise ValueError('板内支座局部图：尺寸记录与次梁宽度不一致')
    below=beam_h-h
    visible=below
    side=1.2*w
    # Top of the beam and slab coincide, as in the supplied monolithic floor model.
    # The lower slab contour does not cross the beam web: there is no joint line.
    lines=[([-side,h],[side,h]),([-side,0],[-w/2,0]),([w/2,0],[side,0]),
           ([-w/2,0],[-w/2,-visible]),([w/2,0],[w/2,-visible])]
    truncated=False
    cut=[[-w/2,-visible],[w/2,-visible]]
    return dict(kind='板与次梁整体连接',support_width_mm=w,slab_thickness_mm=h,
                beam_total_height_mm=beam_h,beam_below_slab_mm=below,
                visible_below_slab_mm=visible,truncated=truncated,outline_lines=lines,
                lower_boundary=cut,dimension_pairs=[[-w/2,0],[0,w/2],[-w/2,w/2]],
                dimension_values_mm=[w/2,w/2,w],units='mm')


def replace_slab_support(canvas,r,pt,scene_scale):
    """Replace one bounded image region, preserving every pixel outside the inset."""
    g=geometry(r);d=r['dimension_geometry']['slab'];total=d['axis_mm'][-1];step=total/25
    a=pt([total*.345,-3.95*step]);b=pt([total*.70,-11.0*step])
    box=(math.floor(a[0]),math.floor(a[1]),math.ceil(b[0]),math.ceil(b[1]))
    if not (0<=box[0]<box[2]<=canvas.w and 0<=box[1]<box[3]<=canvas.h):
        raise ValueError('板内支座局部图超出预留图框')
    width,height=box[2]-box[0],box[3]-box[1]
    im=Image.new('RGB',(width,height),'white');draw=ImageDraw.Draw(im);labels=[]
    def text(x,y,s,size=24,anchor=None):
        font=ImageFont.truetype(font_path(),size)
        bbox=draw.textbbox((x,y),s,font=font,anchor=anchor)
        if bbox[0]<0 or bbox[1]<0 or bbox[2]>width or bbox[3]>height:
            raise ValueError('板内支座局部图文字超出图框：'+s)
        labels.append(dict(text=s,bounds=list(bbox)))
        draw.text((x,y),s,font=font,fill='black',anchor=anchor)
    w=g['support_width_mm'];h=g['slab_thickness_mm'];dep=g['visible_below_slab_mm']
    available_height=height-215
    kmax=min((width-170)/(2.4*w),available_height/(h+dep))
    if kmax<=0:raise ValueError('板内支座局部图预留空间不足')
    # Standard whole-number enlargement; never use independent horizontal/vertical scales.
    zoom=max(1,math.floor(kmax/scene_scale));k=scene_scale*zoom
    if k>kmax+1e-8:zoom=kmax/scene_scale;k=kmax
    cx=width/2-30;top=77;z0=top+h*k
    def pixel(q):return (cx+q[0]*k,z0-q[1]*k)
    text(4,8,f'板—次梁内支座 ×{zoom:.2f}'.replace('.00',''),26)
    text(4,43,'整体 T 形节点（次梁显示全高）',24)
    for p,q in g['outline_lines']:draw.line([pixel(p),pixel(q)],fill='black',width=2)
    draw.line([pixel(q) for q in g['lower_boundary']],fill='black',width=2)
    # Thin dash-dot centreline, extending beyond both section boundaries.
    axis_top=top-12;axis_bottom=z0+dep*k+17;cy=axis_top
    while cy<axis_bottom:
        draw.line([(cx,cy),(cx,min(cy+13,axis_bottom))],fill='#777777',width=1)
        if cy+20<axis_bottom:draw.point((cx,cy+20),fill='#777777')
        cy+=28
    # Independent annotation offsets do not alter physical geometry.
    start=z0+dep*k+39
    levels=[start,start+34,start+68]
    for (left,right),value,yy in zip(g['dimension_pairs'],g['dimension_values_mm'],levels):
        xa,xb=cx+left*k,cx+right*k
        za=z0 if left else axis_bottom;zb=z0 if right else axis_bottom
        draw.line([(xa,za),(xa,yy+6)],fill='#888888',width=1)
        draw.line([(xb,zb),(xb,yy+6)],fill='#888888',width=1)
        draw.line([(xa,yy),(xb,yy)],fill='black',width=1)
        for xx in (xa,xb):draw.line([(xx-4,yy+5),(xx+4,yy-5)],fill='black',width=1)
        text((xa+xb)/2,yy-7,f'{value:g}',24,'mb')
    # Vertical dimensions: 80 is the slab thickness; total beam depth includes it.
    right=cx+1.2*w*k
    vertical=[]
    def vdim(x,y1,y2,value,source1,source2):
        for xx,yy in ((source1,y1),(source2,y2)):
            draw.line([(xx,yy),(x+5,yy)],fill='#888888',width=1)
        draw.line([(x,y1),(x,y2)],fill='black',width=1)
        for yy in (y1,y2):draw.line([(x-4,yy+5),(x+4,yy-5)],fill='black',width=1)
        font=ImageFont.truetype(font_path(),24);s=f'{value:g}'
        bb=font.getbbox(s);tile=Image.new('RGB',(bb[2]-bb[0]+4,bb[3]-bb[1]+4),'white')
        ImageDraw.Draw(tile).text((2-bb[0],2-bb[1]),s,font=font,fill='black')
        tile=tile.rotate(90,expand=True)
        loc=(round(x-tile.width-5),round((y1+y2-tile.height)/2))
        if loc[0]<0 or loc[1]<0 or loc[0]+tile.width>width or loc[1]+tile.height>height:
            raise ValueError('内支座竖向尺寸超出局部图框')
        im.paste(tile,loc);vertical.append(dict(value_mm=value,y1_px=y1,y2_px=y2))
    vdim(right+43,top,z0,h,right,right)
    vdim(right+96,top,z0+dep*k,g['beam_total_height_mm'],right,cx+w*k/2)
    text(width/2,height-24,'总高含板厚；尺寸单位 mm',23,'mt')
    # Do not let a valid-but-extreme model silently overlap dimension chains and footnote.
    if levels[-1]+10>height-31:
        raise ValueError('板内支座局部图高度不足，无法避让尺寸与说明')
    canvas.image.paste(im,box[:2])
    canvas.support_detail=dict(geometry=g,pixel_box=box,zoom=zoom,pixels_per_mm=k,
                               dimension_levels_px=levels,vertical_dimensions=vertical,label_bounds=labels)
    return canvas
