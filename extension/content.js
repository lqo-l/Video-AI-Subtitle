(() => {
  const API = "http://127.0.0.1:18765";
  let job = null;
  let result = null;
  let overlay = null;
  let lastUrl = "";
  let pollTimer = null;
  let renderedTranslationCount = -1;
  let activeTab = "transcript";
  let playbackReady = false;
  let panelCollapsed = false;
  let assistantDismissed = false;
  let playerResizeObserver = null;
  let renderedSummary = "";
  let summaryAutoOpened = false;
  let transcriptComplete = false;
  let summaryComplete = false;
  let layoutAnimationFrame = 0;
  const defaultSubtitlePrefs = {visible:true, language:"bilingual", fontScale:1, bottom:10, background:false};
  let subtitlePrefs = {...defaultSubtitlePrefs};
  // Moon Add: persist the sidebar edge and user-selected width across videos.
  const defaultPanelPrefs = {side:"right", width:390, layoutMode:"overlay", opacity:.94};
  let panelPrefs = {...defaultPanelPrefs};
  const defaultLauncherPrefs = {side:"right", top:180};
  let launcherPrefs = {...defaultLauncherPrefs};
  const site = location.hostname.includes("bilibili.com") ? "bilibili" : "youtube";

  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const formatTime = seconds => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

  async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `本机服务错误 ${response.status}`);
    return response.json();
  }

  function video() { return document.querySelector("video"); }

  function playerContainer() {
    const player=video();
    if(!player)return null;
    return site==="bilibili"
      ? player.closest(".bpx-player-container,.bilibili-player,.bilibili-player-video") || player.parentElement
      : player.closest(".html5-video-player") || player.parentElement;
  }

  function isVideoPage() {
    return site==="bilibili"
      ? location.pathname.startsWith("/video/") || location.pathname.startsWith("/bangumi/play/")
      : location.pathname==="/watch";
  }

  function sourceLanguageLabel() {
    return ({en:"英文",ja:"日文",zh:"中文"})[result?.source_language] || "原文";
  }

  async function safeSendMessage(message) {
    let lastError = null;
    for (let attempt = 0; attempt < 3; attempt++) {
      try { return await chrome.runtime.sendMessage(message); }
      catch (e) {
        lastError = e;
        console.log("[YTBA] sendMessage retry", attempt + 1, "/ 3:", e.message || e);
        if (attempt < 2) await new Promise(r => setTimeout(r, 1000 * (attempt + 1)));
      }
    }
    console.error("[YTBA] sendMessage failed after 3 attempts:", lastError);
    throw new Error("扩展通信失败，请刷新当前视频页面后重试 (Ctrl+Shift+R)");
  }

  async function ensureService() {
    // Moon Add: ask the native host to start, then wait until HTTP is ready.
    const response = await safeSendMessage({type:"ensure-service"});
    if (!response?.ok) throw new Error(response?.error || "本机启动器不可用，请运行 install-native-host.ps1");
    for (let attempt = 0; attempt < 30; attempt++) {
      try { await api("/health"); return; } catch (_) { await new Promise(resolve => setTimeout(resolve, 300)); }
    }
    throw new Error("本机服务启动超时");
  }

  function showPrompt() {
    if (assistantDismissed || document.querySelector("#ytba-prompt") || document.querySelector("#ytba-root")) return;
    const box = document.createElement("div");
    box.id = "ytba-prompt";
    box.innerHTML = `<strong>生成原文与中文字幕？</strong><div style="margin-top:6px;color:#bbc2ce">支持英文/日文，处理完成后提醒你手动播放。</div><div class="actions"><button class="ytba-button secondary" data-no>暂不</button><button class="ytba-button" data-yes>开始处理</button></div>`;
    box.querySelector("[data-no]").onclick = () => box.remove();
    box.querySelector("[data-yes]").onclick = () => { box.remove(); start(); };
    document.body.appendChild(box);
  }

  // Moon Begin: Bilibili uses a quiet draggable launcher instead of a modal prompt.
  function showLauncher() {
    if(assistantDismissed||document.querySelector("#ytba-launcher")||document.querySelector("#ytba-root"))return;
    const launcher=document.createElement("button");
    launcher.id="ytba-launcher";
    launcher.className="ytba-floating-launcher";
    launcher.textContent="译";
    launcher.title="点击开始处理，拖拽可移动；右键关闭";
    launcher.setAttribute("aria-label","打开 AI 双语字幕助手");
    document.body.appendChild(launcher);
    applyLauncherPrefs();
    bindLauncherDrag(launcher,()=>{launcher.remove();start();});
    bindDismissContextMenu(launcher);
    updateFullscreenLayout();
  }

  function applyLauncherPrefs(){
    launcherPrefs.side=launcherPrefs.side==="left"?"left":"right";
    launcherPrefs.top=Math.round(Math.min(Math.max(72,Number(launcherPrefs.top)||180),Math.max(72,window.innerHeight-72)));
    document.body.style.setProperty("--ytba-launcher-top",`${launcherPrefs.top}px`);
    document.body.classList.toggle("ytba-launcher-left",launcherPrefs.side==="left");
    document.body.classList.toggle("ytba-launcher-right",launcherPrefs.side==="right");
  }

  function bindLauncherDrag(element,onClick){
    element.onpointerdown=event=>{
      if(event.button!==0)return;
      event.preventDefault();
      element.setPointerCapture(event.pointerId);
      const origin={x:event.clientX,y:event.clientY,top:launcherPrefs.top};
      let moved=false;
      element.classList.add("dragging");
      element.onpointermove=move=>{
        if(Math.hypot(move.clientX-origin.x,move.clientY-origin.y)>5)moved=true;
        launcherPrefs.top=Math.min(Math.max(58,origin.top+move.clientY-origin.y),window.innerHeight-58);
        launcherPrefs.side=move.clientX<window.innerWidth/2?"left":"right";
        applyLauncherPrefs();
      };
      const finish=()=>{
        element.onpointermove=element.onpointerup=element.onpointercancel=null;
        element.classList.remove("dragging");
        chrome.storage.local.set({launcherPrefs});
        if(element.closest("#ytba-root")&&moved){
          panelPrefs.side=launcherPrefs.side;
          chrome.storage.local.set({panelPrefs});
          applyPanelPrefs();
        }
        if(!moved)onClick();
      };
      element.onpointerup=finish;element.onpointercancel=finish;
    };
  }

  function bindDismissContextMenu(element){
    // Moon Add: edge launchers have no room for another icon, so right-click closes them.
    element.oncontextmenu=event=>{
      event.preventDefault();
      event.stopPropagation();
      closeAssistant();
    };
  }
  // Moon End

  function ensurePanel() {
    let root = document.querySelector("#ytba-root");
    if (root) return root;
    document.querySelector("#ytba-launcher")?.remove();
    root = document.createElement("aside");
    root.id = "ytba-root";
    root.innerHTML = `<button class="ytba-edge-handle" data-expand title="展开字幕助手；右键关闭" aria-label="展开字幕助手">译</button><div class="ytba-resize-handle" data-resize title="拖拽调整侧栏宽度"></div><div class="ytba-head"><div class="ytba-brand"><span class="ytba-brand-mark" aria-hidden="true">译</span><span><strong>AI 双语字幕助手</strong><small>字幕 · 翻译 · 摘要</small></span></div><button class="ytba-icon-button" data-retry title="从缓存继续" aria-label="重试">↻</button><button class="ytba-icon-button ytba-collapse" data-close title="收缩侧栏" aria-label="收缩侧栏">&gt;</button><button class="ytba-icon-button ytba-dismiss" data-dismiss title="关闭助手" aria-label="关闭助手">×</button></div><div class="ytba-status"><div class="ytba-status-row"><div class="ytba-pulse" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i></div><span data-status>准备中</span></div><div class="ytba-progress"><div style="width:0%"></div></div><div class="ytba-task-actions"><button data-task="pause">暂停</button><button data-task="cancel">取消</button></div></div><div class="ytba-primary-tools"><button class="ytba-control" data-control="visible">隐藏字幕</button><label class="ytba-control ytba-language">语言 <select data-control="language"><option value="bilingual">原文 + 中文</option><option value="zh">仅中文</option><option value="source">仅原文</option></select></label><button class="ytba-control" data-layout-mode>布局：覆盖</button><details class="ytba-tools-menu"><summary title="更多工具">•••</summary><div class="ytba-tools-popover"><button class="ytba-control" data-side>移到左侧</button><button class="ytba-control" data-control="smaller">字号 −</button><button class="ytba-control" data-control="larger">字号 ＋</button><button class="ytba-control" data-control="up">字幕上移</button><button class="ytba-control" data-control="down">字幕下移</button><button class="ytba-control" data-control="background">字幕背景</button><button class="ytba-control" data-export disabled>导出 Markdown</button><button class="ytba-control" data-control="reset">恢复显示默认值</button></div></details></div><div class="ytba-tabs"><button class="active" data-tab="transcript"><span>字幕</span><i class="ytba-tab-indicator"></i></button><button data-tab="summary"><span>摘要</span><i class="ytba-tab-indicator"></i></button></div><div class="ytba-body"></div>`;
    // Moon Begin: collapse into a persistent edge handle instead of deleting the panel.
    root.querySelector("[data-close]").onclick = event => { event.stopPropagation(); setPanelCollapsed(true); };
    root.querySelector("[data-dismiss]").onclick = event => { event.stopPropagation(); closeAssistant(); };
    root.querySelector("[data-side]").onclick = () => updatePanelPrefs({side:panelPrefs.side==="right"?"left":"right"});
    root.querySelector("[data-layout-mode]").onclick = () => updatePanelPrefs({layoutMode:panelPrefs.layoutMode==="overlay"?"push":"overlay"});
    root.querySelector('[data-task="pause"]').onclick = toggleJobPause;
    root.querySelector('[data-task="cancel"]').onclick = cancelCurrentJob;
    bindPanelResize(root);
    root.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => renderTab(button.dataset.tab));
    root.querySelector("[data-retry]").onclick = retryFromCheckpoint;
    const edgeHandle=root.querySelector("[data-expand]");
    bindLauncherDrag(edgeHandle,()=>setPanelCollapsed(false));
    bindDismissContextMenu(edgeHandle);
    bindSubtitleControls(root);
    root.querySelector("[data-export]").onclick = () => safeSendMessage({type:"download-markdown", content:buildMarkdown(), filename:safeName(result.title)});
    document.body.appendChild(root);
    document.body.classList.add(`ytba-site-${site}`);
    document.body.classList.add("ytba-panel-open");
    applyPanelPrefs();
    setPanelCollapsed(panelCollapsed);
    refreshTabStates();
    return root;
  }

  function setTabComplete(tab, complete) {
    const changed=(tab==="transcript"?transcriptComplete:summaryComplete)!==complete;
    if(tab==="transcript")transcriptComplete=complete;else summaryComplete=complete;
    const button=document.querySelector(`#ytba-root [data-tab="${tab}"]`);
    button?.classList.toggle("completed",complete);
    button?.classList.toggle("just-completed",complete&&changed);
    if(complete&&changed)setTimeout(()=>button?.classList.remove("just-completed"),1800);
    refreshTabStates();
  }

  function refreshTabStates() {
    const root=document.querySelector("#ytba-root");if(!root)return;
    const transcript=root.querySelector('[data-tab="transcript"]');
    const summary=root.querySelector('[data-tab="summary"]');
    transcript?.classList.toggle("completed",transcriptComplete);
    transcript?.classList.toggle("processing",Boolean(job&&["queued","running"].includes(job.state)&&!transcriptComplete));
    summary?.classList.toggle("completed",summaryComplete);
    summary?.classList.toggle("processing",job?.summary_state==="running");
    summary?.classList.toggle("failed",job?.summary_state==="failed");
  }

  function setPanelCollapsed(collapsed) {
    panelCollapsed=collapsed;
    const root=document.querySelector("#ytba-root");
    root?.classList.toggle("ytba-collapsed",collapsed);
    document.body.classList.toggle("ytba-panel-collapsed",collapsed);
    updateFullscreenLayout(); // Moon Add: push mode must restore/reapply immediately.
    // Moon Add: keep YouTube's player layout in lockstep with the CSS transition.
    cancelAnimationFrame(layoutAnimationFrame);
    const started=performance.now();
    const refreshLayout=now=>{
      window.dispatchEvent(new Event("resize"));
      updateResponsiveSubtitleScale();
      if(now-started<380)layoutAnimationFrame=requestAnimationFrame(refreshLayout);
    };
    layoutAnimationFrame=requestAnimationFrame(refreshLayout);
  }

  function updateFullscreenLayout() {
    // Moon Begin: only descendants of the fullscreen element are rendered by Chrome.
    const root=document.querySelector("#ytba-root");
    const player=video();
    const bilibiliFullscreen=site==="bilibili"
      ? (document.body.classList.contains("webscreen-fix")
          ? playerContainer()
          : [...document.querySelectorAll(".bpx-state-fullscreen")].find(element=>element.contains(player)))
      : null;
    const host=document.fullscreenElement || bilibiliFullscreen || null;
    const launcher=document.querySelector("#ytba-launcher");
    document.querySelectorAll(".ytba-fullscreen-host").forEach(element=>{
      if(element!==host)element.classList.remove("ytba-fullscreen-host");
    });
    if(host&&root&&host!==root&&!host.contains(root))host.appendChild(root);
    if(!host&&root&&root.parentElement!==document.body)document.body.appendChild(root);
    if(host&&launcher&&!host.contains(launcher))host.appendChild(launcher);
    if(!host&&launcher&&launcher.parentElement!==document.body)document.body.appendChild(launcher);
    host?.classList.add("ytba-fullscreen-host");
    document.body.classList.toggle("ytba-fullscreen",Boolean(host));
    updateSiteHeaderOffset(Boolean(host));
    // Moon End
  }

  async function closeAssistant() {
    // Moon Begin: stay dismissed until an explicit popup start message reopens the assistant.
    if(assistantDismissed)return;
    assistantDismissed=true;
    const activeJob=job&&["queued","running","paused"].includes(job.state)?job.id:null;
    clearTimeout(pollTimer);
    cancelAnimationFrame(layoutAnimationFrame);
    pollTimer=null;layoutAnimationFrame=0;
    const player=video();
    if(player&&playbackReady)player.removeEventListener("timeupdate",syncSubtitle);
    playerResizeObserver?.disconnect();playerResizeObserver=null;
    document.querySelector("#ytba-prompt")?.remove();
    document.querySelector("#ytba-launcher")?.remove();
    document.querySelector("#ytba-root")?.remove();
    document.querySelector("#ytba-overlay")?.remove();
    document.querySelectorAll(".ytba-fullscreen-host").forEach(element=>element.classList.remove("ytba-fullscreen-host"));
    document.body.classList.remove("ytba-panel-open","ytba-panel-collapsed","ytba-panel-resizing","ytba-fullscreen");
    panelCollapsed=false;playbackReady=false;overlay=null;job=null;result=null;
    window.dispatchEvent(new Event("resize"));
    try{if(activeJob)await api(`/jobs/${activeJob}/cancel`,{method:"POST"});}catch(error){console.warn("[YTBA] close cancel failed:",error);}
    safeSendMessage({type:"release-service"}).catch(()=>{});
    // Moon End
  }

  function updateSiteHeaderOffset(fullscreen=false) {
    // Moon Begin: keep the Bilibili account/navigation bar unobstructed in page mode.
    if(site!=="bilibili")return;
    if(fullscreen){document.body.style.setProperty("--ytba-site-header-offset","0px");return;}
    const selectors=[
      "#bili-header-container", "header.bili-header", ".mini-header",
      ".international-header",
    ];
    // Moon Modified: use the first actual top-level header. Taking the maximum
    // bottom of nested menus can leave an extra blank strip below the navbar.
    const header=selectors.map(selector=>document.querySelector(selector)).find(element=>{
      if(!element)return false;
      const rect=element.getBoundingClientRect();
      return rect.width>0&&rect.height>0&&rect.bottom>0&&rect.top<24;
    });
    const rect=header?.getBoundingClientRect();
    const offset=Math.round(rect ? Math.min(96,Math.max(48,rect.bottom)) : 64);
    document.body.style.setProperty("--ytba-site-header-offset",`${offset}px`);
    // Moon End
  }

  function safeName(name) { return name.replace(/[\\/:*?"<>|]/g, "_").slice(0, 100); }

  function bindSubtitleControls(root) {
    // Moon Begin: playback-only subtitle display controls.
    root.querySelector('[data-control="visible"]').onclick=()=>updateSubtitlePrefs({visible:!subtitlePrefs.visible});
    root.querySelector('[data-control="language"]').onchange=event=>updateSubtitlePrefs({language:event.target.value});
    root.querySelector('[data-control="smaller"]').onclick=()=>updateSubtitlePrefs({fontScale:Math.max(.65,subtitlePrefs.fontScale-.1)});
    root.querySelector('[data-control="larger"]').onclick=()=>updateSubtitlePrefs({fontScale:Math.min(1.8,subtitlePrefs.fontScale+.1)});
    root.querySelector('[data-control="up"]').onclick=()=>updateSubtitlePrefs({bottom:Math.min(40,subtitlePrefs.bottom+3)});
    root.querySelector('[data-control="down"]').onclick=()=>updateSubtitlePrefs({bottom:Math.max(2,subtitlePrefs.bottom-3)});
    root.querySelector('[data-control="background"]').onclick=()=>updateSubtitlePrefs({background:!subtitlePrefs.background});
    root.querySelector('[data-control="reset"]').onclick=()=>updateSubtitlePrefs({...defaultSubtitlePrefs});
    refreshSubtitleControls();
    // Moon End
  }

  function updateSubtitlePrefs(changes) {
    subtitlePrefs={...subtitlePrefs,...changes};
    chrome.storage.local.set({subtitlePrefs});
    applySubtitlePrefs();
    refreshSubtitleControls();
    syncSubtitle();
  }

  function refreshSubtitleControls() {
    const root=document.querySelector("#ytba-root"); if(!root)return;
    const visible=root.querySelector('[data-control="visible"]');
    visible.textContent=subtitlePrefs.visible?"隐藏字幕":"显示字幕";
    visible.classList.toggle("active",subtitlePrefs.visible);
    root.querySelector('[data-control="language"]').value=subtitlePrefs.language;
    const languageSelect=root.querySelector('[data-control="language"]');
    if(languageSelect.value==="")languageSelect.value=subtitlePrefs.language==="en"?"source":"bilingual";
    languageSelect.querySelector('option[value="bilingual"]').textContent=`${sourceLanguageLabel()} + 中文`;
    languageSelect.querySelector('option[value="source"]').textContent=`仅${sourceLanguageLabel()}`;
    root.querySelector('[data-control="background"]').classList.toggle("active",subtitlePrefs.background);
  }

  function applySubtitlePrefs() {
    if(!overlay)return;
    overlay.style.display=subtitlePrefs.visible?"block":"none";
    overlay.style.bottom=`${subtitlePrefs.bottom}%`;
    overlay.classList.toggle("ytba-overlay-background",subtitlePrefs.background);
    updateResponsiveSubtitleScale();
  }

  function updateResponsiveSubtitleScale() {
    if(!overlay)return;
    const player=playerContainer();
    if(!player)return;
    // Moon Add: 960px player width is the neutral size; clamp for phone-sized
    // windows and ultrawide/fullscreen displays to keep captions comfortable.
    const scale=Math.min(1.65,Math.max(.68,player.getBoundingClientRect().width/960));
    const userScale=subtitlePrefs.fontScale;
    overlay.style.setProperty("--ytba-en-size",`${(21*scale*userScale).toFixed(1)}px`);
    overlay.style.setProperty("--ytba-zh-size",`${(24*scale*userScale).toFixed(1)}px`);
  }

  function buildMarkdown() {
    // Moon Add: export remains available after the temporary local service exits.
    const lines=[`# ${result.title}`,"",`来源：${location.href}`,"","## 摘要","",result.summary,"","## 关键点",""];
    lines.push(...result.key_points.map(point=>`- ${point}`),"",`## ${sourceLanguageLabel()}与中文字幕`,"");
    result.segments.forEach(item=>{
      lines.push(`### ${formatTime(item.start)}`,"",item.en,"");
      if(result.source_language!=="zh")lines.push(item.zh,"");
    });
    return lines.join("\n");
  }

  // Moon Begin: switch edges and resize without detaching or rebuilding the panel.
  function clampPanelWidth(width) {
    return Math.round(Math.min(680, Math.max(280, Math.min(width, window.innerWidth - 80))));
  }

  function applyPanelPrefs() {
    panelPrefs.side=panelPrefs.side==="left"?"left":"right";
    panelPrefs.layoutMode=(panelPrefs.layoutMode||panelPrefs.fullscreenMode)==="push"?"push":"overlay";
    panelPrefs.opacity=Math.min(1,Math.max(.72,Number(panelPrefs.opacity)||defaultPanelPrefs.opacity));
    panelPrefs.width=clampPanelWidth(Number(panelPrefs.width)||defaultPanelPrefs.width);
    document.body.style.setProperty("--ytba-panel-width",`${panelPrefs.width}px`);
    document.body.style.setProperty("--ytba-panel-opacity",panelPrefs.opacity);
    document.body.classList.toggle("ytba-panel-left",panelPrefs.side==="left");
    document.body.classList.toggle("ytba-panel-right",panelPrefs.side==="right");
    document.body.classList.toggle("ytba-layout-push",panelPrefs.layoutMode==="push");
    const root=document.querySelector("#ytba-root");
    if(!root)return;
    const sideButton=root.querySelector("[data-side]");
    sideButton.textContent=panelPrefs.side==="right"?"移到左侧":"移到右侧";
    sideButton.title=`将侧栏移到${panelPrefs.side==="right"?"左":"右"}侧`;
    const layoutButton=root.querySelector("[data-layout-mode]");
    layoutButton.textContent=`布局：${panelPrefs.layoutMode==="push"?"挤压":"覆盖"}`;
    layoutButton.classList.toggle("active",panelPrefs.layoutMode==="push");
    root.querySelector("[data-close]").textContent=panelPrefs.side==="right"?">":"<";
  }

  function updatePanelPrefs(changes,{save=true}={}) {
    panelPrefs={...panelPrefs,...changes};
    applyPanelPrefs();
    if(save)chrome.storage.local.set({panelPrefs});
    window.dispatchEvent(new Event("resize"));
    updateResponsiveSubtitleScale();
    updateFullscreenLayout();
  }

  function bindPanelResize(root) {
    const handle=root.querySelector("[data-resize]");
    handle.onpointerdown=event=>{
      if(panelCollapsed||event.button!==0)return;
      event.preventDefault();
      handle.setPointerCapture(event.pointerId);
      document.body.classList.add("ytba-panel-resizing");
      const resize=moveEvent=>{
        const rawWidth=panelPrefs.side==="left"?moveEvent.clientX:window.innerWidth-moveEvent.clientX;
        updatePanelPrefs({width:clampPanelWidth(rawWidth)},{save:false});
      };
      const finish=()=>{
        handle.onpointermove=null; handle.onpointerup=null; handle.onpointercancel=null;
        document.body.classList.remove("ytba-panel-resizing");
        chrome.storage.local.set({panelPrefs});
      };
      handle.onpointermove=resize; handle.onpointerup=finish; handle.onpointercancel=finish;
    };
  }
  // Moon End

  function renderSummaryMarkdown(markdown) {
    // Moon Add: render the constrained summary Markdown without injecting model HTML.
    return markdown.split("\n").map(line=>{
      const safe=escapeHtml(line);
      if(/^##\s+/.test(line))return `<h3 class="ytba-stream-section">${safe.replace(/^##\s+/,"")}</h3>`;
      if(/^[-*]\s+/.test(line))return `<div class="ytba-stream-point"><span>◆</span>${safe.replace(/^[-*]\s+/,"")}</div>`;
      return line.trim()?`<p>${safe}</p>`:'<div class="ytba-stream-gap"></div>';
    }).join("");
  }

  function updateStatus(stage, progress, error) {
    if(assistantDismissed)return;
    const root = ensurePanel();
    root.querySelector("[data-status]").textContent = error ? `${stage}: ${error}` : stage;
    const bar = root.querySelector(".ytba-progress > div");
    const isSummarizing = stage.includes("生成摘要");
    if (isSummarizing) {
      bar.style.width = "100%";
      bar.classList.add("ytba-progress-indeterminate");
    } else {
      bar.classList.remove("ytba-progress-indeterminate");
      bar.style.width = `${progress || 0}%`;
    }
    const spinner = root.querySelector(".ytba-pulse");
    const done = error || progress >= 100;
    if (spinner) spinner.style.display = done ? "none" : "inline-block";
  }

  // Moon Begin: compact task controls share the checkpoint-aware service lifecycle.
  function refreshTaskControls() {
    const root=document.querySelector("#ytba-root");if(!root)return;
    const pause=root.querySelector('[data-task="pause"]');
    const cancel=root.querySelector('[data-task="cancel"]');
    const active=Boolean(job&&["queued","running","paused"].includes(job.state));
    pause.hidden=!active;cancel.hidden=!active;
    pause.textContent=job?.state==="paused"?"继续":"暂停";
    pause.classList.toggle("active",job?.state==="paused");
  }

  async function toggleJobPause(){
    if(!job)return;
    const action=job.state==="paused"?"resume":"pause";
    try{job=await api(`/jobs/${job.id}/${action}`,{method:"POST"});refreshTaskControls();updateStatus(job.stage,job.progress);if(action==="resume")poll();}
    catch(error){updateStatus("任务控制失败",job.progress,error.message);}
  }

  async function cancelCurrentJob(){
    if(!job||!confirm("取消当前任务？已完成的字幕、翻译与摘要进度会保留，可稍后重试。"))return;
    try{job=await api(`/jobs/${job.id}/cancel`,{method:"POST"});clearTimeout(pollTimer);refreshTaskControls();updateStatus(job.stage,job.progress);safeSendMessage({type:"release-service"});}
    catch(error){updateStatus("取消失败",job.progress,error.message);}
  }
  // Moon End

  async function start() {
    // Moon Add: only an explicit start action may reopen a dismissed assistant.
    assistantDismissed=false;
    const player = video();
    if (player) { player.pause(); player.currentTime = 0; }
    ensurePanel();
    try {
      updateStatus("正在启动本机服务", 2);
      await ensureService();
      if(assistantDismissed){safeSendMessage({type:"release-service"}).catch(()=>{});return;}
      const createdJob = await api("/jobs", {method:"POST", body:JSON.stringify({url:location.href})});
      if(assistantDismissed){api(`/jobs/${createdJob.id}/cancel`,{method:"POST"}).catch(()=>{});safeSendMessage({type:"release-service"}).catch(()=>{});return;}
      job=createdJob;
      poll();
    } catch (error) { safeSendMessage({type:"release-service"}); updateStatus("无法启动", 0, error.message); }
  }

  async function retryFromCheckpoint() {
    // Moon Add: terminate a stale native session, then create a job that resumes its checkpoint.
    clearTimeout(pollTimer);
    const button=document.querySelector("#ytba-root [data-retry]");
    if(button)button.disabled=true;
    updateStatus("正在读取上次进度…",2);
    try {
      await safeSendMessage({type:"release-service"});
      await new Promise(resolve=>setTimeout(resolve,350));
      if(assistantDismissed)return;
      job=null;
      renderedTranslationCount=-1;
      renderedSummary="";
      summaryAutoOpened=false;
      transcriptComplete=false;
      summaryComplete=false;
      await ensureService();
      if(assistantDismissed){safeSendMessage({type:"release-service"}).catch(()=>{});return;}
      const createdJob=await api("/jobs",{method:"POST",body:JSON.stringify({url:location.href})});
      if(assistantDismissed){api(`/jobs/${createdJob.id}/cancel`,{method:"POST"}).catch(()=>{});safeSendMessage({type:"release-service"}).catch(()=>{});return;}
      job=createdJob;
      poll();
    } catch(error) {
      updateStatus("重试失败",0,error.message);
    } finally {
      if(button)button.disabled=false;
    }
  }

  async function poll() {
    try {
      const latestJob = await api(`/jobs/${job.id}`);
      if(assistantDismissed)return;
      job=latestJob;
      refreshTaskControls();
      const liveStage = job.translated_segments > 0 && job.state === "running"
        ? `已翻译 ${job.translated_segments} / ${job.total_segments}，可手动播放`
        : job.stage;
      updateStatus(liveStage, job.progress, job.error);
      setTabComplete("transcript",job.total_segments>0&&job.translated_segments>=job.total_segments);
      setTabComplete("summary",job.summary_state==="completed");
      refreshTabStates();
      // Moon Begin: render each completed translation batch immediately.
      if (job.preview_segments?.length && job.translated_segments !== renderedTranslationCount) {
        renderedTranslationCount = job.translated_segments;
        result = {segments: job.preview_segments, summary: "", key_points: [], source_language:job.source_language, platform:job.platform};
        if (job.translated_segments > 0) {
          setupPlayback();
          updateStatus(`已翻译 ${job.translated_segments} / ${job.total_segments}，可手动播放`, job.progress);
        }
        if (activeTab === "transcript") renderTab("transcript");
      }
      // Moon End
      // Moon Begin: summary streaming is independent from translation batches.
      if (job.summary_partial && job.summary_partial !== renderedSummary) {
        renderedSummary = job.summary_partial;
        if (!summaryAutoOpened) {
          summaryAutoOpened = true;
          activeTab = "summary";
        }
        if (activeTab === "summary") renderTab("summary");
      }
      // Moon End
      if (job.state === "completed") {
        result = job.result;
        setupResult();
        const root = ensurePanel();
        root.classList.add("ytba-completed");
        safeSendMessage({type:"notify", message:`《${result.title}》处理完成，请手动播放。`});
        safeSendMessage({type:"release-service"});
      } else if (["failed","cancelled"].includes(job.state)) {
        safeSendMessage({type:"release-service"});
      } else if (job.state === "paused") {
        pollTimer=setTimeout(poll,1500);
      } else if (job.state !== "failed") {
        const fastPoll = job.stage.startsWith("翻译中文字幕") || job.stage.includes("生成摘要"); pollTimer = setTimeout(poll, fastPoll ? 750 : 1500);
      }
    } catch (error) { updateStatus("连接中断", 0, error.message); }
  }

  function setupResult() {
    setupPlayback();
    const root = ensurePanel();
    root.querySelector("[data-export]").disabled = false;
    renderTab(activeTab);
  }

  function setupPlayback() {
    // Moon Begin: translated batches become playable without waiting for the full job.
    const player = video();
    if (!player) return;
    if (!playbackReady) {
      player.addEventListener("timeupdate", syncSubtitle);
      playbackReady = true;
    }
    // Moon Modified: html5-video-container can have zero height on YouTube.
    // Anchor to the stable player box so bottom positioning stays inside the video.
    const container = playerContainer();
    const existingOverlay = document.querySelector("#ytba-overlay");
    if (existingOverlay && existingOverlay.parentElement !== container) existingOverlay.remove();
    if (container && !document.querySelector("#ytba-overlay")) {
      overlay = document.createElement("div");
      overlay.id = "ytba-overlay";
      container.appendChild(overlay);
    } else {
      overlay = document.querySelector("#ytba-overlay");
    }
    applySubtitlePrefs();
    refreshSubtitleControls();
    updateResponsiveSubtitleScale();
    if(!playerResizeObserver){
      playerResizeObserver=new ResizeObserver(updateResponsiveSubtitleScale);
      playerResizeObserver.observe(container);
    }
    syncSubtitle();
    // Moon End
  }

  function renderTab(tab) {
    if (!result) return;
    activeTab = tab;
    const root = ensurePanel();
    root.querySelectorAll("[data-tab]").forEach(x => x.classList.toggle("active", x.dataset.tab === tab));
    const body = root.querySelector(".ytba-body");
    if (tab === "summary") {
      if (job?.state !== "completed" && renderedSummary) {
        const streaming=job.summary_state === "running";
        body.innerHTML = `<div class="ytba-stream-heading">${streaming?'<span class="ytba-live-dot"></span> AI 正在提炼原文内容':'✓ 摘要已生成，字幕仍在翻译'}</div><div class="ytba-stream-text">${renderSummaryMarkdown(renderedSummary)}${streaming?'<span class="ytba-stream-caret"></span>':''}</div>`;
      } else if (job?.summary_state === "failed" && !result.summary) {
        body.innerHTML = `<div class="ytba-summary-error">摘要生成失败：${escapeHtml(job.summary_error || "未知错误")}<br>字幕翻译结果仍可正常使用。</div>`;
      } else {
        // Moon Modified: cached and completed summaries retain the polished
        // streaming layout instead of falling back to plain headings and lists.
        const completedMarkdown=[
          "## 内容摘要",result.summary,"","## 关键点",
          ...result.key_points.map(point=>`- ${point}`),
        ].join("\n");
        body.innerHTML = `<div class="ytba-stream-heading"><span class="ytba-summary-check">✓</span> AI 内容提炼已完成</div><div class="ytba-stream-text">${renderSummaryMarkdown(completedMarkdown)}</div>`;
      }
      return;
    }
    body.innerHTML = result.segments.map((x,i)=>`<div class="ytba-segment" data-index="${i}"><div class="ytba-time">${formatTime(x.start)}</div><div class="${result.source_language==="zh"?"ytba-zh":"ytba-en"}">${escapeHtml(x.en)}</div>${result.source_language==="zh"?"":`<div class="ytba-zh">${x.zh ? escapeHtml(x.zh) : '<span style="color:#707784">等待翻译…</span>'}</div>`}</div>`).join("");
    body.querySelectorAll(".ytba-segment").forEach(el => el.onclick = () => { const player=video(); player.currentTime=result.segments[Number(el.dataset.index)].start; });
  }

  function syncSubtitle() {
    if (!result || !overlay) return;
    const now = video().currentTime;
    const index = result.segments.findIndex(x => x.start <= now && x.end >= now);
    const item = result.segments[index];
    // Moon Modified: untranslated future segments intentionally render nothing.
    if (!subtitlePrefs.visible || !item?.zh) overlay.innerHTML = "";
    else if (result.source_language === "zh") overlay.innerHTML = `<div class="zh">${escapeHtml(item.zh)}</div>`;
    else if (subtitlePrefs.language === "zh") overlay.innerHTML = `<div class="zh">${escapeHtml(item.zh)}</div>`;
    else if (["source","en"].includes(subtitlePrefs.language)) overlay.innerHTML = `<div class="en">${escapeHtml(item.en)}</div>`;
    else overlay.innerHTML = `<div class="en">${escapeHtml(item.en)}</div><div class="zh">${escapeHtml(item.zh)}</div>`;
    document.querySelectorAll(".ytba-segment.active").forEach(x=>x.classList.remove("active"));
    const active = document.querySelector(`.ytba-segment[data-index="${index}"]`);
    active?.classList.add("active");
    active?.scrollIntoView({block:"nearest"});
  }

  function watchNavigation() {
    if (location.href === lastUrl) return;
    if(lastUrl&&job?.state==="running")safeSendMessage({type:"release-service"}).catch(()=>{});
    lastUrl = location.href;
    const player = video();
    if (player && playbackReady) player.removeEventListener("timeupdate", syncSubtitle);
    playerResizeObserver?.disconnect(); playerResizeObserver=null; cancelAnimationFrame(layoutAnimationFrame); layoutAnimationFrame=0;
    clearTimeout(pollTimer); job = result = null; renderedTranslationCount = -1; renderedSummary = ""; summaryAutoOpened = false; transcriptComplete = false; summaryComplete = false; activeTab = "transcript"; playbackReady = false; overlay = null;
    document.querySelector("#ytba-root")?.remove(); document.querySelector("#ytba-overlay")?.remove(); document.querySelector("#ytba-launcher")?.remove(); document.body.classList.remove("ytba-panel-open","ytba-panel-collapsed","ytba-panel-resizing","ytba-fullscreen","ytba-site-youtube","ytba-site-bilibili"); panelCollapsed=false;
    if (isVideoPage()&&!assistantDismissed) setTimeout(site==="bilibili"?showLauncher:showPrompt, 1800);
  }

  chrome.runtime.onMessage.addListener(message => { if (message.type === "start") start(); if (message.type === "open"&&!assistantDismissed) ensurePanel(); });
  // Moon Add: apply settings-page appearance changes without reloading the video.
  chrome.storage.onChanged.addListener((changes,area)=>{if(area==="local"&&changes.panelPrefs){panelPrefs={...defaultPanelPrefs,...changes.panelPrefs.newValue};panelPrefs.layoutMode=panelPrefs.layoutMode||panelPrefs.fullscreenMode||"overlay";applyPanelPrefs();}});
  document.addEventListener("fullscreenchange",updateFullscreenLayout);
  // Moon Add: Bilibili web-fullscreen only toggles a body class, so react
  // immediately instead of waiting for the navigation polling interval.
  new MutationObserver(updateFullscreenLayout).observe(document.body,{attributes:true,attributeFilter:["class"]});
  updateFullscreenLayout();
  chrome.storage.local.get({subtitlePrefs:defaultSubtitlePrefs,panelPrefs:defaultPanelPrefs,launcherPrefs:defaultLauncherPrefs}).then(data=>{subtitlePrefs={...defaultSubtitlePrefs,...data.subtitlePrefs};panelPrefs={...defaultPanelPrefs,...data.panelPrefs};launcherPrefs={...defaultLauncherPrefs,...data.launcherPrefs};panelPrefs.layoutMode=panelPrefs.layoutMode||panelPrefs.fullscreenMode||"overlay";delete panelPrefs.fullscreenMode;if(subtitlePrefs.language==="en")subtitlePrefs.language="source";applyPanelPrefs();applyLauncherPrefs();applySubtitlePrefs();refreshSubtitleControls();});
  setInterval(()=>{watchNavigation();updateFullscreenLayout();}, 1000);
  watchNavigation();
})();
