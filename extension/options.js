const API="http://127.0.0.1:18765";
const fields=["base_url","translation_model","summary_model","whisper_model","device"];
// Moon Begin: represent an existing secret without returning it to the extension.
const KEY_PLACEHOLDER="••••••••";
chrome.runtime.sendMessage({type:"ensure-service"}).then(response=>{
  if(!response?.ok)throw new Error(response?.error||"本机启动器不可用");
  return new Promise(resolve=>setTimeout(resolve,500));
}).then(()=>fetch(`${API}/config`)).then(r=>r.json()).then(data=>{
  fields.forEach(x=>document.getElementById(x).value=data[x]);
  if(data.api_key_configured){api_key.value=KEY_PLACEHOLDER;api_key.dataset.configured="true";}
}).catch(()=>message.textContent="请先启动本机服务");
api_key.onfocus=()=>{if(api_key.value===KEY_PLACEHOLDER)api_key.value="";};
api_key.onblur=()=>{if(!api_key.value&&api_key.dataset.configured==="true")api_key.value=KEY_PLACEHOLDER;};
reset_translation.onclick=()=>{translation_model.value="deepseek-v4-flash";message.textContent="已恢复默认值，请点击保存设置";};
window.addEventListener("beforeunload",()=>chrome.runtime.sendMessage({type:"release-service"}));
form.onsubmit=async event=>{event.preventDefault();message.textContent="保存中…";try{const native=await chrome.runtime.sendMessage({type:"ensure-service"});if(!native?.ok)throw new Error(native?.error||"本机启动器不可用");await new Promise(resolve=>setTimeout(resolve,500));const data=Object.fromEntries(fields.map(x=>[x,document.getElementById(x).value]));data.api_key=api_key.value===KEY_PLACEHOLDER?"":api_key.value;const r=await fetch(`${API}/config`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});if(!r.ok)throw new Error((await r.json()).detail);const saved=await r.json();message.textContent="已保存";if(saved.api_key_configured){api_key.value=KEY_PLACEHOLDER;api_key.dataset.configured="true";}chrome.runtime.sendMessage({type:"release-service"});}catch(e){message.textContent=`失败:${e.message}`;}};// Moon End
