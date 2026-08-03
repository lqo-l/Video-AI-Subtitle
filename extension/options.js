const API="http://127.0.0.1:8765";
const fields=["base_url","translation_model","summary_model","whisper_model","device"];
fetch(`${API}/config`).then(r=>r.json()).then(data=>fields.forEach(x=>document.getElementById(x).value=data[x])).catch(()=>message.textContent="请先启动本机服务");
form.onsubmit=async event=>{event.preventDefault();message.textContent="保存中…";const data=Object.fromEntries([...fields,"api_key"].map(x=>[x,document.getElementById(x).value]));try{const r=await fetch(`${API}/config`,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(data)});if(!r.ok)throw new Error((await r.json()).detail);message.textContent="已保存";api_key.value="";}catch(e){message.textContent=`失败：${e.message}`;}};
