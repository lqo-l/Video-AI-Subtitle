// Moon Begin
const API="http://127.0.0.1:18765";
const fields=["base_url","translation_model","summary_model","whisper_model","whisper_model_path","whisper_download_source","device"];
const KEY_PLACEHOLDER="••••••••";
let modelPoll=null;
let cudaPoll=null;
let modelRequestActive=false;
let cudaRequestActive=false;
let serviceReady=false;
const byId=id=>document.getElementById(id);
const humanSize=value=>value?`${(value/1024/1024).toFixed(1)} MB`:"0 MB";

async function ensureService(){if(serviceReady){try{await request("/health");return;}catch(_){serviceReady=false;}}const response=await chrome.runtime.sendMessage({type:"ensure-service"});if(!response?.ok)throw new Error(response?.error||"本机启动器不可用");await new Promise(resolve=>setTimeout(resolve,500));serviceReady=true;}
async function request(path,options={}){const response=await fetch(`${API}${path}`,options);if(!response.ok)throw new Error((await response.json().catch(()=>null))?.detail||`服务错误 ${response.status}`);return response.json();}
function renderModel(data,query=modelQuery()){
  model_stage.textContent=data.stage+(data.source?` · ${data.source}`:"");
  model_percent.textContent=`${data.progress||0}%`;
  model_bar.style.width=`${data.progress||0}%`;
  const transfer=data.total?`${humanSize(data.downloaded)} / ${humanSize(data.total)}${data.speed?` · ${humanSize(data.speed)}/s`:""}`:"";
  const missing=data.missing_files?.length?`缺少：${data.missing_files.join("、")}`:"";
  const reusable=(data.local_models||[]).filter(item=>item.valid&&item.model!==data.model).map(item=>`${item.model}（${humanSize(item.size)}）`).join("、");
  model_detail.textContent=[data.resolved_path||data.configured_path||"未找到当前型号",missing,transfer,reusable?`其他已安装：${reusable}`:"",data.error].filter(Boolean).join(" · ");
  const running=data.state==="running";
  check_model.disabled=running;
  download_model.disabled=running;
  download_model.textContent=running?"正在下载…":"下载 / 继续下载";
  clearTimeout(modelPoll);
  if(running)modelPoll=setTimeout(()=>checkModel({quiet:true,query}),700);
}
function modelQuery(){return new URLSearchParams({model:whisper_model.value,model_path:whisper_model_path.value,source:whisper_download_source.value}).toString();}
async function checkModel({quiet=false,query=modelQuery()}={}){
  if(modelRequestActive)return;
  modelRequestActive=true;
  if(!quiet){check_model.disabled=true;model_stage.textContent=`正在检查 ${whisper_model.value}…`;model_detail.textContent="正在读取模型目录和运行设备";}
  try{await ensureService();renderModel(await request(`/models/status?${query}`),query);}
  catch(error){clearTimeout(modelPoll);model_stage.textContent=`检查失败：${error.message}`;check_model.disabled=false;download_model.disabled=false;download_model.textContent="下载 / 继续下载";}
  finally{modelRequestActive=false;}
}
function renderCuda(data){
  cuda_stage.textContent=data.stage+(data.component?` · ${data.component}`:"");
  cuda_percent.textContent=`${data.progress||0}%`;
  cuda_bar.style.width=`${data.progress||0}%`;
  const transfer=data.total?`${humanSize(data.downloaded)} / ${humanSize(data.total)}${data.speed?` · ${humanSize(data.speed)}/s`:""}`:"";
  cuda_detail.textContent=[data.path,transfer,data.error].filter(Boolean).join(" · ")||"默认使用 CPU。主动安装约需下载 1.37 GB。";
  const running=data.state==="running";
  check_cuda.disabled=running;
  install_cuda.disabled=running||data.valid;
  install_cuda.textContent=data.valid?"GPU 已配置":running?"正在配置…":"一键配置 GPU";
  clearTimeout(cudaPoll);
  if(running)cudaPoll=setTimeout(()=>checkCuda({quiet:true}),700);
}
async function checkCuda({quiet=false}={}){
  if(cudaRequestActive)return;
  cudaRequestActive=true;
  if(!quiet){check_cuda.disabled=true;cuda_stage.textContent="正在检查 GPU 环境…";cuda_detail.textContent="正在检查显卡、cuBLAS 与 cuDNN";}
  try{await ensureService();renderCuda(await request("/cuda/status"));}
  catch(error){clearTimeout(cudaPoll);cuda_stage.textContent=`检查失败：${error.message}`;check_cuda.disabled=false;}
  finally{cudaRequestActive=false;}
}

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
download_model.onclick=async()=>{const query=modelQuery();try{download_model.disabled=true;renderModel(await request(`/models/download?${query}`,{method:"POST"}),query);}catch(error){model_stage.textContent=`下载失败：${error.message}`;download_model.disabled=false;}};
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
