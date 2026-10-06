"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="structagent-token"]').content;
const labels = {queued:"准备中",running:"执行中",completed:"已完成",needs_input:"请补充要求",failed:"执行未完成",error:"执行未完成",invalid_input:"请检查参数",invalid_output:"解析未通过校验",interrupted:"运行已中断",recovery_required:"CAD需要恢复",pending:"等待",skipped:"未执行"};
const steps = {parse:"理解与校验",design:"楼盖设计",check:"独立校核",cad:"CAD出图"};
const memberNames = {slab:"板",secondary:"次梁",main:"主梁"};
const cases = {A:"设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。",B:"设计一个5.4m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。",C:"设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C35和HRB400，活荷载3.0kN/m²。"};
const errorMessages = {cad_unavailable:"未连接到AutoCAD 2022。请打开AutoCAD，处理启动提示后重新开始。",cad_busy:"AutoCAD正在执行其他命令。请结束该命令，保持空闲后重新开始。",cad_start_failed:"无法启动CAD连接程序，请检查本机部署。",cad_receipt_invalid:"图纸未通过完成核验，请保留记录并检查CAD状态。",api_timeout:"模型响应超时，请稍后重新开始；本次没有继续计算或出图。",api_authentication_failed:"API密钥未通过验证，请检查本机配置。",api_balance_insufficient:"API账户余额不足，请检查账户后重新开始。",api_rate_limited:"API请求受限，请稍后重新开始。",api_connection_failed:"无法连接模型服务，请检查网络后重新开始。",api_invalid_json:"模型回复格式未通过校验，本次没有继续计算或出图。",api_incomplete_response:"模型回复不完整，请稍后重新开始。",api_unavailable:"模型服务暂时不可用，请稍后重新开始。",cad_timeout:"CAD绘图超时，请检查AutoCAD状态；需要时点击“检查并恢复CAD”。",cad_recovery_required:"CAD会话需要恢复，请保持AutoCAD打开并点击“检查并恢复CAD”。",owner_exited:"原运行进程已退出。本次不会自动重做，请检查CAD并恢复后重新开始。",source_mismatch:"解析数值与原文依据不一致，本次已停止。请核对要求后重新开始。",workflow_error:"流程执行遇到异常，后续步骤已停止。请保留这次运行记录供检查。"};
let current = null, busy = false, pending = false, stopped = false, ready = false, hydrated = false, lastRecovery = "";
let professions=[], selectionRevision=0, refreshRevision=0;
const structured=()=>professions.find(p=>p.id===$("profession").value)?.kind==="structured";
async function api(path, method="GET", data) {
  const response = await fetch(path,{method,headers:{"X-StructAgent-Token":token,"Content-Type":"application/json"},...(data===undefined?{}:{body:JSON.stringify(data)})});
  const result = await response.json();
  if(!response.ok) throw new Error(result.error || "操作未完成，请保留现场供检查。");
  return result;
}
function notice(text) { $("notice").textContent=structured()?StructuredInput.friendly(text):text; $("notice").hidden=!text; }
function controls() {
  $("start").disabled = busy || pending || !ready || (!structured()&&$("input-mode").value==="template"&&!$("template-confirmed").checked);
  $("start").textContent = busy ? "任务执行中…" : structured()?"运行本地流程":"开始设计";
  $("recover").disabled = busy || pending || stopped;
  $("stop").disabled = busy || pending || stopped;
  if(busy || pending || stopped) $("open-cad").disabled=true;
  if(busy || pending || stopped) for(const id of ["generate-report","open-report","download-report"]) $(id).disabled=true;
}
function node(tag,text,className) { const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el; }
function render(job) {
  $("check-basis").textContent="";
  if(job.input_mode==="structured"){renderStructured(job);return;}
  resultLayout(false);
  const s=job.snapshot, status=s.status;
  $("job-title").textContent=job.project_name + " · " + new Date(job.created*1000).toLocaleString();
  $("status").textContent=labels[status] || "状态待检查";$("status").className="tag "+status;
  Object.keys(steps).forEach(key=>{const value=(s.steps||{})[key]||(["running","queued"].includes(status)?"pending":"skipped"),el=$("step-"+key);el.className=value;el.querySelector("small").textContent=labels[value]||value;});
  $("issues").replaceChildren();
  (s.errors||[]).forEach(error=>{const box=node("div","","issue");const path=error.path||[],field=path[1]==="model"?path.slice(2).join("."):"";box.append(node("p",error.code==="missing_parameter"&&field?"请补充："+FullInput.displayPath(field):errorMessages[error.code]||error.message||"请检查本次输入。"));if(error.quote)box.append(node("p","原文："+error.quote,"quote"));$("issues").append(box);});
  if(status==="interrupted" && !(s.errors||[]).length) $("issues").append(node("p","原任务已中断，请检查CAD状态后重新开始。","issue"));
  const parsed=s.parse_result||{}, p=(parsed.envelope||{}).parameters, evidence=parsed.source_evidence||{};
  $("parameters").hidden=!p;$("parameter-empty").hidden=!!p;
  $("parameters").classList.toggle("full-model",p?.input_mode==="explicit");
  $("parameter-empty").textContent=status==="needs_input"?"请根据上方提示补充设计要求后重新开始。":"参数确认后将显示数值及原文依据。";
  const tbody=$("parameters").querySelector("tbody");tbody.replaceChildren();
  if(p?.input_mode==="explicit") {function show(value,prefix=""){for(const [key,item] of Object.entries(value)){const path=prefix?prefix+"."+key:key;if(item&&typeof item==="object"&&!Array.isArray(item))show(item,path);else{const row=document.createElement("tr");const source=evidence[path]||{};row.append(node("td",FullInput.displayPath(path)),node("td",Array.isArray(item)?item.join(", "):String(item)),node("td",source.quote||source.source||"工程参数表"));tbody.append(row);}}}show(p.model);}
  else if(p) for(const [key,label,unit] of [["span_x","主梁轴跨"," mm"],["span_y","次梁轴跨"," mm"],["concrete","混凝土",""],["steel","梁纵筋",""],["live_load","活荷载"," kN/m²"]]) {
    const row=document.createElement("tr");row.append(node("td",label),node("td",String(p[key])+unit),node("td",evidence[key]?.quote||"—"));tbody.append(row);
  }
  $("design-summary").textContent=job.summary?`已完成板、次梁、主梁设计及已有校核；共 ${job.summary.reinforcement_items} 项钢筋明细。`:"尚未完成计算";
  const checked=job.check;
  $("check-summary").textContent=job.check_issue||(checked?`独立校核 ${checked.status}：${checked.summary.passed}/${checked.summary.total} 项通过（含数据一致性检查）。`:"尚未完成独立校核");
  if(job.check_issue)$("issues").append(node("p",job.check_issue,"issue"));
  $("check-details").hidden=!checked;$("check-rows").replaceChildren();
  if(checked){$("check-coverage").textContent=checked.coverage.demand_source+" 未独立复核："+checked.coverage.not_checked.join("；")+"。";for(const item of checked.checks){const row=document.createElement("tr");row.append(node("td",`${memberNames[item.member]}截面${item.section+1} · ${item.label}`),node("td",`${Number(item.actual.toPrecision(7))} ${item.relation} ${Number(item.limit.toPrecision(7))} ${item.unit}`),node("td",item.passed?"通过":"未通过"));$("check-rows").append(row);}}
  const cad=(s.steps||{}).cad;
  $("cad-status").textContent=s.success?"图纸已保存，并完成重开与图元核验。":cad==="running"?"正在生成并验证CAD图纸，请保持AutoCAD空闲。":cad==="failed"||status==="recovery_required"?"本次CAD未确认完成，请查看上方提示。":"尚未生成图纸";
  const drawing=(s.artifacts||[]).find(a=>a.type==="dwg");$("drawing-path").textContent=drawing?.path||"";
  $("open-cad").disabled=!job.can_open||busy||pending;
  $("warnings").replaceChildren();(s.warnings||[]).forEach(w=>$("warnings").append(node("li",typeof w==="string"?w:JSON.stringify(w))));$("warning-box").hidden=!(s.warnings||[]).length;
  $("tool-log").replaceChildren();for(const call of s.tool_calls||[]){const li=document.createElement("li");li.append(node("span",`${steps[call.step]||call.step} · ${call.tool}`),node("span",labels[call.status]||call.status));$("tool-log").append(li);}
  if(!(s.tool_calls||[]).length)$("tool-log").append(node("li","暂无工具调用","muted"));
  $("run-id").textContent=s.run_id?"运行编号："+s.run_id:"";
  const report=job.report;
  $("report-status").textContent=report?.message||"本机尚未启用计算书功能，请更新并重启程序。";
  $("generate-report").disabled=!report?.can_generate||busy||pending;
  $("generate-report").textContent=report?.status==="running"?"计算书生成中…":report?.status==="completed"?"重新生成计算书":"生成计算书";
  $("open-report").disabled=!report?.can_open||busy||pending;
  $("download-report").disabled=!report?.can_download||busy||pending;
  $("report-summary").textContent=report?.summary?`Word格式 · ${report.summary.images}幅图 · ${report.summary.tables}张表 · ${report.summary.check_summary.passed}/${report.summary.check_summary.total}项校核通过。`:"";
  $("report-run-id").textContent=report?.run_id?"计算书运行编号："+report.run_id:"";
  if(report?.status==="completed"&&report.tool){const li=document.createElement("li");li.append(node("span","计算书 · "+report.tool),node("span","已完成"));$("tool-log").append(li);}
}
async function refresh() {
  const generation=selectionRevision, refresh=++refreshRevision, profession=$("profession").value;
  const data=await api("/api/status?profession="+encodeURIComponent(profession));if(generation!==selectionRevision||refresh!==refreshRevision)return;busy=!!data.active;ready=data.configuration.ready;
  $("connection").textContent="本机服务已连接";$("config").textContent=data.configuration.message+(structured()?"":" · AutoCAD需保持空闲");
  const history=$("history");history.replaceChildren();
  if(!data.jobs.length){const option=node("option","暂无运行记录");option.value="";history.append(option);}
  for(const job of data.jobs){const option=node("option",job.project_name+" · "+new Date(job.created*1000).toLocaleString());option.value=job.id;history.append(option);}
  if(!current && data.jobs.length) current=data.jobs.some(j=>j.id===data.active)?data.active:data.jobs[0].id;
  if(current){history.value=current;const id=current,job=await api("/api/jobs/"+id);if(generation!==selectionRevision||refresh!==refreshRevision||id!==current)return;render(job);if(!hydrated){if(structured()||!$("request").value.trim()){restoreInput(job);}hydrated=true;}}
  if(data.recovery){const value=JSON.stringify(data.recovery);if(value!==lastRecovery){notice(data.recovery.message);lastRecovery=value;}}
  controls();
}
$("design-form").addEventListener("submit",async event=>{
  event.preventDefault();if(pending||busy)return;pending=true;notice("");controls();
  try{const generation=selectionRevision;let payload;if(structured()){payload={input_mode:"structured",profession:$("profession").value,project_name:$("project-name").value,...StructuredInput.collect()};}else{payload={project_name:$("project-name").value,text:$("request").value};if($("input-mode").value==="explicit"){payload.input_mode="explicit";payload.model=FullInput.collect();}else{payload.template_confirmed=$("template-confirmed").checked;}}const job=await api("/api/jobs","POST",payload);if(generation===selectionRevision)current=job.id;await refresh();if(generation===selectionRevision)$("result-title").scrollIntoView({behavior:"smooth",block:"start"});}
  catch(error){notice(error.message);}finally{pending=false;controls();}
});
document.querySelectorAll("[data-case]").forEach(button=>button.addEventListener("click",()=>{$("request").value=cases[button.dataset.case];$("request").focus();}));
$("template-confirmed").addEventListener("change",controls);
function changeMode(){$("template-panel").hidden=$("input-mode").value!=="template";$("full-input-panel").hidden=$("input-mode").value!=="explicit";controls();}
function restoreInput(job){$("project-name").value=job.project_name;if(job.input_mode==="structured"){StructuredInput.load(job.envelope);return;}$("request").value=job.text;$("input-mode").value=Object.prototype.hasOwnProperty.call(job,"model")?"explicit":"template";if(job.model)FullInput.load(job.model);changeMode();}
$("input-mode").addEventListener("change",changeMode);
$("history").addEventListener("change",async()=>{current=$("history").value;const id=current,generation=++selectionRevision;StructuredInput.invalidate();try{const job=await api("/api/jobs/"+id);if(generation!==selectionRevision||id!==current)return;restoreInput(job);render(job);}catch(error){if(generation===selectionRevision)notice(error.message);}});
$("open-cad").addEventListener("click",async()=>{try{await api("/api/jobs/"+current+"/open-cad","POST",{});notice("已请求用本机AutoCAD打开图纸。");}catch(error){notice(error.message);}});
for(const [id,action,message] of [["generate-report","generate-report","已开始生成本次方案的计算书。"],["open-report","open-report","已请求用本机文档软件打开计算书。"]]){
  $(id).addEventListener("click",async()=>{if(pending||busy)return;pending=true;controls();try{await api("/api/jobs/"+current+"/"+action,"POST",{});notice(message);await refresh();}catch(error){notice(error.message);}finally{pending=false;controls();}});
}
$("download-report").addEventListener("click",async()=>{
  if(pending||busy)return;pending=true;controls();
  try{const response=await fetch("/api/jobs/"+current+"/report-download",{headers:{"X-StructAgent-Token":token}});
    if(!response.ok){const result=await response.json();throw new Error(result.error||"计算书下载失败。");}
    const url=URL.createObjectURL(await response.blob()),link=document.createElement("a");link.href=url;link.download="StructAgent-计算书.docx";document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);notice("计算书下载已交给浏览器，请查看下载列表。");
  }catch(error){notice(error.message);}finally{pending=false;await refresh().catch(()=>{});controls();}
});
$("recover").addEventListener("click",async()=>{pending=true;controls();try{await api("/api/recover","POST",{});await refresh();}catch(error){notice(error.message);}finally{pending=false;controls();}});
$("stop").addEventListener("click",async()=>{try{await api("/api/stop","POST",{});stopped=true;ready=false;controls();$("connection").textContent="程序已退出";notice("程序已退出，可以关闭此页面。下次双击启动文件即可重新打开。");}catch(error){notice(error.message);}});
async function poll(){if(stopped)return;try{await refresh();}catch(error){$("connection").textContent="连接中断";ready=false;controls();notice("无法连接本机程序。请重新打开StructAgent并刷新页面，原任务不会自动重做。");}finally{if(!stopped)setTimeout(poll,1200);}}
function resultLayout(local){$("design-result-title").textContent=local?(professions.find(p=>p.id===$("profession").value)?.form.result_title||"计算结果"):"设计与图纸";$("step-design").hidden=false;$("step-cad").hidden=local;$("step-design").querySelector("span").textContent=local?(professions.find(p=>p.id===$("profession").value)?.form.design_label||"设计"):"楼盖设计";$("open-cad").hidden=local;$("cad-status").hidden=local;$("drawing-path").hidden=local;$("generate-report").closest(".card").hidden=local;$("check-scope").textContent=local?(professions.find(p=>p.id===$("profession").value)?.form.notice||""):"仅复核实配截面与抗剪约束；不包含独立内力分析及规范全项审查。";}
function renderStructured(job){resultLayout(true);const s=job.snapshot,c=job.check;$("job-title").textContent=job.project_name+" · 项目标识 "+job.project_id+" · "+new Date(job.created*1000).toLocaleString();$("status").textContent=labels[s.status]||"状态待检查";$("status").className="tag "+s.status;
  for(const key of Object.keys(steps)){const el=$("step-"+key),state=s.steps?.[key]||(["running","queued"].includes(s.status)?"pending":"skipped");el.className=state;el.querySelector("small").textContent=labels[state]||state;}
  $("step-design").hidden=job.operation==="check";$("issues").replaceChildren();for(const error of s.errors||[]){const path=(error.path||[]).join('.');$("issues").append(node("p",StructuredInput.friendly((path?path+"：":"")+(error.message||"请检查参数。")),"issue"));}if(job.check_issue)$("issues").append(node("p",job.check_issue,"issue"));
  $("parameters").hidden=false;$("parameter-empty").hidden=true;$("parameters").classList.add("full-model");const tbody=$("parameters").querySelector("tbody");tbody.replaceChildren();function show(value,path=""){for(const [key,v] of Object.entries(value)){const p=path?path+'.'+key:key;if(v&&typeof v==='object'&&!Array.isArray(v))show(v,p);else{const row=document.createElement("tr");row.append(node("td",StructuredInput.displayPath(p)),node("td",String(v)),node("td","用户明确输入 / 本地JSON"));tbody.append(row);}}}show(job.envelope);
  $("design-summary").textContent=job.display_summary||"尚无可确认的计算结果。";
  $("check-summary").textContent=job.check_issue||(c?`独立校核 ${c.status}：${c.summary.passed}/${c.summary.total} 项通过。`:"尚未完成独立校核");$("check-details").hidden=!c;$("check-rows").replaceChildren();
  $("check-basis").textContent=(c?.display_basis||[]).join("；");
  if(c){const coverage=c.display_coverage||c.coverage;$("check-coverage").textContent="已检查："+coverage.checked.join("；")+"。未覆盖："+coverage.not_checked.join("；")+"。"+coverage.pass_meaning;for(const item of c.display_rows||[]){const row=document.createElement("tr");row.append(node("td",item.label+"；依据："+item.basis),node("td",item.comparison),node("td",item.passed?"通过":"未通过"));$("check-rows").append(row);}}
  $("warnings").replaceChildren();for(const warning of s.warnings||[])$("warnings").append(node("li",typeof warning==='string'?warning:JSON.stringify(warning)));$("warning-box").hidden=!(s.warnings||[]).length;$("tool-log").replaceChildren();for(const call of s.tool_calls||[]){const li=document.createElement("li");li.append(node("span",`${call.step} · ${call.tool}`),node("span",labels[call.status]||call.status));$("tool-log").append(li);}$("run-id").textContent=s.run_id?"运行编号："+s.run_id:"";
}
function chooseProfession(){selectionRevision++;refreshRevision++;StructuredInput.invalidate();current=null;hydrated=true;ready=false;const p=professions.find(p=>p.id===$("profession").value),local=p?.kind==="structured";$("mode-footer").textContent=local?"本地参数校验与计算 · 每次运行独立保存":"本机计算与绘图 · 参数由云端模型解析 · 每次运行独立保存";$("floor-input").hidden=local;$("structured-panel").hidden=!local;$("request").required=!local;$("recover").hidden=local;$("request-title").textContent=local?p.form.title:"描述你的设计要求";$("input-help").textContent=local?p.form.help:"直接输入自然语言，无需命令、引号或固定句式。";$("usage-scope").textContent=local?p.form.notice:"先打开并保持AutoCAD空闲。首次使用按本机部署说明配置API和CAD脚本。结果需要工程人员复核。";$("project-name").value=local?"":"办公楼演示项目";if(local)StructuredInput.configure(p,api,notice);resultLayout(local);$("step-design").hidden=false;$("job-title").textContent="填写本专业工程输入后开始";$("status").textContent="等待开始";$("status").className="tag";for(const id of ["issues","check-rows","tool-log"]){$(id).replaceChildren();}$("parameters").hidden=true;$("parameter-empty").hidden=false;$("check-summary").textContent="尚未完成独立校核";$("check-details").hidden=true;$("design-summary").textContent="尚未完成计算";$("warning-box").hidden=true;$("run-id").textContent="";$("drawing-path").textContent="";$("cad-status").textContent="尚未生成图纸";$("check-basis").textContent="";$("open-cad").disabled=true;notice("");controls();refresh().catch(e=>notice(e.message));}
$("profession").addEventListener("change",chooseProfession);
Promise.all([FullInput.initialize(()=>api("/api/input-form"),notice),api("/api/professions")]).then(([,data])=>{professions=data.professions;$("profession").replaceChildren(...professions.map(p=>new Option(p.name,p.id)));poll();}).catch(error=>notice("参数表初始化失败，请刷新或重新启动程序。"));
