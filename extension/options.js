// Moon Begin
const API="http://127.0.0.1:18765";
const fields=["base_url","translation_model","summary_model","whisper_model","whisper_model_path","whisper_download_source","device"];
const KEY_PLACEHOLDER="••••••••";
let modelPoll=null;
let cudaPoll=null;
let serviceReady=false;
const byId=id=>document.getElementById(id);
const humanSize=value=>value?`${(value/1024/1024).toFixed(1)} MB`:"0 MB";

async function ensureService(){if(serviceReady){try{await request("/health");return;}catch(_){serviceReady=false;}}const response=await chrome.runtime.sendMessage({type:"ensure-service"});if(!response?.ok)throw new Error(response?.error||"本机启动器不可用");await new Promise(resolve=>setTimeout(resolve,500));serviceReady=true;}
async function request(path,options={}){const response=await fetch(`${API}${path}`,options);if(!response.ok)throw new Error((await response.json().catch(()=>null))?.detail||`服务错误 ${response.status}`);return response.json();}
function renderModel(data){
  model_stage.textContent=data.stage+(data.source?` · ${data.source}`:"");
  model_percent.textContent=`${data.progress||0}%`;
  model_bar.style.width=`${data.progress||0}%`;
  const transfer=data.total?`${humanSize(data.downloaded)} / ${humanSize(data.total)}${data.speed?` · ${humanSize(data.speed)}/s`:""}`:"";
  model_detail.textContent=[data.resolved_path||data.configured_path||"未找到可用模型",transfer,data.error].filter(Boolean).join(" · ");
  if(data.state==="running"){clearTimeout(modelPoll);modelPoll=setTimeout(checkModel,700);}
}
async function checkModel(){check_model.disabled=true;model_stage.textContent="正在检查模型…";model_detail.textContent="正在读取模型目录和运行设备";try{await ensureService();renderModel(await request("/models/status"));}catch(error){model_stage.textContent=`检查失败：${error.message}`;}finally{check_model.disabled=false;}}
function renderCuda(data){
  cuda_stage.textContent=data.stage+(data.component?` · ${data.component}`:"");
  cuda_percent.textContent=`${data.progress||0}%`;
  cuda_bar.style.width=`${data.progress||0}%`;
  const transfer=data.total?`${humanSize(data.downloaded)} / ${humanSize(data.total)}${data.speed?` · ${humanSize(data.speed)}/s`:""}`:"";
  cuda_detail.textContent=[data.path,transfer,data.error].filter(Boolean).join(" · ")||"默认使用 CPU。主动安装约需下载 1.37 GB。";
  install_cuda.disabled=data.state==="running"||data.valid;
  install_cuda.textContent=data.valid?"GPU 已配置":data.state==="running"?"正在配置…":"一键配置 GPU";
  if(data.state==="running"){clearTimeout(cudaPoll);cudaPoll=setTimeout(checkCuda,700);}
}
async function checkCuda(){check_cuda.disabled=true;cuda_stage.textContent="正在检查 GPU 环境…";cuda_detail.textContent="正在检查显卡、cuBLAS 与 cuDNN";try{await ensureService();renderCuda(await request("/cuda/status"));}catch(error){cuda_stage.textContent=`检查失败：${error.message}`;}finally{check_cuda.disabled=false;}}

ensureService().then(()=>request("/config")).then(async data=>{
  fields.forEach(id=>byId(id).value=data[id]??"");
  if(data.api_key_configured){api_key.value=KEY_PLACEHOLDER;api_key.dataset.configured="true";}
  const stored=await chrome.storage.local.get({panelPrefs:{opacity:.94}});
  panel_opacity.value=Math.round((stored.panelPrefs?.opacity??.94)*100);opacity_value.value=`${panel_opacity.value}%`;
  checkModel();
  checkCuda();
}).catch(error=>message.textContent=`无法读取设置：${error.message}`);

api_key.onfocus=()=>{if(api_key.value===KEY_PLACEHOLDER)api_key.value="";};
api_key.onblur=()=>{if(!api_key.value&&api_key.dataset.configured==="true")api_key.value=KEY_PLACEHOLDER;};
panel_opacity.oninput=()=>opacity_value.value=`${panel_opacity.value}%`;
check_model.onclick=checkModel;
download_model.onclick=async()=>{try{download_model.disabled=true;renderModel(await request("/models/download",{method:"POST"}));}catch(error){model_stage.textContent=`下载失败：${error.message}`;}finally{download_model.disabled=false;}};
check_cuda.onclick=checkCuda;
install_cuda.onclick=async()=>{
  if(!confirm("将下载约 1.37 GB 的 NVIDIA cuBLAS、cuDNN 与 NVRTC 到插件虚拟环境。继续吗？"))return;
  try{renderCuda(await request("/cuda/install",{method:"POST"}));}catch(error){cuda_stage.textContent=`配置失败：${error.message}`;}
};
reset_translation.onclick=()=>{translation_model.value="deepseek-v4-flash";message.textContent="已恢复默认值，请点击保存设置";};
window.addEventListener("beforeunload",()=>chrome.runtime.sendMessage({type:"release-service"}));
form.onsubmit=async event=>{
  event.preventDefault();message.textContent="保存中…";
  try{
    await ensureService();
    const data=Object.fromEntries(fields.map(id=>[id,byId(id).value]));
    data.api_key=api_key.value===KEY_PLACEHOLDER?"":api_key.value;
    const saved=await request("/config",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});
    const stored=await chrome.storage.local.get({panelPrefs:{}});
    await chrome.storage.local.set({panelPrefs:{...stored.panelPrefs,opacity:Number(panel_opacity.value)/100}});
    message.textContent="已保存并应用";
    if(saved.api_key_configured){api_key.value=KEY_PLACEHOLDER;api_key.dataset.configured="true";}
    checkModel();
    checkCuda();
  }catch(error){message.textContent=`保存失败：${error.message}`;}
};
// Moon End
