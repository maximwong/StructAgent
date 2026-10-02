"use strict";
// Professional form descriptors come from the floor plugin; no calculation runs here.
const FullInput = (()=>{
  let spec=null;const controls=new Map();
  function readPath(model,path){return path.split(".").reduce((value,key)=>value?.[key],model);}
  function writePath(model,path,value){const parts=path.split(".");let group=model;for(const key of parts.slice(0,-1))group=group[key]??={};group[parts.at(-1)]=value;}
  function load(model){for(const [path,input] of controls){const value=readPath(model,path);input.value=value===undefined?"":Array.isArray(value)?value.join(", "):String(value);}}
  function collect(){const model={};for(const field of spec?.fields||[]){const input=controls.get(field.path),text=input.value.trim(),schema=field.schema;if(!text && schema.type!=="string")continue;
    let value=text;if(schema.type==="number"||schema.type==="integer")value=Number(text);else if(schema.type==="boolean")value=text==="true";else if(schema.type==="array")value=text.split(/[,，\s]+/).map(Number);
    if((typeof value==="number"&&!Number.isFinite(value))||(Array.isArray(value)&&value.some(n=>!Number.isFinite(n))))throw new Error(field.label+"需要有限数值。");writePath(model,field.path,value);
  }return model;}
  async function initialize(fetchSpec,showNotice){spec=await fetchSpec();const container=document.getElementById("full-input-fields");const groups=new Map();
    for(const field of spec.fields){let details=groups.get(field.group);if(!details){details=document.createElement("details");const summary=document.createElement("summary");summary.textContent=field.group;details.append(summary);container.append(details);groups.set(field.group,details);}
      const schema=field.schema,id="model-"+field.path.replaceAll(".","-"),label=document.createElement("label");label.htmlFor=id;label.textContent=field.label;
      let input;const options=schema.enum||(schema.const!==undefined?[schema.const]:schema.type==="boolean"?[true,false]:null);
      if(options){input=document.createElement("select");const blank=document.createElement("option");blank.value="";blank.textContent="请选择";input.append(blank);for(const option of options){const el=document.createElement("option");el.value=String(option);el.textContent=typeof option==="boolean"?(option?"是":"否"):String(option);input.append(el);}}
      else{input=document.createElement("input");input.type=schema.type==="number"||schema.type==="integer"?"number":"text";if(input.type==="number")input.step=schema.type==="integer"?"1":"any";if(schema.type==="array")input.placeholder="数值之间用逗号分隔";}
      input.id=id;input.dataset.path=field.path;details.append(label,input);controls.set(field.path,input);
    }
    document.getElementById("full-input-notice").textContent=spec.notice;
    document.getElementById("load-input-example").onclick=()=>{load(spec.example);showNotice("已载入案例的全部参数，可逐项修改；这次运行将使用完整参数模式。");};
    document.getElementById("clear-full-input").onclick=()=>{load({});showNotice("已清空参数；请补充后开始。");};
    document.getElementById("import-model").onchange=async event=>{try{const file=event.target.files[0];if(!file)return;if(file.size>12000)throw new Error("参数文件过大，限12KB。");const model=JSON.parse((await file.text()).replace(/^\uFEFF/,""));if(!model||Array.isArray(model)||typeof model!=="object")throw new Error("参数文件必须是工程参数对象。");
      const known=new Set(spec.fields.map(f=>f.path));function inspect(value,prefix=""){for(const [key,child] of Object.entries(value)){const path=prefix?prefix+"."+key:key;if(child&&typeof child==="object"&&!Array.isArray(child)){if(![...known].some(p=>p.startsWith(path+".")))throw new Error("参数文件包含未知字段："+path);inspect(child,path);}else if(!known.has(path))throw new Error("参数文件包含未知字段："+path);}}inspect(model);load(model);showNotice("已导入参数文件，请检查数值和单位后开始。");
    }catch(error){showNotice(error.message);}};
  }
  function displayPath(path){const field=spec?.fields.find(f=>f.path===path);return field?field.group+" · "+field.label:path;}
  return {initialize,collect,load,displayPath};
})();
