fetch("http://127.0.0.1:18765/health").then(r=>r.json()).then(()=>status.textContent="本机服务已连接").catch(()=>status.textContent="点击处理后将自动启动本机服务");
const serviceLeaseId=`ytba-popup-${crypto.randomUUID()}`;
// Moon Begin: only show update UI when a newer GitHub Release exists; local unpacked files still require a manual reinstall.
let updateInfo=null;
const updateBox=document.querySelector("#update"), updateTitle=document.querySelector("#update_title"), updateNote=document.querySelector("#update_note"), checkUpdate=document.querySelector("#check_update"), openUpdate=document.querySelector("#open_update"), updateStatus=document.querySelector("#update_status");
async function refreshUpdate(force=false){
  updateStatus.classList.remove("show");
  checkUpdate.disabled=true;
  try{
    updateInfo=await chrome.runtime.sendMessage({type:"check-extension-update",force});
    if(updateInfo?.available){
      updateBox.classList.add("show");
      updateTitle.textContent=`发现新版本 v${updateInfo.latestVersion}`;
      updateNote.textContent=`当前 v${updateInfo.currentVersion} · 下载后按安装说明更新扩展`;
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
checkUpdate.onclick=()=>refreshUpdate(true);
refreshUpdate();
// Moon End
start.onclick=async()=>{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});chrome.tabs.sendMessage(tab.id,{type:"start"});window.close();};
options.onclick=()=>chrome.runtime.openOptionsPage();
// Moon Begin: cache removal starts the local service only for the duration of the request.
clear_cache.onclick=async()=>{
  if(!confirm("确定清理所有视频字幕、摘要和关键点缓存吗？API 设置不会被删除。"))return;
  clear_cache.disabled=true;status.textContent="正在启动本机服务…";
  try{
    const native=await chrome.runtime.sendMessage({type:"ensure-service",leaseId:serviceLeaseId});
    if(!native?.ok)throw new Error(native?.error||"本机启动器不可用");
    const response=await fetch("http://127.0.0.1:18765/cache",{method:"DELETE"});
    if(!response.ok)throw new Error(`清理失败 ${response.status}`);
    const result=await response.json();
    status.textContent=`已清理 ${result.removed} 个视频缓存`;
  }catch(error){status.textContent=`清理失败：${error.message}`;}
  finally{chrome.runtime.sendMessage({type:"release-service",leaseId:serviceLeaseId});clear_cache.disabled=false;}
};
// Moon End
