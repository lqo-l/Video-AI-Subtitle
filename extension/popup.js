fetch("http://127.0.0.1:18765/health").then(r=>r.json()).then(()=>status.textContent="本机服务已连接").catch(()=>status.textContent="点击处理后将自动启动本机服务");
start.onclick=async()=>{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});chrome.tabs.sendMessage(tab.id,{type:"start"});window.close();};
options.onclick=()=>chrome.runtime.openOptionsPage();
