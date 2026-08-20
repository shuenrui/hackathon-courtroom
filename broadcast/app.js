const SPEAKERS = {
  juror_one: { name: "The Builder" },
  juror_two: { name: "The Skeptic" },
  juror_three: { name: "The Futurist" },
  team: { name: "The Team" },
};

const KIND_LABEL = {
  review: "Opening Read",
  question: "Cross-Examination",
  answer: "From the Floor",
  followup: "Follow-Up",
};

const scenes = {};
let playlist = null;
let segments = [];
let current = 0;
let seq = 0;
let paused = false;
let muted = false;
let started = false;
let activeAudio = null;
let activeVideo = null;
let pauseTimer = null;
let pauseRemaining = 0;
let pauseResolve = null;
let dockTimeout = null;

const $ = (id) => document.getElementById(id);

function sceneNames() {
  return ["standby", "title", "evidence", "dialogue", "close", "end"];
}

function initScenes() {
  for (const name of sceneNames()) scenes[name] = $("scene-" + name);
}

function showScene(name) {
  for (const other of sceneNames()) {
    const el = scenes[other];
    if (other === name) {
      el.hidden = false;
      requestAnimationFrame(() => el.setAttribute("data-active", "true"));
    } else {
      el.setAttribute("data-active", "false");
      setTimeout(() => {
        if (el.getAttribute("data-active") === "false") el.hidden = true;
      }, 480);
    }
  }
  document.body.dataset.scene = name;
}

function setStatus(text) {
  $("dock-status").textContent = text;
}

function waitMs(ms, mySeq) {
  return new Promise((resolve) => {
    if (mySeq !== seq) return resolve(false);
    let remaining = ms;
    let startedAt = performance.now();
    const finish = (ok) => {
      pauseTimer = null;
      pauseResolve = null;
      resolve(ok);
    };
    pauseResolve = finish;
    pauseTimer = setTimeout(() => finish(mySeq === seq), remaining);
    pauseTimer._pause = () => {
      clearTimeout(pauseTimer);
      pauseRemaining = remaining - (performance.now() - startedAt);
    };
    pauseTimer._resume = () => {
      startedAt = performance.now();
      remaining = Math.max(0, pauseRemaining);
      pauseTimer = setTimeout(() => finish(mySeq === seq), remaining);
    };
  });
}

function setPaused(next) {
  if (paused === next) return;
  paused = next;
  $("btn-pause").textContent = paused ? "Resume" : "Pause";
  if (paused) {
    if (activeAudio) activeAudio.pause();
    if (activeVideo) activeVideo.pause();
    if (pauseTimer && pauseTimer._pause) pauseTimer._pause();
    setStatus("Held");
  } else {
    if (activeAudio) activeAudio.play().catch(() => {});
    if (activeVideo) activeVideo.play().catch(() => {});
    if (pauseTimer && pauseTimer._resume) pauseTimer._resume();
  }
}

function buildWordSpans(el, text) {
  el.innerHTML = "";
  const words = text.split(/\s+/).filter(Boolean);
  for (const w of words) {
    const span = document.createElement("span");
    span.className = "word";
    span.textContent = w;
    el.appendChild(span);
    el.appendChild(document.createTextNode(" "));
  }
  return el.querySelectorAll(".word");
}

