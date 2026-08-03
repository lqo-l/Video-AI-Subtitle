(() => { console.log("[YTBA] content.js v3 loaded - spinner + summary streaming");
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
  let playerResizeObserver = null;
  const defaultSubtitlePrefs = {visible:true, language:"bilingual", fontScale:1, bottom:10, background:false};
  let subtitlePrefs = {...defaultSubtitlePrefs};

  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const formatTime = seconds => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

  async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `本机服务错误 ${response.status}`);
    return response.json();
  }

  function video() { return document.querySelector("video"); }

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
    throw new Error("扩展通信失败，请刷新 YouTube 页面后重试 (Ctrl+Shift+R)");
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
    if (document.querySelector("#ytba-prompt") || document.querySelector("#ytba-root")) return;
    const box = document.createElement("div");
    box.id = "ytba-prompt";
    box.innerHTML = `<strong>生成中英双语字幕？</strong><div style="margin-top:6px;color:#bbc2ce">将先完整处理视频，完成后提醒你手动播放。</div><div class="actions"><button class="ytba-button secondary" data-no>暂不</button><button class="ytba-button" data-yes>开始处理</button></div>`;
    box.querySelector("[data-no]").onclick = () => box.remove();
    box.querySelector("[data-yes]").onclick = () => { box.remove(); start(); };
    document.body.appendChild(box);
  }

  function ensurePanel() {
    let root = document.querySelector("#ytba-root");
    if (root) return root;
    root = document.createElement("aside");
    root.id = "ytba-root";
    root.innerHTML = `<div class="ytba-head"><strong>双语字幕助手</strong><button class="ytba-button secondary" data-export disabled>导出 MD</button><button class="ytba-button secondary" data-close>×</button></div><div class="ytba-status"><span data-status>准备中</span><div class="ytba-progress"><div style="width:0%"></div></div></div><div class="ytba-controls"><button class="ytba-control" data-control="visible">隐藏字幕</button><label class="ytba-control">语言 <select data-control="language"><option value="bilingual">中英双语</option><option value="zh">仅中文</option><option value="en">仅英文</option></select></label><button class="ytba-control" data-control="smaller">字号−</button><button class="ytba-control" data-control="larger">字号＋</button><button class="ytba-control" data-control="up">上移</button><button class="ytba-control" data-control="down">下移</button><button class="ytba-control" data-control="background">字幕背景</button><button class="ytba-control" data-control="reset">恢复默认</button></div><div class="ytba-tabs"><button class="active" data-tab="transcript">字幕</button><button data-tab="summary">摘要</button></div><div class="ytba-body"></div>`;
    // Moon Begin: collapse into a persistent edge handle instead of deleting the panel.
    root.querySelector("[data-close]").onclick = event => { event.stopPropagation(); setPanelCollapsed(true); };
    root.onclick = event => { if (panelCollapsed && !event.target.closest("button,select")) setPanelCollapsed(false); };
    root.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => renderTab(button.dataset.tab));
    bindSubtitleControls(root);
    root.querySelector("[data-export]").onclick = () => safeSendMessage({type:"download-markdown", content:buildMarkdown(), filename:safeName(result.title)});
    document.body.appendChild(root);
    document.body.classList.add("ytba-panel-open");
    setPanelCollapsed(panelCollapsed);
    return root;
  }

  function setPanelCollapsed(collapsed) {
    panelCollapsed=collapsed;
    const root=document.querySelector("#ytba-root");
    root?.classList.toggle("ytba-collapsed",collapsed);
    document.body.classList.toggle("ytba-panel-collapsed",collapsed);
    window.dispatchEvent(new Event("resize"));
  }

  function updateFullscreenLayout() {
    // Moon Add: the normal 64px YouTube header offset must not survive fullscreen.
    document.body.classList.toggle("ytba-fullscreen",Boolean(document.fullscreenElement));
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
    const player=video()?.closest(".html5-video-player");
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
    lines.push(...result.key_points.map(point=>`- ${point}`),"","## 中英字幕","");
    result.segments.forEach(item=>lines.push(`### ${formatTime(item.start)}`,"",item.en,"",item.zh,""));
    return lines.join("\n");
  }

  function updateStatus(stage, progress, error) {
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
    const spinner = root.querySelector(".ytba-spinner");
    const done = error || progress >= 100;
    if (spinner) spinner.style.display = done ? "none" : "inline-block";
  }

  async function start() {
    const player = video();
    if (player) { player.pause(); player.currentTime = 0; }
    ensurePanel();
    try {
      updateStatus("正在启动本机服务", 2);
      await ensureService();
      job = await api("/jobs", {method:"POST", body:JSON.stringify({url:location.href})});
      poll();
    } catch (error) { safeSendMessage({type:"release-service"}); updateStatus("无法启动", 0, error.message); }
  }

  async function poll() {
    try {
      job = await api(`/jobs/${job.id}`);
      const liveStage = job.translated_segments > 0 && job.state === "running"
        ? `已翻译 ${job.translated_segments} / ${job.total_segments}，可手动播放`
        : job.stage;
      updateStatus(liveStage, job.progress, job.error);
      // Moon Begin: render each completed translation batch immediately.
      if (job.preview_segments?.length && job.translated_segments !== renderedTranslationCount) {
        renderedTranslationCount = job.translated_segments;
        result = {segments: job.preview_segments, summary: "", key_points: []};
        if (job.translated_segments > 0) {
          setupPlayback();
          updateStatus(`已翻译 ${job.translated_segments} / ${job.total_segments}，可手动播放`, job.progress);
        }
        if (activeTab === "transcript") renderTab("transcript");
      if (job.summary_partial && activeTab === "summary") renderTab("summary");
      // Auto-switch to summary tab when partial content arrives and user is on transcript
      if (job.summary_partial && !job.result && activeTab === "transcript" && job.translated_segments >= job.total_segments) {
        // Summary is streaming in, show it
      }
      }
      // Moon End
      if (job.state === "completed") {
        result = job.result;
        setupResult();
        const root = ensurePanel();
        root.classList.add("ytba-completed");
        safeSendMessage({type:"notify", message:`《${result.title}》处理完成，请手动播放。`});
        safeSendMessage({type:"release-service"});
      } else if (job.state === "failed") {
        safeSendMessage({type:"release-service"});
      } else if (job.state !== "failed") {
        const fastPoll = job.stage.startsWith("翻译中文字幕") || job.stage.includes("生成摘要"); pollTimer = setTimeout(poll, fastPoll ? 750 : 1500);
      }
    } catch (error) { updateStatus("连接中断", 0, error.message); }
  }

  function setupResult() {
    setupPlayback();
    const root = ensurePanel();
    root.querySelector("[data-export]").disabled = false;
    renderTab("transcript");
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
    const container = player.closest(".html5-video-player") || player.parentElement;
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
      body.innerHTML = `<h3>摘要</h3><div>${escapeHtml(result.summary).replace(/\n/g,"<br>")}</div><h3>关键点</h3><ul>${result.key_points.map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
      return;
    }
    body.innerHTML = result.segments.map((x,i)=>`<div class="ytba-segment" data-index="${i}"><div class="ytba-time">${formatTime(x.start)}</div><div class="ytba-en">${escapeHtml(x.en)}</div><div class="ytba-zh">${x.zh ? escapeHtml(x.zh) : '<span style="color:#707784">等待翻译…</span>'}</div></div>`).join("");
    body.querySelectorAll(".ytba-segment").forEach(el => el.onclick = () => { const player=video(); player.currentTime=result.segments[Number(el.dataset.index)].start; });
  }

  function syncSubtitle() {
    if (!result || !overlay) return;
    const now = video().currentTime;
    const index = result.segments.findIndex(x => x.start <= now && x.end >= now);
    const item = result.segments[index];
    // Moon Modified: untranslated future segments intentionally render nothing.
    if (!subtitlePrefs.visible || !item?.zh) overlay.innerHTML = "";
    else if (subtitlePrefs.language === "zh") overlay.innerHTML = `<div class="zh">${escapeHtml(item.zh)}</div>`;
    else if (subtitlePrefs.language === "en") overlay.innerHTML = `<div class="en">${escapeHtml(item.en)}</div>`;
    else overlay.innerHTML = `<div class="en">${escapeHtml(item.en)}</div><div class="zh">${escapeHtml(item.zh)}</div>`;
    document.querySelectorAll(".ytba-segment.active").forEach(x=>x.classList.remove("active"));
    const active = document.querySelector(`.ytba-segment[data-index="${index}"]`);
    active?.classList.add("active");
    active?.scrollIntoView({block:"nearest"});
  }

  function watchNavigation() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    const player = video();
    if (player && playbackReady) player.removeEventListener("timeupdate", syncSubtitle);
    playerResizeObserver?.disconnect(); playerResizeObserver=null;
    clearTimeout(pollTimer); job = result = null; renderedTranslationCount = -1; activeTab = "transcript"; playbackReady = false; overlay = null;
    document.querySelector("#ytba-root")?.remove(); document.querySelector("#ytba-overlay")?.remove(); document.body.classList.remove("ytba-panel-open","ytba-panel-collapsed","ytba-fullscreen"); panelCollapsed=false;
    if (location.pathname === "/watch") setTimeout(showPrompt, 1800);
  }

  chrome.runtime.onMessage.addListener(message => { if (message.type === "start") start(); if (message.type === "open") ensurePanel(); });
  document.addEventListener("fullscreenchange",updateFullscreenLayout);
  updateFullscreenLayout();
  chrome.storage.local.get({subtitlePrefs:defaultSubtitlePrefs}).then(data=>{subtitlePrefs={...defaultSubtitlePrefs,...data.subtitlePrefs};applySubtitlePrefs();refreshSubtitleControls();});
  setInterval(watchNavigation, 1000);
  watchNavigation();
})();
