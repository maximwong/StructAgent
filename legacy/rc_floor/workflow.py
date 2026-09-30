"""One immutable calculation snapshot feeds all outputs; per-output status."""
from pathlib import Path
from datetime import datetime
import json,hashlib,csv
from engine import calculate
from figures import generate as draw_figures
from cad_scene import export_drawing
from cad_export import export as export_cad


def write_status(out,state):
    (out/'STATUS.json').write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf-8')


def finish(out,state):
    outputs=state['outputs']
    state['state']='SUCCESS' if all(outputs.get(k,{}).get('state')=='SUCCESS' for k in ['word','pdf','cad']) else 'PARTIAL'
    write_status(out,state)
    problems=[k+': '+v['message'] for k,v in outputs.items() if v.get('state')=='FAILED']
    if problems:(out/'问题清单.txt').write_text('\n'.join(problems),encoding='utf-8-sig')
    elif (out/'问题清单.txt').exists():(out/'问题清单.txt').unlink()
    return out


def generate(config,out,docx_only=False):
    from report import build_docx,convert
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    # Never overwrite an earlier run. GUI creates unique timestamp directories.
    if (out/'STATUS.json').exists():raise FileExistsError('输出目录已有生成记录，请选择新目录；重试CAD使用专门入口。')
    state={'state':'RUNNING','created_at':datetime.now().isoformat(),'outputs':{}}
    write_status(out,state)
    try:
        raw=Path(config).read_bytes();p=json.loads(raw.decode('utf-8-sig'));r=calculate(p)
        state['input_sha256']=hashlib.sha256(raw).hexdigest()
        (out/'input.json').write_bytes(raw)
        data=json.dumps(r,ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8');(out/'results.json').write_bytes(data)
        state['results_sha256']=hashlib.sha256(data).hexdigest()
        with (out/'钢筋长度.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['编号','用途','直径mm','组内根数','单根几何长度mm','向上取整mm'])
            for b in r['bars']:w.writerow([b[k] for k in ['mark','use','diameter','count','length_mm','rounded_mm']])
        export_drawing(r,out/'cad');state['scene_sha256']=hashlib.sha256((out/'cad/drawing_scene.json').read_bytes()).hexdigest()
        state['outputs']['cad_data']={'state':'SUCCESS','path':'cad/floor_data.dat'}
    except Exception as e:
        state.update(state='FAILED',message=str(e));write_status(out,state)
        (out/'问题清单.txt').write_text(str(e),encoding='utf-8-sig');raise
    try:
        figs=draw_figures(r,out/'figures');build_docx(r,figs,out/'设计说明书.docx')
        state['outputs']['word']={'state':'SUCCESS','path':'设计说明书.docx'}
    except Exception as e:state['outputs']['word']={'state':'FAILED','message':str(e)}
    write_status(out,state)
    if docx_only:
        state['outputs']['pdf']={'state':'SKIPPED'};state['outputs']['cad']={'state':'SKIPPED'}
        state['state']='DOCX_READY' if state['outputs']['word']['state']=='SUCCESS' else 'FAILED';write_status(out,state);return out
    if state['outputs']['word']['state']=='SUCCESS':
        try:
            converter=convert(out/'设计说明书.docx',out/'设计说明书.pdf')
            state['outputs']['pdf']={'state':'SUCCESS','path':'设计说明书.pdf','converter':converter}
        except Exception as e:state['outputs']['pdf']={'state':'FAILED','message':str(e)}
    else:state['outputs']['pdf']={'state':'FAILED','message':'Word生成失败，不能导出PDF。'}
    write_status(out,state)
    try:
        check=export_cad(out/'cad/drawing_scene.json',out/'楼盖设计图.dwg')
        state['outputs']['cad']={'state':'SUCCESS','path':'楼盖设计图.dwg','verification':check}
    except Exception as e:state['outputs']['cad']={'state':'FAILED','message':str(e)}
    return finish(out,state)


def retry_cad(out):
    out=Path(out);state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'))
    for path,key in [('input.json','input_sha256'),('results.json','results_sha256'),('cad/drawing_scene.json','scene_sha256')]:
        if hashlib.sha256((out/path).read_bytes()).hexdigest()!=state.get(key):raise ValueError(path+'已变化，请重新生成全部输出以保证一致。')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S_%f');name='楼盖设计图_'+stamp+'.dwg'
    try:
        check=export_cad(out/'cad/drawing_scene.json',out/name)
        state['outputs']['cad']={'state':'SUCCESS','path':name,'verification':check}
    except Exception as e:state['outputs']['cad']={'state':'FAILED','message':str(e)}
    return finish(out,state)
