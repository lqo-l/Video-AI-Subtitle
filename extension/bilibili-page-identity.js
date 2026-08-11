// Moon Begin
// Runs in Bilibili's page world so the isolated extension script never guesses a
// CID from URL p. The newest player API request is the most reliable signal after
// SPA navigation; hydration data is only a conservative fallback.
(() => {
  const eventName = "ytba:bilibili-playback-identity";
  const requestName = "ytba:get-bilibili-playback-identity";

  function positiveCid(value) {
    const cid = Number(value);
    return Number.isSafeInteger(cid) && cid > 0 ? cid : null;
  }

  function resourceCid() {
    try {
      const entries = performance.getEntriesByType("resource");
      for (let index = entries.length - 1; index >= 0; index -= 1) {
        const name = entries[index]?.name;
        if (!name || !/\/x\/player\/(?:wbi\/)?v2(?:\?|$)/.test(name)) continue;
        const cid = positiveCid(new URL(name).searchParams.get("cid"));
        if (cid) return cid;
      }
    } catch (_) { /* A missing Performance API simply uses the fallback below. */ }
    return null;
  }

  function stateCid() {
    try {
      const liveCid = positiveCid(window.player?.getVideoMessage?.()?.cid);
      if (liveCid) return liveCid;
    } catch (_) { /* Player implementations differ; retain data-only fallbacks. */ }
    const candidates = [
      window.__playinfo__, window.__PLAYINFO__, window.__INITIAL_STATE__?.videoData,
      window.__INITIAL_STATE__?.epInfo, window.__PLAYER_CONFIG__, window.__NEXT_DATA__
    ];
    for (const candidate of candidates) {
      const cid = positiveCid(candidate?.cid || candidate?.data?.cid || candidate?.videoInfo?.cid);
      if (cid) return cid;
    }
    return null;
  }

  function currentIdentity() {
    const bvid = location.pathname.match(/\/(BV[0-9A-Za-z]+)/i)?.[1] || "";
    const cid = stateCid() || resourceCid();
    return /^BV[0-9A-Za-z]+$/i.test(bvid) && cid ? { bvid, cid } : null;
  }

  window.addEventListener(requestName, () => {
    window.dispatchEvent(new CustomEvent(eventName, { detail: currentIdentity() }));
  });
})();
// Moon End
