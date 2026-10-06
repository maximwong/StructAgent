"use strict";
// Generic renderer: each loaded plugin describes its complete envelope fields.
const StructuredInput = (()=>{
  let spec=null, revision=0, apiCall=null, showNotice=null;
  const inputs=new Map();
  const get=id=>document.getElementById(id);
  const read=(obj,path)=>path.split('.').reduce((v,k)=>v?.[k],obj);
  function write(obj,path,value){const keys=path.split('.');let at=obj;for(const k of keys.slice(0,-1))at=at[k]??={};at[keys.at(-1)]=value;}
  function mode(){return spec?.modes.find(m=>m.id===get('structured-mode').value);}
  function draw(){revision++;inputs.clear();const container=get('structured-fields');container.replaceChildren();const groups=new Map();
    for(const f of mode()?.fields||[]){let group=groups.get(f.group);if(!group){group=document.createElement('details');group.open=true;const title=document.createElement('summary');title.textContent=f.group;group.append(title);container.append(group);groups.set(f.group,group);}
      const label=document.createElement('label');label.textContent=f.label+(f.required?' *':'');const schema=f.schema,choices=schema.enum||(schema.const!==undefined?[schema.const]:schema.type==='boolean'?[true,false]:null);let input;
      if(choices){input=document.createElement('select');input.append(new Option('请选择',''));for(const value of choices)input.append(new Option(typeof value==='boolean'?(value?'是':'否'):f.choices_labels?.[String(value)]||String(value),String(value)));}
      else{input=document.createElement('input');input.type=['number','integer'].includes(schema.type)?'number':'text';if(input.type==='number')input.step=schema.type==='integer'?'1':'any';}
      input.id='structured-'+f.path.replaceAll('.','-');input.dataset.path=f.path;label.htmlFor=input.id;group.append(label,input);inputs.set(f.path,input);
    }
  }
  function collect(){const envelope={tool:mode().tool};for(const f of mode().fields){const text=inputs.get(f.path).value.trim();if(!text)continue;let value=text;const s=f.schema;
      if(s.type==='boolean')value=text==='true';else if(['number','integer'].includes(s.type)||typeof s.const==='number'||s.enum?.some(v=>typeof v==='number')){value=Number(text);if(!Number.isFinite(value))throw new Error(f.label+'须为有限数值。');}
      write(envelope,f.path,value);
    }return {operation:mode().operation,envelope};}
  function load(envelope){const next=spec.modes.find(m=>m.tool===envelope.tool&&(envelope.parameters?.design_result_ref?m.id==='reference':m.id!=='reference'));if(!next)throw new Error('请求工具与操作模式不匹配。');get('structured-mode').value=next.id;draw();for(const [path,input] of inputs){const value=read(envelope,path);input.value=value===undefined?'':String(value);}}
  function configure(profession,call,notify){revision++;spec=profession.form;apiCall=call;showNotice=notify;get('structured-notice').textContent=spec.notice;get('structured-mode').replaceChildren(...spec.modes.map(m=>new Option(m.name,m.id)));draw();get('structured-examples').replaceChildren();
    for(const example of spec.examples||[]){const button=document.createElement('button');button.type='button';button.textContent=example.name;button.onclick=()=>{load(example.envelope);showNotice('已显式载入匿名教学案例；请核对每项工程输入。');};get('structured-examples').append(button);}
    get('structured-mode').onchange=()=>{draw();showNotice('已切换操作模式，请完整填写本次输入。');};get('structured-clear').onclick=()=>{draw();showNotice('已清空全部参数。');};
    get('structured-import').value='';get('structured-import').onchange=async event=>{const generation=++revision;try{const file=event.target.files[0];if(!file)return;if(file.size>15000)throw new Error('JSON文件限15KB。');const text=await file.text();if(generation!==revision)return;const result=await apiCall('/api/structured-import','POST',{profession:profession.id,json:text});if(generation!==revision)return;load(result.envelope);showNotice('完整JSON已验证并导入，工具、项目标识、单位规范与全部参数均已保留。');}catch(error){if(generation===revision)showNotice(error.message);}};
  }
  function invalidate(){revision++;}
  function displayPath(path){const f=spec?.modes.flatMap(m=>m.fields).find(f=>f.path===path);return f?f.group+' · '+f.label:path;}
  function friendly(text){if(!spec)return text;const fields=[...new Map(spec.modes.flatMap(m=>m.fields).map(f=>[f.path,f])).values()].sort((a,b)=>b.path.length-a.path.length);for(const f of fields)text=text.replaceAll(f.path,displayPath(f.path));return text;}
  return {configure,collect,load,invalidate,displayPath,friendly};
})();
