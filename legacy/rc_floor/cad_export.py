"""Bounded desktop AutoCAD export. Never report a partial DWG as success."""
from pathlib import Path
import subprocess,os,json


def export(scene,dwg,timeout=240):
    scene=Path(scene).resolve();dwg=Path(dwg).resolve()
    if os.name!='nt':raise RuntimeError('直接生成DWG需要Windows及桌面AutoCAD 2022。')
    if dwg.exists():raise FileExistsError('DWG已存在，请使用新的文件名。')
    log=dwg.with_suffix('.log');cmd=['powershell.exe','-STA','-NoProfile','-ExecutionPolicy','Bypass','-File',str(Path(__file__).with_name('cad_export.ps1')),'-Scene',str(scene),'-OutputDwg',str(dwg),'-NewInstance']
    with log.open('wb') as f:
        try:proc=subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            raise RuntimeError('AutoCAD启动或绘图超时。请打开AutoCAD 2022并处理首次启动或许可对话框，再点“重试CAD”。日志：'+str(log))
    if proc.returncode or not dwg.exists():
        raise RuntimeError('AutoCAD未完成DWG生成。请确认AutoCAD 2022能正常打开空白图，再重试；也可使用输出内RCFLOOR.lsp与floor_data.dat手动绘图。日志：'+str(log))
    check=Path(str(dwg)+'.verify.json')
    if not check.exists():raise RuntimeError('DWG未完成重新打开验证，不能标记成功。')
    data=json.loads(check.read_text(encoding='utf-8-sig'))
    if data.get('state')!='SUCCESS':raise RuntimeError('DWG验证失败。')
    return data
