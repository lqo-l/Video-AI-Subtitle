(() => {
  const API = "http://127.0.0.1:8765";
  let job = null;
  let result = null;
  let overlay = null;
  let lastUrl = "";
  let pollTimer = null;

  const escapeHtml = (value) => String(value).replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
  const formatTime = seconds => `${String(Math.floor(seconds / 60)).padStart(2, "0")}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

  async function api(path, options = {}) {
    const response = await fetch(`${API}${path}`, {headers: {"Content-Type": "application/json"}, ...options});
    if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail || `本机服务错误 ${response.status}`);
    return response.json();
  }

  function video() { return document.querySelector("video"); }

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
    root.innerHTML = `<div class="ytba-head"><strong>双语字幕助手</strong><button class="ytba-button secondary" data-export disabled>导出 MD</button><button class="ytba-button secondary" data-close>×</button></div><div class="ytba-status"><span data-status>准备中</span><div class="ytba-progress"><div style="width:0%"></div></div></div><div class="ytba-tabs"><button class="active" data-tab="transcript">字幕</button><button data-tab="summary">摘要</button></div><div class="ytba-body"></div>`;
    root.querySelector("[data-close]").onclick = () => { root.remove(); document.body.classList.remove("ytba-panel-open"); };
    root.querySelectorAll("[data-tab]").forEach(button => button.onclick = () => renderTab(button.dataset.tab));
    root.querySelector("[data-export]").onclick = () => chrome.runtime.sendMessage({type:"download-markdown", jobId:job.id, filename:safeName(result.title)});
    document.body.appendChild(root);
    document.body.classList.add("ytba-panel-open");
    return root;
  }

  function safeName(name) { return name.replace(/[\\/:*?"<>|]/g, "_").slice(0, 100); }

  function updateStatus(stage, progress, error) {
    const root = ensurePanel();
    root.querySelector("[data-status]").textContent = error ? `${stage}: ${error}` : stage;
    root.querySelector(".ytba-progress > div").style.width = `${progress || 0}%`;
  }

  async function start() {
    const player = video();
    if (player) { player.pause(); player.currentTime = 0; }
    ensurePanel();
    try {
      job = await api("/jobs", {method:"POST", body:JSON.stringify({url:location.href})});
      poll();
    } catch (error) { updateStatus("无法启动", 0, error.message); }
  }

  async function poll() {
    try {
      job = await api(`/jobs/${job.id}`);
      updateStatus(job.stage, job.progress, job.error);
      if (job.state === "completed") {
        result = job.result;
        setupResult();
        chrome.runtime.sendMessage({type:"notify", message:`《${result.title}》处理完成，请手动播放。`});
      } else if (job.state !== "failed") {
        pollTimer = setTimeout(poll, 1500);
      }
    } catch (error) { updateStatus("连接中断", 0, error.message); }
  }

  function setupResult() {
    const player = video();
    if (player) { player.pause(); player.currentTime = 0; player.addEventListener("timeupdate", syncSubtitle); }
    const container = player?.parentElement;
    if (container && !document.querySelector("#ytba-overlay")) {
      overlay = document.createElement("div"); overlay.id = "ytba-overlay"; container.appendChild(overlay);
    }
    const root = ensurePanel();
    root.querySelector("[data-export]").disabled = false;
    renderTab("transcript");
  }

  function renderTab(tab) {
    if (!result) return;
    const root = ensurePanel();
    root.querySelectorAll("[data-tab]").forEach(x => x.classList.toggle("active", x.dataset.tab === tab));
    const body = root.querySelector(".ytba-body");
    if (tab === "summary") {
      body.innerHTML = `<h3>摘要</h3><div>${escapeHtml(result.summary).replace(/\n/g,"<br>")}</div><h3>关键点</h3><ul>${result.key_points.map(x=>`<li>${escapeHtml(x)}</li>`).join("")}</ul>`;
      return;
    }
    body.innerHTML = result.segments.map((x,i)=>`<div class="ytba-segment" data-index="${i}"><div class="ytba-time">${formatTime(x.start)}</div><div class="ytba-en">${escapeHtml(x.en)}</div><div class="ytba-zh">${escapeHtml(x.zh)}</div></div>`).join("");
    body.querySelectorAll(".ytba-segment").forEach(el => el.onclick = () => { const player=video(); player.currentTime=result.segments[Number(el.dataset.index)].start; });
  }

  function syncSubtitle() {
    if (!result || !overlay) return;
    const now = video().currentTime;
    const index = result.segments.findIndex(x => x.start <= now && x.end >= now);
    const item = result.segments[index];
    overlay.innerHTML = item ? `<div class="en">${escapeHtml(item.en)}</div><div class="zh">${escapeHtml(item.zh)}</div>` : "";
    document.querySelectorAll(".ytba-segment.active").forEach(x=>x.classList.remove("active"));
    const active = document.querySelector(`.ytba-segment[data-index="${index}"]`);
    active?.classList.add("active");
    active?.scrollIntoView({block:"nearest"});
  }

  function watchNavigation() {
    if (location.href === lastUrl) return;
    lastUrl = location.href;
    clearTimeout(pollTimer); job = result = null;
    document.querySelector("#ytba-root")?.remove(); document.querySelector("#ytba-overlay")?.remove(); document.body.classList.remove("ytba-panel-open");
    if (location.pathname === "/watch") setTimeout(showPrompt, 1800);
  }

  chrome.runtime.onMessage.addListener(message => { if (message.type === "start") start(); if (message.type === "open") ensurePanel(); });
  setInterval(watchNavigation, 1000);
  watchNavigation();
})();
