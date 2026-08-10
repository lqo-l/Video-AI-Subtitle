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
const humanSize=value=>{const amount=Number(value)||0;if(amount>=1024**3)return `${(amount/1024**3).toFixed(2)} GB`;if(amount>=1024**2)return `${(amount/1024**2).toFixed(1)} MB`;if(amount>=1024)return `${(amount/1024).toFixed(1)} KB`;return `${Math.round(amount)} B`;};

async function ensureService(){if(serviceReady){try{await request("/health");return;}catch(_){serviceReady=false;}}const response=await chrome.runtime.sendMessage({type:"ensure-service"});if(!response?.ok)throw new Error(response?.error||"本机启动器不可用");await new Promise(resolve=>setTimeout(resolve,500));serviceReady=true;}
async function request(path,options={}){const response=await fetch(`${API}${path}`,options);if(!response.ok)throw new Error((await response.json().catch(()=>null))?.detail||`服务错误 ${response.status}`);return response.json();}
function renderModel(data,query=modelQuery()){
  const modelName=`Whisper ${data.model||whisper_model.value} 模型`;
  const running=data.state==="running";
  model_state.textContent=running?`${data.progress||0}%`:data.valid?"✓ 可用":data.state==="failed"?"检查失败":"未安装";
  model_state.classList.toggle("ready",data.valid&&!running);
  model_state.classList.toggle("failed",data.state==="failed");
  model_progress.hidden=!running;
  model_bar.style.width=`${data.progress||0}%`;
  const missing=data.missing_files?.length?`缺少：${data.missing_files.join("、")}`:"";
  const reusable=(data.local_models||[]).filter(item=>item.valid&&item.model!==data.model).map(item=>`${item.model}（${humanSize(item.size)}）`).join("、");
  const transfer=running?`已下载 ${humanSize(data.downloaded)} / ${data.total?humanSize(data.total):"等待获取"} · ${humanSize(data.speed)}/s`:"";
  const status=running?`${data.stage}${data.source?` · ${data.source}`:""}`:data.valid?`${data.model} 模型已安装并可用`:data.stage==="模型未完整安装"?`${data.model} 模型文件不完整`:`本机未安装 ${modelName}`;
  model_detail.textContent=[status,transfer,missing,reusable?`其他已安装：${reusable}`:"",data.error].filter(Boolean).join(" · ");
  open_model.disabled=running||!data.valid||!data.resolved_path;
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
  // Moon Modified: preserve the last trustworthy status and animate it without flashing the card.
  if(!quiet){check_model.disabled=true;model_state.classList.add("checking");model_state.setAttribute("aria-busy","true");}
  try{await ensureService();renderModel(await request(`/models/status?${query}`),query);}
  catch(error){clearTimeout(modelPoll);model_state.textContent="检查失败";model_state.classList.add("failed");model_detail.textContent=error.message;check_model.disabled=false;download_model.disabled=false;download_model.textContent="下载 / 继续下载";}
  finally{modelRequestActive=false;if(!quiet){model_state.classList.remove("checking");model_state.removeAttribute("aria-busy");}}
}
function renderCuda(data){
  const running=data.state==="running";
  cuda_state.textContent=running?`${data.progress||0}%`:data.valid?"✓ 已配置":data.state==="failed"?"配置失败":"未配置";
  cuda_state.classList.toggle("ready",data.valid&&!running);
  cuda_state.classList.toggle("failed",data.state==="failed");
  cuda_progress.hidden=!running;
  cuda_bar.style.width=`${data.progress||0}%`;
  const transfer=running?`已下载 ${humanSize(data.downloaded)} / ${data.total?humanSize(data.total):"等待获取"} · ${humanSize(data.speed)}/s`:"";
  const status=running?`${data.stage}${data.component&&data.component!==data.stage?` · ${data.component}`:""}`:data.valid?"GPU 运行库已配置并通过加载检查":"默认使用 CPU，可按需配置 GPU 加速";
  cuda_detail.textContent=[status,transfer,data.error].filter(Boolean).join(" · ");
  open_cuda.disabled=running||!data.path;
  check_cuda.disabled=running;
  install_cuda.disabled=running||data.valid;
  install_cuda.textContent=data.valid?"GPU 已配置":running?"正在配置…":"一键配置 GPU";
  clearTimeout(cudaPoll);
  if(running)cudaPoll=setTimeout(()=>checkCuda({quiet:true}),700);
}
async function checkCuda({quiet=false}={}){
  if(cudaRequestActive)return;
  cudaRequestActive=true;
  // Moon Modified: keep the current result visible while the refresh is pending.
  if(!quiet){check_cuda.disabled=true;cuda_state.classList.add("checking");cuda_state.setAttribute("aria-busy","true");}
  try{await ensureService();renderCuda(await request("/cuda/status"));}
  catch(error){clearTimeout(cudaPoll);cuda_state.textContent="检查失败";cuda_state.classList.add("failed");cuda_detail.textContent=error.message;check_cuda.disabled=false;}
  finally{cudaRequestActive=false;if(!quiet){cuda_state.classList.remove("checking");cuda_state.removeAttribute("aria-busy");}}
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
check_model.onclick=()=>checkModel();
download_model.onclick=async()=>{const query=modelQuery();try{download_model.disabled=true;renderModel(await request(`/models/download?${query}`,{method:"POST"}),query);}catch(error){model_state.textContent="下载失败";model_state.classList.add("failed");model_detail.textContent=error.message;download_model.disabled=false;}};
open_model.onclick=async()=>{try{await request(`/models/open?${modelQuery()}`,{method:"POST"});}catch(error){model_detail.textContent=`无法打开模型文件夹：${error.message}`;}};
check_cuda.onclick=()=>checkCuda();
install_cuda.onclick=async()=>{
  if(!confirm("将下载约 1.37 GB 的 NVIDIA cuBLAS、cuDNN 与 NVRTC 到插件虚拟环境。继续吗？"))return;
  try{renderCuda(await request("/cuda/install",{method:"POST"}));}catch(error){cuda_state.textContent="配置失败";cuda_state.classList.add("failed");cuda_detail.textContent=error.message;}
};
open_cuda.onclick=async()=>{try{await request("/cuda/open",{method:"POST"});}catch(error){cuda_detail.textContent=`无法打开运行库文件夹：${error.message}`;}};
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
