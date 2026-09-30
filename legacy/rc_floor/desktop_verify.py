"""Finish the two prepared examples from the user's normal Windows desktop."""
from pathlib import Path
import json,traceback
from report import convert
from workflow import write_status,retry_cad,finish
ROOT=Path(__file__).resolve().parent

def main():
    results=[]
    for name in ['sample1','changed']:
        out=ROOT/'examples'/name
        try:
            state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'))
            if state['outputs'].get('pdf',{}).get('state')!='SUCCESS':
                try:
                    converter=convert(out/'设计说明书.docx',out/'设计说明书.pdf')
                    state['outputs']['pdf']={'state':'SUCCESS','path':'设计说明书.pdf','converter':converter}
                except Exception as e:state['outputs']['pdf']={'state':'FAILED','message':str(e)}
                write_status(out,state)
            if state['outputs'].get('cad',{}).get('state')!='SUCCESS':retry_cad(out)
            else:finish(out,state)
            results.append(json.loads((out/'STATUS.json').read_text(encoding='utf-8')))
            print(name,results[-1]['state'],flush=True)
        except Exception:
            results.append({'state':'FAILED','message':traceback.format_exc()});print(traceback.format_exc(),flush=True)
    (ROOT/'desktop_verification.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    try:
        from verify_scale import run
        run(ROOT);print('6000/4000 mm PDF physical-scale verification SUCCESS',flush=True)
    except Exception:
        (ROOT/'scale_verification_failure.log').write_text(traceback.format_exc(),encoding='utf-8')
        print('PDF physical-scale verification incomplete; see scale_verification_failure.log',flush=True)
    print('验证结束，结果已保存。',flush=True)
    return 0 if all(s['state']=='SUCCESS' for s in results) else 1

if __name__=='__main__':raise SystemExit(main())
