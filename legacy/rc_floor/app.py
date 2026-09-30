"""Chinese desktop parameter editor. No account/API/network is used at runtime."""
import copy
import json
import os
from pathlib import Path
from datetime import datetime
import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from input_validation import CONCRETE_MATERIALS as MATERIALS

ROOT=Path(__file__).resolve().parent
LABELS={
 'project':'项目名称','basis':'计算模型说明',
 'secondary_axis_spans_mm':'次梁五跨轴线跨度 mm（逗号分隔）','main_axis_spans_mm':'主梁三跨轴线跨度 mm（逗号分隔）',
 'secondary_spacing_mm':'次梁间距 mm','wall_axis_to_inner_face_mm':'外墙轴线至内边 mm','slab_bearing_mm':'板墙端支承长度 mm','secondary_bearing_mm':'次梁墙端支承长度 mm','main_bearing_mm':'主梁墙端支承长度 mm','column_width_mm':'柱宽 mm',
 'concrete_kN_m3':'混凝土重度 kN/m³','finish_mm':'面层厚度 mm','finish_kN_m3':'面层重度 kN/m³','plaster_mm':'抹灰厚度 mm','plaster_kN_m3':'抹灰重度 kN/m³','live_kN_m2':'活荷载标准值 kN/m²','gamma_g':'恒荷载分项系数','gamma_q':'活荷载分项系数',
 'concrete':'混凝土等级','fc_MPa':'混凝土抗压强度 fc MPa','ft_MPa':'混凝土抗拉强度 ft MPa','alpha1':'等效矩形压应力系数 α1','slab_steel':'板钢筋等级','slab_fy_MPa':'板钢筋强度 fy MPa','beam_steel':'梁纵筋等级','beam_fy_MPa':'梁纵筋强度 fy MPa','stirrup_steel':'箍筋等级','stirrup_fy_MPa':'箍筋强度 fyv MPa','xi_elastic_limit':'主梁相对受压区高度限值','xi_plastic_limit':'板次梁相对受压区高度限值',
 'h_mm':'截面高度或板厚 mm','b_mm':'梁宽 mm','cover_mm':'保护层厚度 mm','main_diameters_mm':'板受力筋候选直径 mm','spacings_mm':'板受力筋候选间距 mm','arch_factor':'允许内拱时的弯矩折减系数','distribution_diameter_mm':'板分布筋直径 mm','stirrup_diameter_mm':'箍筋直径 mm','stirrup_legs':'箍筋肢数（固定2）','extra_top_mm':'上筋交叉附加下移 mm','max_stirrup_spacing_mm':'普通箍筋间距上限 mm','support_moment':'主梁支座计算位置','hanger_diameter_mm':'旧版斜吊筋候选直径 mm（本报告不用）','hanger_angle_deg':'旧版斜吊筋倾角 °（本报告不用）',
 'beam_diameters_mm':'梁纵筋候选直径 mm','maximum_rows':'纵筋最多排数（1或2）','aggregate_mm':'骨料粒径 mm','slab_support_extension_ratio':'旧版板支座示意比例（本报告不用）','slab_wall_extension_ratio':'旧版板墙端示意比例（本报告不用）',
 'author':'姓名','class_name':'班级','student_id':'学号','date':'日期（留空为当天）','anchor_ribbed_factor':'带肋筋锚固系数（不小于40d）','anchor_plain_factor':'光圆筋锚固系数（不小于34d）','lap_factor':'受拉搭接系数（不小于1.6）','max_stock_mm':'单根原材长度上限 mm','top_extension_ratio':'次梁全组负筋伸出比例（不小于1/3）','stirrup_hook_tail_d':'箍筋弯钩平直段系数（不小于10d）','stirrup_bend_inner_d':'箍筋最小弯曲内径系数（不小于4d）','allow_arch':'采用中带内拱折减（需确认适用）'}
TABS=[('项目与作者',['project','basis','report']),('结构布置',['geometry']),('荷载与材料',['loads','materials']),('板配筋',['slab']),('次梁配筋',['secondary']),('主梁配筋',['main']),('选筋设置',['detailing'])]
HIDDEN={'hanger_diameter_mm','hanger_angle_deg','slab_support_extension_ratio','slab_wall_extension_ratio'}


