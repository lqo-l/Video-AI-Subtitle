// Moon Begin: never rely on an element ID becoming a global variable. `status`
// collides with the built-in window.status string and silently drops UI writes.
const serviceStatus=document.querySelector("#status");
async function refreshServiceStatus(){
  const controller=new AbortController();
  const timeout=setTimeout(()=>controller.abort(),1500);
  try{
    const response=await fetch("http://127.0.0.1:18765/health",{signal:controller.signal,cache:"no-store"});
    const health=await response.json();
    if(!response.ok||health?.ok!==true)throw new Error("服务状态异常");
    serviceStatus.textContent="本机服务已连接";
  }catch(_){
    serviceStatus.textContent="本机服务未启动，处理时自动启动";
  }finally{
    clearTimeout(timeout);
  }
}
refreshServiceStatus();
// Moon End
const serviceLeaseId=`ytba-popup-${crypto.randomUUID()}`;
// Moon Begin: update progress stays inside the popup and reloads only after the native helper has replaced release files.
let updateInfo=null;
const updateBox=document.querySelector("#update"), updateTitle=document.querySelector("#update_title"), updateNote=document.querySelector("#update_note"), checkUpdate=document.querySelector("#check_update"), openUpdate=document.querySelector("#open_update"), installUpdate=document.querySelector("#install_update"), updateStatus=document.querySelector("#update_status"), updateProgress=document.querySelector("#update_progress"), updateProgressText=document.querySelector("#update_progress_text"), updateProgressBar=document.querySelector("#update_progress_bar");
function formatBytes(value){
  const bytes=Number(value)||0;
  if(bytes<1024)return `${bytes} B`;
  if(bytes<1024*1024)return `${(bytes/1024).toFixed(1)} KB`;
  return `${(bytes/1024/1024).toFixed(1)} MB`;
}
function renderUpdateProgress(progress){
  if(!progress||progress.state!=="running"){updateProgress.classList.remove("show","indeterminate");return;}
  const downloaded=Number(progress.downloaded)||0,total=Number(progress.total)||0,speed=Number(progress.speed)||0;
  const knownTotal=total>0;
  updateProgress.classList.add("show");
  updateProgress.classList.toggle("indeterminate",!knownTotal);
  const percent=knownTotal?Math.min(100,Math.floor(downloaded*100/total)):0;
  updateProgressBar.style.width=`${percent}%`;
  if(knownTotal){
    updateProgressText.textContent=`${progress.stage||"正在下载"} · ${percent}% · ${formatBytes(downloaded)} / ${formatBytes(total)} · ${formatBytes(speed)}/s`;
  }else{
    updateProgressText.textContent=progress.stage||"正在连接更新服务器";
  }
}
async function refreshUpdate(force=false){
  updateStatus.classList.remove("show");
  checkUpdate.disabled=true;
  try{
    updateInfo=await chrome.runtime.sendMessage({type:"check-extension-update",force});
    if(updateInfo?.available){
      updateBox.classList.add("show");
      updateTitle.textContent=`发现新版本 v${updateInfo.latestVersion}`;
      updateNote.textContent=`当前 v${updateInfo.currentVersion} · 将保留本机配置和缓存`;
    }else{
      updateBox.classList.remove("show");
      updateStatus.textContent=updateInfo?.error||`已是最新版本 v${updateInfo?.currentVersion||chrome.runtime.getManifest().version}`;
      updateStatus.classList.add("show");
    }
  }catch(_){
    updateBox.classList.remove("show");
    updateStatus.textContent="暂时无法检查更新";
    updateStatus.classList.add("show");
  }
  finally{checkUpdate.disabled=false;}
}
openUpdate.onclick=()=>{if(updateInfo?.url)chrome.tabs.create({url:updateInfo.url});};
installUpdate.onclick=async()=>{
  if(!updateInfo?.available)return;
  installUpdate.disabled=true;openUpdate.disabled=true;checkUpdate.disabled=true;
  installUpdate.textContent="正在更新…";
  updateNote.textContent="完成后将自动重载扩展，请勿关闭 Chrome";
  renderUpdateProgress({state:"running",stage:"正在连接更新服务器"});
  try{
    const result=await chrome.runtime.sendMessage({type:"install-extension-update",update:updateInfo});
    if(!result?.ok)throw new Error(result?.error||"更新未完成");
    renderUpdateProgress({state:"running",stage:"更新完成，正在重载扩展…",downloaded:1,total:1});
    updateNote.textContent="更新完成，正在重载扩展…";
    setTimeout(()=>chrome.runtime.reload(),300);
  }catch(error){
    renderUpdateProgress(null);
    updateNote.textContent=`更新失败：${error.message}`;
    installUpdate.textContent="重试更新";
    installUpdate.disabled=false;openUpdate.disabled=false;checkUpdate.disabled=false;
  }
};
chrome.storage.onChanged.addListener((changes,area)=>{
  if(area==="local"&&changes.ytbaExtensionUpdateProgress)renderUpdateProgress(changes.ytbaExtensionUpdateProgress.newValue);
});
checkUpdate.onclick=()=>refreshUpdate(true);
refreshUpdate();
// Moon End
start.onclick=async()=>{
  start.disabled=true;serviceStatus.textContent="正在连接当前视频…";
  try{
    const [tab]=await chrome.tabs.query({active:true,currentWindow:true});
    const result=await chrome.runtime.sendMessage({type:"start-current-video",tab});
    if(!result?.ok)throw new Error(result?.error||"无法连接当前视频页面");
    window.close();
  }catch(error){serviceStatus.textContent=`无法处理：${error.message}`;start.disabled=false;}
};
options.onclick=()=>chrome.runtime.openOptionsPage();
// Moon Begin: cache removal starts the local service only for the duration of the request.
clear_cache.onclick=async()=>{
  if(!confirm("确定清理所有视频字幕、摘要和关键点缓存吗？API 设置不会被删除。"))return;
  clear_cache.disabled=true;serviceStatus.textContent="正在启动本机服务…";
  try{
    const native=await chrome.runtime.sendMessage({type:"ensure-service",leaseId:serviceLeaseId});
    if(!native?.ok)throw new Error(native?.error||"本机启动器不可用");
    const response=await fetch("http://127.0.0.1:18765/cache",{method:"DELETE"});
    if(!response.ok)throw new Error(`清理失败 ${response.status}`);
    const result=await response.json();
    serviceStatus.textContent=`已清理 ${result.removed} 个视频缓存`;
  }catch(error){serviceStatus.textContent=`清理失败：${error.message}`;}
  finally{chrome.runtime.sendMessage({type:"release-service",leaseId:serviceLeaseId});clear_cache.disabled=false;}
};
// Moon End