function revealWords(el, durationMs, mySeq) {
  return new Promise((resolve) => {
    const words = el.querySelectorAll(".word");
    if (!words.length) return resolve();
    const step = durationMs / words.length;
    let lit = 0;
    let last = performance.now();
    let acc = 0;
    const frame = (now) => {
      if (mySeq !== seq) return resolve();
      if (!paused) acc += now - last;
      last = now;
      while (lit < words.length && acc >= lit * step) {
        words[lit].classList.add("lit");
        lit++;
      }
      if (lit >= words.length) return resolve();
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
  });
}

function estimateMs(text) {
  const words = text.split(/\s+/).filter(Boolean).length;
  return Math.max(2400, words * 400);
}

function setSpeaker(speakerId, kind) {
  const speaker = SPEAKERS[speakerId] || { name: speakerId };
  const plate = $("speaker-plate");
  plate.dataset.judge = speakerId;
  $("speaker-name").textContent = speakerId === "team" && playlist ? (currentTeamName() || speaker.name) : speaker.name;
  $("speaker-role").textContent = KIND_LABEL[kind] || "";
  $("utterance").dataset.judge = speakerId;
  document.querySelectorAll(".bench-mini").forEach((b) => {
    b.classList.toggle("speaking", b.dataset.judge === speakerId);
  });
  const teamBench = document.querySelector('.bench-mini[data-judge="team"] span:last-child');
  if (teamBench) teamBench.textContent = currentTeamName() || "The Team";
}

function currentTeamName() {
  const seg = segments[current];
  return seg ? seg.team_name : "";
}

function clearSpeaker() {
  document.querySelectorAll(".bench-mini").forEach((b) => b.classList.remove("speaking"));
}

async function playLine(line, mySeq) {
  setSpeaker(line.speaker, line.kind);
  const el = $("utterance");
  buildWordSpans(el, line.text);

  let audioOk = false;
  let dur = estimateMs(line.text);
  if (line.audio) {
    activeAudio = new Audio(line.audio);
    activeAudio.muted = muted;
    try {
      await activeAudio.play();
      audioOk = true;
      if (activeAudio.duration && isFinite(activeAudio.duration)) {
        dur = activeAudio.duration * 1000;
      }
    } catch {
      audioOk = false;
    }
  }

  const revealMs = Math.max(1200, dur * 0.94);
  const reveal = revealWords(el, revealMs, mySeq);
  if (audioOk) {
    await new Promise((res) => {
      activeAudio.onended = res;
      activeAudio.onerror = res;
    });
  }
  await reveal;
  activeAudio = null;
  if (mySeq !== seq) return false;
  await waitMs(700, mySeq);
  return mySeq === seq;
}

async function playSegment(index, mySeq) {
  const seg = segments[index];
  if (!seg) return;
  current = index;
  updateRail();

  showScene("title");
  $("title-docket").textContent = `Docket · ${playlist.event || "Build with AI Agents"}`;
  $("title-team").textContent = seg.team_name || `Team ${seg.team_number}`;
  $("title-liner").textContent = seg.one_liner || "";
  const stamp = $("case-stamp");
  stamp.textContent = `CASE ${String(seg.team_number).padStart(2, "0")}`;
  stamp.classList.remove("smash");
  void stamp.offsetWidth;
  stamp.classList.add("smash");
  document.body.classList.add("shake");
  setTimeout(() => document.body.classList.remove("shake"), 450);
  setStatus(`Case ${String(seg.team_number).padStart(2, "0")} — opening`);
  if (!(await waitMs(3600, mySeq))) return;

  if (seg.demo_video) {
    showScene("evidence");
    setStatus(`Case ${String(seg.team_number).padStart(2, "0")} — exhibit`);
    const video = $("evidence-video");
    activeVideo = video;
    $("evidence-placeholder").hidden = true;
    video.src = seg.demo_video;
    const done = new Promise((res) => {
      video.onended = res;
      video.onerror = res;
    });
    video.play().catch(() => {});
    await done;
    activeVideo = null;
    video.removeAttribute("src");
    video.load();
    if (mySeq !== seq) return;
    if (!(await waitMs(600, mySeq))) return;
  }

  showScene("dialogue");
  $("case-label").textContent = `Case ${String(seg.team_number).padStart(2, "0")}`;
  let proceeding = 0;
  for (const line of seg.lines) {
    if (mySeq !== seq) return;
    proceeding++;
    $("proceeding-label").textContent = `Proceeding ${String(proceeding).padStart(2, "0")} · ${KIND_LABEL[line.kind] || "Testimony"}`;
    setStatus(`Case ${String(seg.team_number).padStart(2, "0")} — ${KIND_LABEL[line.kind] || "testimony"}`);
    const ok = await playLine(line, mySeq);
    if (!ok) return;
  }
  clearSpeaker();

  showScene("close");
  setStatus(`Case ${String(seg.team_number).padStart(2, "0")} — closed`);
  const closeStamp = document.querySelector(".close-stamp");
  closeStamp.classList.remove("smash");
  void closeStamp.offsetWidth;
  closeStamp.classList.add("smash");
  if (!(await waitMs(5200, mySeq))) return;

  if (index + 1 < segments.length) {
    await playSegment(index + 1, mySeq);
  } else {
    showScene("end");
    setStatus("Adjourned");
  }
}

function jumpTo(index) {
  if (index < 0 || index >= segments.length) return;
  seq++;
  paused = false;
  $("btn-pause").textContent = "Pause";
  playSegment(index, seq);
}

function updateRail() {
  const rail = $("rail");
  rail.innerHTML = "";
  segments.forEach((seg, i) => {
    const frame = document.createElement("button");
    frame.className = "rail-frame";
    if (i < current) frame.classList.add("done");
    if (i === current) frame.classList.add("current");
    frame.textContent = `CASE ${String(seg.team_number).padStart(2, "0")}`;
    frame.title = seg.team_name || "";
    frame.addEventListener("click", () => jumpTo(i));
    rail.appendChild(frame);
  });
  const cur = rail.querySelector(".current");
  if (cur) cur.scrollIntoView({ inline: "center", block: "nearest" });
}

function pokeDock() {
  const dock = $("dock");
  dock.classList.remove("dock-hidden");
  clearTimeout(dockTimeout);
  dockTimeout = setTimeout(() => {
    if (!paused && started) dock.classList.add("dock-hidden");
  }, 3500);
}

function toggleDock(force) {
  const dock = $("dock");
  const show = force !== undefined ? force : dock.classList.contains("dock-hidden");
  dock.classList.toggle("dock-hidden", !show);
  if (show) pokeDock();
}

async function loadPlaylist() {
  try {
    const res = await fetch("segments/playlist.json");
    if (!res.ok) throw new Error("no playlist");
    playlist = await res.json();
    const loaded = await Promise.all(
      playlist.segments.map(async (file) => {
        const r = await fetch("segments/" + file);
        return r.ok ? r.json() : null;
      })
    );
    segments = loaded.filter(Boolean);
  } catch {
    segments = [];
  }
  if (!segments.length) {
    $("standby-sub").textContent = "No cases prepared — run prepare.py to build the docket.";
    $("btn-convene").disabled = true;
    $("btn-convene").textContent = "DOCKET EMPTY";
  }
  updateRail();
}

function convene() {
  if (!segments.length) return;
  started = true;
  $("dock").hidden = false;
  pokeDock();
  jumpTo(0);
}

function toStandby() {
  seq++;
  paused = false;
  started = false;
  showScene("standby");
  setStatus("Standby");
}

function bindControls() {
  $("btn-convene").addEventListener("click", convene);
  $("btn-prev").addEventListener("click", () => jumpTo(Math.max(0, current - 1)));
  $("btn-next").addEventListener("click", () => jumpTo(Math.min(segments.length - 1, current + 1)));
  $("btn-pause").addEventListener("click", () => setPaused(!paused));

  document.addEventListener("keydown", (e) => {
    if (e.code === "Space") {
      e.preventDefault();
      if (started) setPaused(!paused);
    } else if (e.key === "ArrowRight") {
      jumpTo(Math.min(segments.length - 1, current + 1));
    } else if (e.key === "ArrowLeft") {
      jumpTo(Math.max(0, current - 1));
    } else if (e.key === "f" || e.key === "F") {
      if (document.fullscreenElement) document.exitFullscreen();
      else document.documentElement.requestFullscreen().catch(() => {});
    } else if (e.key === "m" || e.key === "M") {
      muted = !muted;
      if (activeAudio) activeAudio.muted = muted;
      setStatus(muted ? "Muted" : "Sound on");
    } else if (e.key === "h" || e.key === "H") {
      toggleDock();
    } else if (e.key === "s" || e.key === "S") {
      toStandby();
    }
  });

  document.addEventListener("mousemove", () => {
    if (started) pokeDock();
  });
}

initScenes();
bindControls();
const boot = loadPlaylist();

const debugScene = new URLSearchParams(location.search).get("scene");
if (debugScene) {
  boot.then(() => {
    if (!segments.length) return;
    const segIndex = Math.min(segments.length - 1, parseInt(new URLSearchParams(location.search).get("seg") || "0", 10));
    const lineIndex = parseInt(new URLSearchParams(location.search).get("line") || "0", 10);
    current = segIndex;
    started = true;
    $("dock").hidden = false;
    updateRail();
    const seg = segments[segIndex];
    if (debugScene === "title") {
      showScene("title");
      $("title-team").textContent = seg.team_name || `Team ${seg.team_number}`;
      $("title-liner").textContent = seg.one_liner || "";
      $("case-stamp").textContent = `CASE ${String(seg.team_number).padStart(2, "0")}`;
    } else if (debugScene === "evidence") {
      showScene("evidence");
      if (seg.demo_video) {
        $("evidence-video").src = seg.demo_video;
        $("evidence-video").muted = true;
        $("evidence-video").play().catch(() => {});
      } else {
        $("evidence-placeholder").hidden = false;
      }
    } else if (debugScene === "dialogue") {
      showScene("dialogue");
      const line = seg.lines[Math.min(lineIndex, seg.lines.length - 1)];
      setSpeaker(line.speaker, line.kind);
      $("utterance").innerHTML = "";
      for (const w of line.text.split(/\s+/).filter(Boolean)) {
        const span = document.createElement("span");
        span.className = "word lit";
        span.textContent = w;
        $("utterance").appendChild(span);
        $("utterance").appendChild(document.createTextNode(" "));
      }
      $("case-label").textContent = `Case ${String(seg.team_number).padStart(2, "0")}`;
    } else if (debugScene === "close") {
      showScene("close");
    }
  });
}
