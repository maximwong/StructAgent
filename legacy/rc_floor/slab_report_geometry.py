"""Report-only representative slab strip. Never changes design/CAD results."""
import math


def close(a,b,label):
    if not math.isclose(a,b,abs_tol=1e-6,rel_tol=1e-10):
        raise ValueError('板配筋插图数据不一致：'+label+f' ({a:g} / {b:g} mm)')


def layout(r):
    p=r['input'];dim=r['dimension_geometry']['slab'];axis=list(dim['axis_mm'])
    h=p['slab']['h_mm'];cover=p['slab']['cover_mm'];wall=dim['wall_axis_to_inner_face_mm']
    width=dim['support_width_mm'];bearing=dim['bearing_mm'];total=axis[-1]
    if len(axis)!=6:raise ValueError('板配筋插图需要五跨代表板带尺寸记录')
    bars={b['mark']:b for b in r['bars'] if b['member']=='slab'}
    for mark in ('B1','B2','B3','B4','B5','B6','B7'):
        if mark not in bars:raise ValueError('板配筋插图缺少钢筋记录：'+mark)
        b=bars[mark]
        close(sum(v for _,v in b['segments']),b['length_mm'],mark+'分段总长')
        if any(v<0 or not math.isfinite(v) for _,v in b['segments']):
            raise ValueError(mark+'分段长度无效')
    records=[]
    for i in range(5):
        mark='B1' if i in (0,4) else 'B3';bar=bars[mark];s=dict(bar['segments']);d=bar['diameter']
        face_a=wall if i==0 else axis[i]+width/2
        face_b=total-wall if i==4 else axis[i+1]-width/2
        close(face_b-face_a,s['净跨'],mark+'净跨')
        al=s['左支座直段'];ar=s['右支座直段']
        if i==4:al,ar=ar,al
        a=face_a-al;b=face_b+ar;y=cover+d/2
        close(b-a+s['两端180度弯钩增加'],bar['length_mm'],mark+'外形与附加量')
        for got,available in [(al,bearing-cover if i==0 else width-cover),
                              (ar,bearing-cover if i==4 else width-cover)]:
            if got>available+1e-6:raise ValueError(mark+'伸入支座段超出已知可用范围')
        records.append(dict(mark=mark,role='bottom',span=i+1,diameter=d,path=[[a,y],[b,y]],
                            faces=[face_a,face_b],anchors=[al,ar],
                            allowance_mm=s['两端180度弯钩增加'],length_mm=bar['length_mm']))
    for i in range(1,5):
        mark='B2' if i in (1,4) else 'B4';bar=bars[mark];s=dict(bar['segments']);d=bar['diameter']
        close(s['支座宽'],width,mark+'支座宽')
        left=s['左伸出'];right=s['右伸出'];drop=s['两端竖段']/2
        a=axis[i]-width/2-left;b=axis[i]+width/2+right;y=h-cover-d/2
        close(drop,h-2*cover-d,mark+'竖段与板厚')
        close(b-a+2*drop,bar['length_mm'],mark+'外形总长')
        records.append(dict(mark=mark,role='top',support=i,diameter=d,
                            path=[[a,y-drop],[a,y],[b,y],[b,y-drop]],
                            faces=[axis[i]-width/2,axis[i]+width/2],extensions=[left,right],
                            drop_mm=drop,allowance_mm=0,length_mm=bar['length_mm']))
    for mark in ('B6','B7'):
        b=bars[mark];s=dict(b['segments']);d=b['diameter'];y=h-cover-d/2
        close(s['墙内直段'],bearing-cover,mark+'墙内直段')
        close(s['端部竖段'],h-2*cover-d,mark+'竖段与板厚')
        a=wall-s['墙内直段'];end=wall+s['伸入板内']
        pts=[[a,y-s['端部竖段']],[a,y],[end,y]]
        close(end-a+s['端部竖段'],b['length_mm'],mark+'外形总长')
        for side in ('left','right'):
            records.append(dict(mark=mark,role='wall' if mark=='B6' else 'corner',side=side,
                                diameter=d,path=pts if side=='left' else [[total-x,z] for x,z in pts],
                                extension_mm=s['伸入板内'],wall_straight_mm=s['墙内直段'],
                                drop_mm=s['端部竖段'],length_mm=b['length_mm']))
    # The curve radii/tails of B1/B3/B5 are not determined by empirical allowances.
    # Preserve those allowances; do not manufacture hook arcs or change bar lengths.
    for rec in records:
        d=rec['diameter']
        if any(z<cover+d/2-1e-6 or z>h-cover-d/2+1e-6 for _,z in rec['path']):
            raise ValueError(rec['mark']+'钢筋中心线超出保护层边界')
    return dict(axis_mm=axis,wall_face_mm=wall,bearing_mm=bearing,support_width_mm=width,
                h_mm=h,cover_mm=cover,total_mm=total,wall_thickness_mm=None,
                slab_extent_mm=[wall-bearing,total-wall+bearing],bars=records,
                distribution=dict(diameter=bars['B5']['diameter'],spacing=r['distribution']['spacing'],
                                  segments=bars['B5']['segments'],length_mm=bars['B5']['length_mm']),
                title='五跨代表板带，非楼盖全部跨数',units='mm')
