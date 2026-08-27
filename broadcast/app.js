(() => {
  const $ = (s, el = document) => el.querySelector(s);

  const SPEAKERS = {
    foreman: { name: "Foreman Vegapunk", role: "THE BENCH", av: "V", img: "assets/avatar-foreman.png" },
    juror_one: { name: "Pythagoras", role: "THE BUILDER", av: "P", img: "assets/avatar-builder.png" },
    juror_two: { name: "Atlas", role: "THE SKEPTIC", av: "A", img: "assets/avatar-skeptic.png" },
    juror_three: { name: "Edison", role: "THE FUTURIST", av: "E", img: "assets/avatar-futurist.png" },
    team: { name: "The Team", role: "PARTICIPANT", av: "T" },
  };

  const state = {
    segments: [],
    loaded: new Set(),
    skipped: [],
    idx: 0,
    lineIdx: 0,
    started: false,
    finished: false,
    paused: false,
    muted: false,
    token: 0,
  };

  /* ── voice engine: one Web Audio context, unlocked by the play
        gesture, so every line is guaranteed audible ─────────── */

  const voice = {
    ctx: null,
    gain: null,
    source: null,
    buffer: null,
    startedAt: 0,
    offset: 0,
    paused: false,
    onEnded: null,

    async unlock() {
      if (!this.ctx) {
        const AC = window.AudioContext || window.webkitAudioContext;
        this.ctx = new AC();
        this.gain = this.ctx.createGain();
        this.gain.connect(this.ctx.destination);
      }
      if (this.ctx.state === "suspended") await this.ctx.resume();
    },

    async load(src) {
      const res = await fetch(src);
      if (!res.ok) throw new Error("fetch " + res.status);
      const arr = await res.arrayBuffer();
      this.buffer = await this.ctx.decodeAudioData(arr);
      this.offset = 0;
      this.paused = false;
    },

    play() {
      if (!this.buffer || !this.ctx) return;
      this.source = this.ctx.createBufferSource();
      this.source.buffer = this.buffer;
      this.source.connect(this.gain);
      this.source.onended = () => {
        if (this.paused) return;
        this.source = null;
        if (this.onEnded) this.onEnded();
      };
      this.startedAt = this.ctx.currentTime - this.offset;
      this.source.start(0, this.offset);
    },

    pause() {
      if (!this.source) return;
      this.paused = true;
      this.offset = this.ctx.currentTime - this.startedAt;
      this.source.onended = null;
      try { this.source.stop(); } catch (e) {}
      this.source = null;
    },

    resume() {
      if (!this.paused) return;
      this.paused = false;
      this.play();
    },

    stop() {
      if (this.source) {
        this.source.onended = null;
        try { this.source.stop(); } catch (e) {}
        this.source = null;
      }
      this.buffer = null;
      this.offset = 0;
      this.paused = false;
      this.onEnded = null;
    },

    setMuted(m) {
      if (this.gain) this.gain.gain.value = m ? 0 : 1;
    },

    get playing() {
      return !!this.source && !this.paused;
    },
  };

  /* ── primitives ──────────────────────────── */

  const sleep = (ms) => new Promise((resolve) => {
    const tok = state.token;
    let remaining = ms;
    let last = performance.now();
    const tick = () => {
      if (tok !== state.token) return resolve(false);
      const now = performance.now();
      if (!state.paused) remaining -= now - last;
      last = now;
      if (remaining <= 0) return resolve(true);
      setTimeout(tick, 40);
    };
    tick();
  });

  const playLine = async (src) => {
    setVoice("LOADING");
    try {
      await voice.load(src);
    } catch (err) {
      console.error("voice load failed:", src, err);
      setVoice("ERROR");
      return;
    }
    setVoice("PLAYING");
    await new Promise((resolve) => {
      voice.onEnded = () => { voice.onEnded = null; resolve(); };
      voice.play();
    });
    setVoice("READY");
  };

  const stopVoice = () => { voice.stop(); setVoice("READY"); };

  const fmtTime = (ts) => {
    if (!ts) return "";
    const m = ts.match(/T(\d{2}:\d{2})/);
    return m ? m[1] : "";
  };

  const seg = () => state.segments[state.idx];

  /* ── rendering ───────────────────────────── */

  const chatCol = () => $("#chat-col");
  const chatScroll = () => $("#chat-scroll");
  const scrollDown = () => {
    const sc = chatScroll();
    sc.scrollTo({ top: sc.scrollHeight, behavior: "smooth" });
  };

  const setProgress = (text) => { $("#bar-progress").textContent = text; };
  const setVoice = (text) => { $("#bar-voice").textContent = "VOICE / " + text; };

  const bigplayHtml = () => `
    <div class="bigplay" id="bigplay">
      <button class="bigplay-btn mono" id="btn-bigplay">▶&nbsp;&nbsp;PLAY JUDGING SESSION</button>
      <p class="bigplay-note mono">${seg().lines.length} MESSAGES / VOICED REPLAY / SCORES SEALED</p>
    </div>`;

  const header = () => {
    const s = seg();
    $("#head-case").textContent = `TEAM ${s.team_number} — ${(s.team_name || "").toUpperCase()}`;
    $("#head-team").textContent = s.case_id.replace("case_", "CASE ").toUpperCase();
    $("#head-oneliner").textContent = s.one_liner || "";
  };

  const resetChat = () => {
    chatCol().innerHTML = bigplayHtml();
    $("#btn-bigplay").addEventListener("click", play);
    state.lineIdx = 0;
    state.started = false;
    state.finished = false;
    setProgress("READY");
    $("#btn-play").textContent = "▶ PLAY";
  };

  const speakerOf = (line) => {
    const s = seg();
    if (line.speaker === "team") {
      return { name: s.team_name, role: `TEAM ${s.team_number}`, av: (s.team_name || "T")[0].toUpperCase() };
    }
    return SPEAKERS[line.speaker] || SPEAKERS.team;
  };

  const avHtml = (sp) => sp.img
    ? `<div class="msg-av msg-av-img"><img src="${sp.img}" alt=""></div>`
    : `<div class="msg-av">${sp.av}</div>`;

  const appendTyping = (line) => {
    const sp = speakerOf(line);
    const el = document.createElement("div");
    el.className = "msg msg-typing";
    el.innerHTML = `
      ${avHtml(sp)}
      <div class="msg-body">
        <span class="typing-label">${sp.name.toUpperCase()} IS TYPING<span class="tdots"><span>.</span><span>.</span><span>.</span></span></span>
      </div>`;
    chatCol().appendChild(el);
    requestAnimationFrame(() => el.classList.add("is-in"));
    scrollDown();
  };

  const removeTyping = () => {
    const t = chatCol().querySelector(".msg-typing");
    if (t) t.remove();
  };

  const appendMessage = (line) => {
    const sp = speakerOf(line);
    const el = document.createElement("div");
    el.className = "msg";
    el.dataset.speaker = line.speaker;
    el.dataset.kind = line.kind;

    if (line.kind === "sealed") {
      el.classList.add("msg-sealed");
      el.innerHTML = `
        ${avHtml(sp)}
        <div class="msg-body">
          <div class="msg-head">
            <span class="msg-name">${sp.name}</span>
            <span class="msg-role">VERDICT</span>
            <span class="msg-time">${fmtTime(line.ts)}</span>
          </div>
          <div class="sealed-card">
            <div class="sealed-bars"><i></i><i></i><i></i></div>
            <p class="sealed-label">VERDICT / SEALED</p>
            <p class="sealed-note">Scores stay sealed until the top-six announcement at 16:45.</p>
          </div>
        </div>`;
    } else {
      el.innerHTML = `
        ${avHtml(sp)}
        <div class="msg-body">
          <div class="msg-head">
            <span class="msg-name">${sp.name}</span>
            <span class="msg-role">${sp.role}</span>
            <span class="msg-time">${fmtTime(line.ts)}</span>
          </div>
          <div class="msg-text">${line.text}</div>
        </div>`;
    }

    chatCol().querySelectorAll(".msg.is-current").forEach((m) => m.classList.remove("is-current"));
    chatCol().appendChild(el);
    requestAnimationFrame(() => el.classList.add("is-in"));
    el.classList.add("is-current");
    scrollDown();
  };

  const appendEndcard = () => {
    const el = document.createElement("div");
    el.className = "endcard";
    const hasNext = state.idx + 1 < state.segments.length;
    el.innerHTML = `
      <p class="endcard-line mono">CASE SEALED / VERDICT ON RECORD / SCORES REVEALED 16:45</p>
      ${hasNext ? '<div class="endcard-next"><button id="btn-next">NEXT CASE →</button></div>' : ""}`;
    chatCol().appendChild(el);
    if (hasNext) $("#btn-next").addEventListener("click", () => { state.token += 1; loadCase(state.idx + 1); play(); });
    scrollDown();
  };

  /* ── live queue: pick up new cases as the watcher stages them ── */

  const refreshPlaylist = async () => {
    const bust = "?b=" + Date.now();
    try {
      const pl = await (await fetch("segments/playlist.json" + bust)).json();
      if (pl.segments.length > state.segments.length + state.skipped.length) {
        let added = false;
        for (const f of pl.segments) {
          if (state.loaded.has(f)) continue;
          try {
            const r = await fetch("segments/" + f + bust);
            if (!r.ok) throw new Error("HTTP " + r.status);
            state.segments.push(await r.json());
            state.loaded.add(f);
            added = true;
          } catch (err) {
            console.error("skipping broken segment:", f, err);
            state.skipped.push(f);
          }
        }
        return added;
      }
    } catch (err) { /* keep waiting */ }
    return false;
  };

  const showWaiting = () => {
    const el = document.createElement("div");
    el.className = "waitcard mono";
    el.id = "waitcard";
    el.innerHTML = `
      <p class="wait-line">STANDBY — NEXT CASE IN PREPARATION<span class="pulse"></span></p>
      <p class="wait-sub">THE BENCH RECONVENES AUTOMATICALLY WHEN A VERDICT LANDS</p>`;
    chatCol().appendChild(el);
    scrollDown();
  };

  const standby = async () => {
    const tok = state.token;
    setProgress("STANDBY / WAITING FOR NEXT CASE");
    showWaiting();
    while (tok === state.token) {
      if (!(await sleep(15000))) return;
      if (tok !== state.token) return;
      if (await refreshPlaylist()) {
        if (tok !== state.token) return;
        loadCase(state.idx + 1);
        play();
        return;
      }
    }
  };

  const autoAdvance = async () => {
    const tok = state.token;
    if (!(await sleep(5000))) return;
    if (tok !== state.token) return;

    if (state.idx + 1 < state.segments.length) {
      loadCase(state.idx + 1);
      play();
      return;
    }

    standby();
  };

  /* ── demo video stage ────────────────────── */

  const playDemo = () => new Promise((resolve) => {
    const s = seg();
    const src = s.demo_video;
    setProgress("DEMO VIDEO");

    const stage = document.createElement("div");
    stage.className = "video-stage";

    const finish = () => {
      if (stage.parentNode) stage.remove();
      resolve();
    };

    const isYouTube = /youtube\.com|youtu\.be/.test(src);

    if (isYouTube) {
      const id = (src.match(/(?:v=|youtu\.be\/|embed\/)([\w-]{11})/) || [])[1] || "";
      stage.innerHTML = `
        <p class="video-k mono">DEMO VIDEO / ${s.team_name.toUpperCase()}</p>
        <div class="video-frame">
          <div id="yt-player"></div>
        </div>
        <button class="video-skip mono" id="btn-skipvideo">SKIP VIDEO →</button>`;
      chatCol().appendChild(stage);
      $("#btn-skipvideo").addEventListener("click", finish);
      stage.scrollIntoView({ behavior: "smooth", block: "start" });

      const start = () => {
        const player = new window.YT.Player("yt-player", {
          videoId: id,
          width: "100%",
          height: "100%",
          playerVars: { autoplay: 1, rel: 0, modestbranding: 1 },
          events: { onStateChange: (e) => { if (e.data === window.YT.PlayerState.ENDED) finish(); } },
        });
        stage._player = player;
      };
      if (window.YT && window.YT.Player) start();
      else {
        const tag = document.createElement("script");
        tag.src = "https://www.youtube.com/iframe_api";
        tag.onload = () => setTimeout(start, 100);
        document.head.appendChild(tag);
      }
    } else {
      stage.innerHTML = `
        <p class="video-k mono">DEMO VIDEO / ${s.team_name.toUpperCase()}</p>
        <div class="video-frame">
          <video id="demo-video" src="${src}" autoplay playsinline></video>
        </div>
        <button class="video-skip mono" id="btn-skipvideo">SKIP VIDEO →</button>`;
      chatCol().appendChild(stage);
      const v = $("#demo-video");
      v.addEventListener("ended", finish);
      v.addEventListener("error", finish);
      $("#btn-skipvideo").addEventListener("click", finish);
      stage.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  });

  /* ── playback ────────────────────────────── */

  const runLoop = async () => {
    const tok = state.token;
    const s = seg();

    while (state.lineIdx < s.lines.length) {
      if (tok !== state.token) return;
      const line = s.lines[state.lineIdx];

      if (line.kind !== "sealed") {
        appendTyping(line);
        const typingMs = Math.min(900 + line.text.length * 5, 2400);
        if (!(await sleep(typingMs))) return;
        removeTyping();
      }

      appendMessage(line);
      state.lineIdx += 1;
      setProgress(`MSG ${state.lineIdx} / ${s.lines.length}`);

      if (line.audio) {
        await playLine(line.audio);
        if (tok !== state.token) return;
      } else if (line.kind === "sealed") {
        if (!(await sleep(3200))) return;
      }
      if (!(await sleep(400))) return;
    }

    if (tok !== state.token) return;
    state.finished = true;
    setProgress("COMPLETE / SEALED");
    $("#btn-play").textContent = "⟲ REPLAY";
    appendEndcard();
    autoAdvance();
  };

  const play = async () => {
    if (state.finished) { restart(); return; }
    if (state.paused) { togglePause(); return; }
    if (state.started) return;
    state.started = true;

    await voice.unlock();
    voice.setMuted(state.muted);

    const bp = $("#bigplay");
    if (bp) bp.classList.add("is-gone");
    $("#btn-play").textContent = "❚❚ PAUSE";

    const tok = state.token;
    if (seg().demo_video) {
      await playDemo();
      if (tok !== state.token) return;
    }
    setProgress("PLAYING");
    runLoop();
  };

  const togglePause = () => {
    if (!state.started || state.finished) return;
    state.paused = !state.paused;
    document.body.classList.toggle("paused", state.paused);
    $("#btn-play").textContent = state.paused ? "▶ RESUME" : "❚❚ PAUSE";
    setProgress(state.paused ? `PAUSED / MSG ${state.lineIdx} / ${seg().lines.length}` : "PLAYING");
    if (state.paused) voice.pause();
    else voice.resume();
  };

  const restart = () => {
    state.token += 1;
    stopVoice();
    state.paused = false;
    document.body.classList.remove("paused");
    resetChat();
    play();
  };

  const skipCase = () => {
    state.token += 1;
    stopVoice();
    state.paused = false;
    document.body.classList.remove("paused");
    if (state.idx + 1 < state.segments.length) {
      loadCase(state.idx + 1);
      play();
      return;
    }
    chatCol().innerHTML = "";
    chatScroll().scrollTo({ top: 0 });
    standby();
  };

  const loadCase = (i) => {
    state.token += 1;
    stopVoice();
    state.idx = i;
    state.paused = false;
    document.body.classList.remove("paused");
    header();
    resetChat();
    chatScroll().scrollTo({ top: 0 });
  };

  const toggleMute = () => {
    state.muted = !state.muted;
    voice.setMuted(state.muted);
    $("#btn-mute").textContent = state.muted ? "UNMUTE" : "MUTE";
  };

  const toggleFullscreen = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen().catch(() => {});
  };

  /* ── boot ────────────────────────────────── */

  const tickClock = () => {
    const d = new Date();
    $("#bar-clock").textContent =
      String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
  };

  const boot = async () => {
    const bust = "?b=" + Date.now();
    try {
      const pl = await (await fetch("segments/playlist.json" + bust)).json();
      for (const f of pl.segments) {
        try {
          const r = await fetch("segments/" + f + bust);
          if (!r.ok) throw new Error("HTTP " + r.status);
          state.segments.push(await r.json());
          state.loaded.add(f);
        } catch (err) {
          console.error("skipping broken segment:", f, err);
          state.skipped.push(f);
        }
      }
    } catch (err) {
      console.error("failed to load playlist", err);
      setProgress("ERROR / PLAYLIST NOT FOUND");
      return;
    }
    if (!state.segments.length) {
      setProgress("ERROR / NO PLAYABLE CASES");
      return;
    }

    loadCase(0);
    tickClock();
    setInterval(tickClock, 10000);

    $("#btn-play").addEventListener("click", play);
    $("#btn-restart").addEventListener("click", restart);
    $("#btn-skipcase").addEventListener("click", skipCase);
    $("#btn-mute").addEventListener("click", toggleMute);
    $("#btn-full").addEventListener("click", toggleFullscreen);

    document.addEventListener("keydown", (e) => {
      if (e.code === "Space") { e.preventDefault(); state.started && !state.finished ? togglePause() : play(); }
      else if (e.key === "r" || e.key === "R") restart();
      else if (e.key === "n" || e.key === "N") skipCase();
      else if (e.key === "m" || e.key === "M") toggleMute();
      else if (e.key === "f" || e.key === "F") toggleFullscreen();
    });

    if (location.search.includes("autostart")) play();
  };

  boot();
})();
