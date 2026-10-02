"use strict";
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="structagent-token"]').content;
const labels = {queued:"准备中",running:"执行中",completed:"已完成",needs_input:"请补充要求",failed:"执行未完成",error:"执行未完成",invalid_input:"请检查参数",invalid_output:"解析未通过校验",interrupted:"运行已中断",recovery_required:"CAD需要恢复",pending:"等待",skipped:"未执行"};
const steps = {parse:"理解与校验",design:"楼盖设计",cad:"CAD出图"};
const cases = {A:"设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。",B:"设计一个5.4m×6m柱网的办公楼单向板肋梁楼盖，采用C30和HRB400，活荷载2.0kN/m²。",C:"设计一个6m×6m柱网的办公楼单向板肋梁楼盖，采用C35和HRB400，活荷载3.0kN/m²。"};
const errorMessages = {cad_unavailable:"未连接到AutoCAD 2022。请打开AutoCAD，处理启动提示后重新开始。",cad_busy:"AutoCAD正在执行其他命令。请结束该命令，保持空闲后重新开始。",cad_start_failed:"无法启动CAD连接程序，请检查本机部署。",cad_receipt_invalid:"图纸未通过完成核验，请保留记录并检查CAD状态。",api_timeout:"模型响应超时，请稍后重新开始；本次没有继续计算或出图。",api_authentication_failed:"API密钥未通过验证，请检查本机配置。",api_balance_insufficient:"API账户余额不足，请检查账户后重新开始。",api_rate_limited:"API请求受限，请稍后重新开始。",api_connection_failed:"无法连接模型服务，请检查网络后重新开始。",api_invalid_json:"模型回复格式未通过校验，本次没有继续计算或出图。",api_incomplete_response:"模型回复不完整，请稍后重新开始。",api_unavailable:"模型服务暂时不可用，请稍后重新开始。",cad_timeout:"CAD绘图超时，请检查AutoCAD状态；需要时点击“检查并恢复CAD”。",cad_recovery_required:"CAD会话需要恢复，请保持AutoCAD打开并点击“检查并恢复CAD”。",owner_exited:"原运行进程已退出。本次不会自动重做，请检查CAD并恢复后重新开始。",source_mismatch:"解析数值与原文依据不一致，本次已停止。请核对要求后重新开始。",workflow_error:"流程执行遇到异常，后续步骤已停止。请保留这次运行记录供检查。"};
let current = null, busy = false, pending = false, stopped = false, ready = false, hydrated = false, lastRecovery = "";
async function api(path, method="GET", data) {
  const response = await fetch(path,{method,headers:{"X-StructAgent-Token":token,"Content-Type":"application/json"},...(data===undefined?{}:{body:JSON.stringify(data)})});
  const result = await response.json();
  if(!response.ok) throw new Error(result.error || "操作未完成，请保留现场供检查。");
  return result;
}
function notice(text) { $("notice").textContent=text; $("notice").hidden=!text; }
function controls() {
  $("start").disabled = busy || pending || !ready || !$("template-confirmed").checked;
  $("start").textContent = busy ? "任务执行中…" : "开始设计";
  $("recover").disabled = busy || pending || stopped;
  $("stop").disabled = busy || pending || stopped;
  if(busy || pending || stopped) $("open-cad").disabled=true;
}
function node(tag,text,className) { const el=document.createElement(tag);el.textContent=text;if(className)el.className=className;return el; }
function render(job) {
  const s=job.snapshot, status=s.status;
  $("job-title").textContent=job.project_name + " · " + new Date(job.created*1000).toLocaleString();
  $("status").textContent=labels[status] || "状态待检查";$("status").className="tag "+status;
  Object.keys(steps).forEach(key=>{const value=(s.steps||{})[key]||(["running","queued"].includes(status)?"pending":"skipped"),el=$("step-"+key);el.className=value;el.querySelector("small").textContent=labels[value]||value;});
  $("issues").replaceChildren();
  (s.errors||[]).forEach(error=>{const box=node("div","","issue");box.append(node("p",errorMessages[error.code]||error.message||"请检查本次输入。"));if(error.quote)box.append(node("p","原文："+error.quote,"quote"));$("issues").append(box);});
  if(status==="interrupted" && !(s.errors||[]).length) $("issues").append(node("p","原任务已中断，请检查CAD状态后重新开始。","issue"));
  const parsed=s.parse_result||{}, p=(parsed.envelope||{}).parameters, evidence=parsed.source_evidence||{};
  $("parameters").hidden=!p;$("parameter-empty").hidden=!!p;
  $("parameter-empty").textContent=status==="needs_input"?"请根据上方提示补充设计要求后重新开始。":"参数确认后将显示数值及原文依据。";
  const tbody=$("parameters").querySelector("tbody");tbody.replaceChildren();
  if(p) for(const [key,label,unit] of [["span_x","主梁轴跨"," mm"],["span_y","次梁轴跨"," mm"],["concrete","混凝土",""],["steel","梁纵筋",""],["live_load","活荷载"," kN/m²"]]) {
    const row=document.createElement("tr");row.append(node("td",label),node("td",String(p[key])+unit),node("td",evidence[key]?.quote||"—"));tbody.append(row);
  }
  $("design-summary").textContent=job.summary?`已完成板、次梁、主梁设计及已有校核；共 ${job.summary.reinforcement_items} 项钢筋明细。`:"尚未完成计算";
  const cad=(s.steps||{}).cad;
  $("cad-status").textContent=s.success?"图纸已保存，并完成重开与图元核验。":cad==="running"?"正在生成并验证CAD图纸，请保持AutoCAD空闲。":cad==="failed"||status==="recovery_required"?"本次CAD未确认完成，请查看上方提示。":"尚未生成图纸";
  const drawing=(s.artifacts||[]).find(a=>a.type==="dwg");$("drawing-path").textContent=drawing?.path||"";
  $("open-cad").disabled=!job.can_open||busy||pending;
  $("warnings").replaceChildren();(s.warnings||[]).forEach(w=>$("warnings").append(node("li",typeof w==="string"?w:JSON.stringify(w))));$("warning-box").hidden=!(s.warnings||[]).length;
  $("tool-log").replaceChildren();for(const call of s.tool_calls||[]){const li=document.createElement("li");li.append(node("span",`${steps[call.step]||call.step} · ${call.tool}`),node("span",labels[call.status]||call.status));$("tool-log").append(li);}
  if(!(s.tool_calls||[]).length)$("tool-log").append(node("li","暂无工具调用","muted"));
  $("run-id").textContent=s.run_id?"运行编号："+s.run_id:"";
}
async function refresh() {
  const data=await api("/api/status");busy=!!data.active;ready=data.configuration.ready;
  $("connection").textContent="本机服务已连接";$("config").textContent=data.configuration.message+" · AutoCAD需保持空闲";
  const history=$("history");history.replaceChildren();
  if(!data.jobs.length){const option=node("option","暂无运行记录");option.value="";history.append(option);}
  for(const job of data.jobs){const option=node("option",job.project_name+" · "+new Date(job.created*1000).toLocaleString());option.value=job.id;history.append(option);}
  if(!current && data.jobs.length) current=data.active&&data.active!=="recovery"?data.active:data.jobs[0].id;
  if(current){history.value=current;const job=await api("/api/jobs/"+current);render(job);if(!hydrated){if(!$("request").value.trim()){$("project-name").value=job.project_name;$("request").value=job.text;}hydrated=true;}}
  if(data.recovery){const value=JSON.stringify(data.recovery);if(value!==lastRecovery){notice(data.recovery.message);lastRecovery=value;}}
  controls();
}
$("design-form").addEventListener("submit",async event=>{
  event.preventDefault();if(pending||busy)return;pending=true;notice("");controls();
  try{const job=await api("/api/jobs","POST",{project_name:$("project-name").value,text:$("request").value,template_confirmed:$("template-confirmed").checked});current=job.id;await refresh();}
  catch(error){notice(error.message);}finally{pending=false;controls();}
});
document.querySelectorAll("[data-case]").forEach(button=>button.addEventListener("click",()=>{$("request").value=cases[button.dataset.case];$("request").focus();}));
$("template-confirmed").addEventListener("change",controls);
$("history").addEventListener("change",async()=>{current=$("history").value;try{const job=await api("/api/jobs/"+current);$("project-name").value=job.project_name;$("request").value=job.text;render(job);}catch(error){notice(error.message);}});
$("open-cad").addEventListener("click",async()=>{try{await api("/api/jobs/"+current+"/open-cad","POST",{});notice("已请求用本机AutoCAD打开图纸。");}catch(error){notice(error.message);}});
$("recover").addEventListener("click",async()=>{pending=true;controls();try{await api("/api/recover","POST",{});await refresh();}catch(error){notice(error.message);}finally{pending=false;controls();}});
$("stop").addEventListener("click",async()=>{try{await api("/api/stop","POST",{});stopped=true;ready=false;controls();$("connection").textContent="程序已退出";notice("程序已退出，可以关闭此页面。下次双击启动文件即可重新打开。");}catch(error){notice(error.message);}});
async function poll(){if(stopped)return;try{await refresh();}catch(error){$("connection").textContent="连接中断";ready=false;controls();notice("无法连接本机程序。请重新打开StructAgent并刷新页面，原任务不会自动重做。");}finally{if(!stopped)setTimeout(poll,1200);}}
poll();
