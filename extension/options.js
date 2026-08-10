// Moon Begin
const API="http://127.0.0.1:18765";
const fields=["base_url","translation_model","summary_model","whisper_model","whisper_model_path","model_install_dir","cuda_install_dir","whisper_download_source","device"];
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
  const running=data.state==="running";
  model_state.textContent=running?`${data.progress||0}%`:data.valid?"✓ 可用":data.state==="failed"?"检查失败":data.state==="cancelled"?"已取消":"未安装";
  model_state.classList.toggle("ready",data.valid&&!running);
  model_state.classList.toggle("failed",data.state==="failed");
  // Moon Add: surface local availability and size where the model decision is made.
  const localModels=new Map((data.local_models||[]).filter(item=>item.valid).map(item=>[item.model,item]));
  if(data.valid&&!localModels.has(data.model))localModels.set(data.model,{size:data.size,valid:true});
  [...whisper_model.options].forEach(option=>{const local=localModels.get(option.value);option.textContent=local?`${option.value} · 已安装 ${humanSize(local.size)}`:option.value;});
  model_progress.hidden=!running;
  model_bar.style.width=`${data.progress||0}%`;
  const missing=data.missing_files?.length?`缺少：${data.missing_files.join("、")}`:"";
  const transfer=running?`已下载 ${humanSize(data.downloaded)} / ${data.total?humanSize(data.total):"等待获取"} · ${humanSize(data.speed)}/s`:"";
  const status=running?`${data.stage}${data.source?` · ${data.source}`:""}`:data.state==="cancelled"?data.stage:data.state==="failed"?data.error:data.stage==="模型未完整安装"?`${data.model} 模型文件不完整`:"";
  model_detail.textContent=[status,transfer,missing].filter(Boolean).join(" · ");
  model_detail.hidden=!model_detail.textContent;
  open_model.disabled=running||!data.valid||!data.resolved_path;
  check_model.disabled=running;
  download_model.disabled=running;
  download_model.hidden=data.valid&&!running;
  choose_model_dir.disabled=running;
  clear_model_cache.disabled=running;
  download_model.textContent=running?"正在下载…":"下载 / 继续下载";
  cancel_model_download.hidden=!running;
  cancel_model_download.disabled=false;
  clearTimeout(modelPoll);
  if(running)modelPoll=setTimeout(()=>checkModel({quiet:true,query}),700);
}
function modelQuery(){return new URLSearchParams({model:whisper_model.value,model_path:whisper_model_path.value,install_dir:model_install_dir.value,source:whisper_download_source.value}).toString();}
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
  cuda_state.textContent=running?`${data.progress||0}%`:data.valid?"✓ 已配置":data.state==="failed"?"配置失败":data.state==="cancelled"?"已取消":"未配置";
  cuda_state.classList.toggle("ready",data.valid&&!running);
  cuda_state.classList.toggle("failed",data.state==="failed");
  cuda_progress.hidden=!running;
  cuda_bar.style.width=`${data.progress||0}%`;
  const transfer=running?`已下载 ${humanSize(data.downloaded)} / ${data.total?humanSize(data.total):"等待获取"} · ${humanSize(data.speed)}/s`:"";
  const status=running?`${data.stage}${data.component&&data.component!==data.stage?` · ${data.component}`:""}`:data.state==="cancelled"?data.stage:"";
  cuda_detail.textContent=[status,transfer,data.error].filter(Boolean).join(" · ");
  cuda_detail.hidden=!cuda_detail.textContent;
  open_cuda.disabled=running||!data.path;
  check_cuda.disabled=running;
  install_cuda.disabled=running||data.valid;
  install_cuda.hidden=data.valid&&!running;
  choose_cuda_dir.disabled=running;
  clear_cuda_cache.disabled=running;
  install_cuda.textContent=data.valid?"GPU 已配置":running?"正在配置…":"一键配置 GPU";
  const downloading=running&&(!data.total||data.downloaded<data.total);
  cancel_cuda_download.hidden=!downloading;
  cancel_cuda_download.disabled=false;
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
cancel_model_download.onclick=async()=>{try{cancel_model_download.disabled=true;renderModel(await request("/models/download/cancel",{method:"POST"}));}catch(error){model_detail.textContent=`无法取消下载：${error.message}`;cancel_model_download.disabled=false;}};
async function clearTransferCache(kind){
  const label=kind==="model"?`Whisper ${whisper_model.value} 模型的未完成下载`:"GPU 运行库安装包";
  if(!confirm(`确定清理${label}？\n\n已安装且可用的文件不会被删除。清理后再次下载将从头开始。`))return;
  const button=kind==="model"?clear_model_cache:clear_cuda_cache;
  button.disabled=true;
  try{
    const query=new URLSearchParams({kind,model:whisper_model.value});
    const result=await request(`/storage/download-cache?${query}`,{method:"DELETE"});
    message.textContent=result.removed_files?`已清理 ${result.removed_files} 个文件，释放 ${humanSize(result.freed_bytes)}`:"没有可清理的下载缓存";
    if(kind==="model")await checkModel();else await checkCuda();
  }catch(error){message.textContent=`清理失败：${error.message}`;}
  finally{button.disabled=false;}
}
clear_model_cache.onclick=()=>clearTransferCache("model");
clear_cuda_cache.onclick=()=>clearTransferCache("cuda");
open_model.onclick=async()=>{try{await request(`/models/open?${modelQuery()}`,{method:"POST"});}catch(error){model_detail.textContent=`无法打开模型文件夹：${error.message}`;}};
check_cuda.onclick=()=>checkCuda();
install_cuda.onclick=async()=>{
  if(!confirm("将下载约 1.37 GB 的 NVIDIA cuBLAS、cuDNN 与 NVRTC 到插件虚拟环境。继续吗？"))return;
  try{renderCuda(await request("/cuda/install",{method:"POST"}));}catch(error){cuda_state.textContent="配置失败";cuda_state.classList.add("failed");cuda_detail.textContent=error.message;}
};
cancel_cuda_download.onclick=async()=>{try{cancel_cuda_download.disabled=true;renderCuda(await request("/cuda/install/cancel",{method:"POST"}));}catch(error){cuda_detail.textContent=`无法取消下载：${error.message}`;cancel_cuda_download.disabled=false;}};
function askMigration(kind){
  migration_text.textContent=`当前安装位置已有${kind==="model"?"模型":"GPU 运行库"}。迁移会复制到新位置并保留原文件。`;
  migration_dialog.showModal();
  return new Promise(resolve=>{
    let settled=false;
    const finish=choice=>{if(settled)return;settled=true;if(migration_dialog.open)migration_dialog.close();resolve(choice);};
    migration_dialog.oncancel=event=>{event.preventDefault();finish("cancel");};
    migration_dialog.querySelectorAll("[data-migration]").forEach(button=>button.onclick=()=>finish(button.dataset.migration));
  });
}
async function chooseStorageDirectory(kind){
  const button=kind==="model"?choose_model_dir:choose_cuda_dir;
  const input=kind==="model"?model_install_dir:cuda_install_dir;
  button.disabled=true;
  try{
    const selected=await request(`/storage/select?kind=${kind}`,{method:"POST"});
    if(!selected.changed)return;
    const choice=selected.has_existing?await askMigration(kind):"keep";
    if(choice==="cancel")return;
    const migrate=choice==="migrate";
    message.textContent=migrate?"正在迁移已有文件，请勿关闭设置页…":"正在更新安装位置…";
    const result=await request("/storage/path",{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({kind,path:selected.path,migrate})});
    input.value=result.path;
    message.textContent=result.migrated?`已迁移 ${result.migrated_items} 项内容并更新安装位置`:"已更新安装位置，旧文件保持不变";
    if(kind==="model")await checkModel();else await checkCuda();
  }catch(error){message.textContent=`无法更新安装位置：${error.message}`;}
  finally{button.disabled=false;}
}
choose_model_dir.onclick=()=>chooseStorageDirectory("model");
choose_cuda_dir.onclick=()=>chooseStorageDirectory("cuda");
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
