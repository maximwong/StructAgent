"""Physical coordinates shared by document figures and editable CAD (mm)."""
from itertools import accumulate


def enrich(r):
    p=r['input'];g=p['geometry'];result={}
    for member,prefix in [('secondary','CL'),('main','ZL')]:
        s=p[member];axis=[0]+list(accumulate(g[member+'_axis_spans_mm']))
        support=p['main']['b_mm'] if member=='secondary' else g['column_width_mm']
        records=[]
        for bar in r['bars']:
            if bar['member']!=member or bar['shape']=='stirrup':continue
            mark=bar['mark'];d=bar['diameter'];parts=dict(bar['segments'])
            y=s['cover_mm']+s['stirrup_diameter_mm']+d/2
            if '-D' in mark:
                i=int(mark.split('-D')[1])-1
                a=(g['wall_axis_to_inner_face_mm'] if i==0 else axis[i]+support/2)-bar['segments'][1][1]
                b=(axis[-1]-g['wall_axis_to_inner_face_mm'] if i==len(axis)-2 else axis[i+1]-support/2)+bar['segments'][2][1]
                pts=[[a,y],[b,y]]
            elif '-F' in mark:
                i=int(mark.split('-F')[1]);pos=bar['position'];y=s['h_mm']-y-s['extra_top_mm']
                pts=[[axis[i]-support/2-pos['left_mm'],y],[axis[i]+support/2+pos['right_mm'],y]]
            else:
                i=int(mark.split('-J')[1])-1;y=s['h_mm']-y-s['extra_top_mm']
                if i in (0,len(axis)-2):
                    wall=g['wall_axis_to_inner_face_mm'];straight=parts['墙内直段'];vertical=parts['补足锚固竖段']
                    if i==0:
                        end=next(b for b in r['bars'] if b['mark']==prefix+'-F1')['position']
                        a=wall-straight;b=axis[1]-support/2-end['left_mm']+parts['非受力搭接']
                        pts=[[a,y-vertical],[a,y],[b,y]]
                    else:
                        end=next(b for b in r['bars'] if b['mark']==prefix+f'-F{len(axis)-2}')['position']
                        a=axis[i]+support/2+end['right_mm']-parts['非受力搭接'];b=axis[-1]-wall+straight
                        pts=[[a,y],[b,y],[b,y-vertical]]
                else:
                    end=next(b for b in r['bars'] if b['mark']==prefix+f'-F{i}')['position']
                    a=axis[i]+support/2+end['right_mm']-parts['左搭接']
                    pts=[[a,y],[a+bar['length_mm'],y]]
            bar['physical_path_mm']=pts
            records.append(dict(mark=mark,path_mm=pts,diameter=d,count=bar['count'],role=mark.split('-')[1][0]))
        # Build stirrup stations from the ordinary schedule and actual lap/transfer zones.
        spacing=min(t['spacing'] for t in r[member+'_shear']);zones=[]
        for event in r['joint_checks']:
            if event.get('member')==member and 'span' in event:
                i=event['span']-1
                left=next(x for x in records if x['mark']==prefix+f'-F{i}')
                right=next(x for x in records if x['mark']==prefix+f'-F{i+1}')
                zones.append(dict(start=right['path_mm'][0][0],end=left['path_mm'][-1][0],spacing=min(100,5*event['diameter']),kind='lap'))
        # Non-force erection overlaps also receive the declared close stirrups.
        close=min(100,5*min(t['diameter'] for t in r[member]))
        for rec in records:
            if rec['role']!='J':continue
            bar=next(t for t in r['bars'] if t['mark']==rec['mark']);parts=dict(bar['segments']);a=rec['path_mm'][0][0];b=rec['path_mm'][-1][0]
            if '左搭接' in parts:
                zones.extend([dict(start=a,end=a+parts['左搭接'],spacing=close,kind='lap'),dict(start=b-parts['右搭接'],end=b,spacing=close,kind='lap')])
            elif int(rec['mark'].split('-J')[1])==1:zones.append(dict(start=b-150,end=b,spacing=close,kind='lap'))
            else:zones.append(dict(start=a,end=a+150,spacing=close,kind='lap'))
        stations=[]
        for i in range(len(axis)-1):
            a=(g['wall_axis_to_inner_face_mm'] if i==0 else axis[i]+support/2)+50
            b=(axis[-1]-g['wall_axis_to_inner_face_mm'] if i==len(axis)-2 else axis[i+1]-support/2)-50
            cuts=sorted({a,b}|{max(a,min(b,z[k])) for z in zones for k in ['start','end']})
            for xa,xb in zip(cuts,cuts[1:]):
                if xb<=xa:continue
                step=min([spacing]+[z['spacing'] for z in zones if z['start']<=(xa+xb)/2<=z['end']])
                import math
                n=max(1,math.ceil((xb-xa)/step));stations.extend(xa+(xb-xa)*j/n for j in range(n+1))
        result[member]=dict(axis_mm=axis,bars=records,lap_zones=zones,stirrup_stations_mm=sorted(set(round(x,6) for x in stations)),ordinary_spacing_mm=spacing)
    r['drawing_geometry']=result
    from detail_geometry import enrich_details
    enrich_details(r)
    return r