def parse_value(text,old,label):
    if isinstance(old,bool):return bool(text)
    if isinstance(old,list):
        values=[float(x.strip()) for x in text.replace('，',',').split(',') if x.strip()]
        if not values:raise ValueError(label+'不能为空')
        return [int(v) if v.is_integer() else v for v in values]
    if isinstance(old,int):
        value=float(text)
        if not value.is_integer():raise ValueError(label+'必须是整数')
        return int(value)
    if isinstance(old,float):return float(text)
    return str(text)


class App:
    def __init__(self,window):
        self.root=window;window.title('单向板肋梁楼盖生成器 · 2026-09-24 CAD图文同步');window.geometry('1100x820');window.minsize(920,680)
        self.params=json.loads((ROOT/'sample1.json').read_text(encoding='utf-8'));self.variables={};self.events=queue.Queue();self.busy=False;self.last_out=None
        style=ttk.Style();style.configure('.',font=('Microsoft YaHei UI',10));style.configure('Title.TLabel',font=('Microsoft YaHei UI',17,'bold'))
        ttk.Label(window,text='单向板肋梁楼盖说明书',style='Title.TLabel').pack(anchor='w',padx=20,pady=(15,5))
        ttk.Label(window,text='固定样例结构：主梁3跨、次梁5跨；每主梁跨为3倍次梁间距。修改参数后生成说明书和 CAD。').pack(anchor='w',padx=20,pady=(0,12))
        bar=ttk.Frame(window);bar.pack(fill='x',padx=20)
        for label,cmd in [('载入方案',self.load),('保存方案',self.save),('恢复样例',self.reset),('检查参数',self.check)]:ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=(0,8))
        self.notebook=ttk.Notebook(window);self.notebook.pack(fill='both',expand=True,padx=20,pady=12)
        self.build_tabs()
        footer=ttk.Frame(window);footer.pack(fill='x',padx=20,pady=(0,12))
        self.generate_button=ttk.Button(footer,text='生成说明书和 CAD',command=self.generate);self.generate_button.pack(side='left')
        ttk.Button(footer,text='重试CAD',command=self.retry_cad).pack(side='left',padx=10)
        ttk.Button(footer,text='打开输出文件夹',command=self.open_output).pack(side='left',padx=10)
        self.status=tk.StringVar(value='准备就绪。生成过程不消耗 Plus 额度。');ttk.Label(footer,textvariable=self.status,wraplength=720).pack(side='left',padx=8)
        window.after(200,self.poll)

    def build_tabs(self):
        for tab in self.notebook.tabs():self.notebook.forget(tab)
        self.variables={}
        for title,groups in TABS:
            tab=ttk.Frame(self.notebook);self.notebook.add(tab,text=title)
            canvas=tk.Canvas(tab,highlightthickness=0);scroll=ttk.Scrollbar(tab,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=scroll.set)
            scroll.pack(side='right',fill='y');canvas.pack(side='left',fill='both',expand=True);frame=ttk.Frame(canvas,padding=15);win=canvas.create_window((0,0),window=frame,anchor='nw')
            frame.bind('<Configure>',lambda event,c=canvas:c.configure(scrollregion=c.bbox('all')));canvas.bind('<Configure>',lambda event,c=canvas,w=win:c.itemconfigure(w,width=event.width))
            row=0
            for group in groups:
                data=self.params[group]
                if not isinstance(data,dict):fields=[('',data)]
                else:fields=data.items()
                for key,value in fields:
                    if key in HIDDEN:continue
                    label=LABELS[key or group];path=(group,key)
                    ttk.Label(frame,text=label).grid(row=row,column=0,sticky='w',padx=(0,14),pady=7)
                    var=tk.BooleanVar(value=value) if isinstance(value,bool) else tk.StringVar(value=', '.join(map(str,value)) if isinstance(value,list) else str(value))
                    self.variables[path]=(var,value,label)
                    if isinstance(value,bool):widget=ttk.Checkbutton(frame,variable=var)
                    elif key=='concrete':
                        widget=ttk.Combobox(frame,textvariable=var,values=list(MATERIALS),state='readonly');widget.bind('<<ComboboxSelected>>',self.material_changed)
                    elif key=='support_moment':widget=ttk.Combobox(frame,textvariable=var,values=['face','axis'],state='readonly')
                    else:widget=ttk.Entry(frame,textvariable=var,width=48)
                    widget.grid(row=row,column=1,sticky='ew',pady=7);row+=1
            frame.columnconfigure(1,weight=1)

    def material_changed(self,event=None):
        grade=self.variables[('materials','concrete')][0].get();fc,ft=MATERIALS[grade]
        self.variables[('materials','fc_MPa')][0].set(fc);self.variables[('materials','ft_MPa')][0].set(ft)

    def collect(self):
        p=copy.deepcopy(self.params)
        for (group,key),(var,old,label) in self.variables.items():
            try:value=parse_value(var.get(),old,label)
            except (ValueError,TypeError):raise ValueError('请检查输入：'+label)
            if key:p[group][key]=value
            else:p[group]=value
        return p

    def load(self):
        if self.busy:return
        name=filedialog.askopenfilename(filetypes=[('参数方案','*.json')])
        if name:
            try:
                p=json.loads(Path(name).read_text(encoding='utf-8-sig'))
                from engine import calculate
                calculate(p);self.params=p;self.build_tabs();self.status.set('已载入 '+Path(name).name)
            except Exception as e:messagebox.showerror('载入失败',str(e))

    def save(self):
        try:p=self.collect()
        except ValueError as e:messagebox.showerror('输入错误',str(e));return
        name=filedialog.asksaveasfilename(defaultextension='.json',filetypes=[('参数方案','*.json')])
        if name:Path(name).write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8');self.status.set('方案已保存')

    def reset(self):
        if self.busy:return
        self.params=json.loads((ROOT/'sample1.json').read_text(encoding='utf-8'));self.build_tabs();self.status.set('已恢复样例1参数')

    def check(self):
        try:
            from engine import calculate
            r=calculate(self.collect());messagebox.showinfo('检查完成',f"程序内计算与配筋检查通过，共{len(r['bars'])}组编号钢筋。\n仍需人工校核的项目会在说明书列出。")
        except Exception as e:messagebox.showerror('参数或配筋不满足条件',str(e))

    def generate(self):
        if self.busy:return
        try:p=self.collect()
        except Exception as e:messagebox.showerror('输入错误',str(e));return
        directory=filedialog.askdirectory(title='选择存放说明书的文件夹')
        if not directory:return
        out=Path(directory)/('楼盖说明书_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f'));out.mkdir()
        config=out/'参数.json';config.write_text(json.dumps(p,ensure_ascii=False,indent=2),encoding='utf-8')
        self.busy=True;self.generate_button.state(['disabled']);self.status.set('正在计算并生成 Word、PDF 和 DWG，请稍候……')
        def worker():
            try:
                from workflow import generate
                generate(config,out);state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'));self.events.put(('success',out) if state['state']=='SUCCESS' else ('error',(out,'部分输出未完成，请查看问题清单；CAD可单独重试。')))
            except Exception as e:self.events.put(('error',(out,str(e))))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        try:
            kind,data=self.events.get_nowait();self.busy=False;self.generate_button.state(['!disabled'])
            if kind=='success':self.last_out=data;self.status.set('完成：'+str(data));messagebox.showinfo('生成完成','Word、PDF、DWG、参数、计算记录和钢筋长度表均已保存。')
            else:
                self.last_out=data[0];self.status.set('未完成，请查看问题清单');messagebox.showerror('生成未完成',data[1])
        except queue.Empty:pass
        self.root.after(200,self.poll)

    def retry_cad(self):
        if self.busy:return
        directory=str(self.last_out) if self.last_out else filedialog.askdirectory(title='选择此前输出目录')
        if not directory:return
        self.busy=True;self.generate_button.state(['disabled']);self.status.set('使用同一份计算结果重试CAD……')
        def worker():
            out=Path(directory)
            try:
                from workflow import retry_cad
                retry_cad(out);state=json.loads((out/'STATUS.json').read_text(encoding='utf-8'))
                self.events.put(('success',out) if state['state']=='SUCCESS' else ('error',(out,'仍有输出未完成，详见问题清单。')))
            except Exception as e:self.events.put(('error',(out,str(e))))
        threading.Thread(target=worker,daemon=True).start()

    def open_output(self):
        if self.last_out and self.last_out.exists():os.startfile(self.last_out)
        else:messagebox.showinfo('输出位置','请先生成一份说明书。')


if __name__=='__main__':
    window=tk.Tk();App(window);window.mainloop()
