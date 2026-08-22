# Archived approaches — what we tried before the living-agent courtroom

Round 1 judging went through three architectures in two days. The final one
(`judging/agents/` + `.opencode/agent/*.md`) won; the earlier two are kept in
git history and summarized here so we don't re-tread them.

## v1 — Python orchestrator + direct Qwen calls (`judging/discordx/`, still the deterministic backbone)

**How it worked:** one Python process ran four `discord.py` clients (Foreman +
3 jurors). Every spoken line was either a fixed template or a single-shot Qwen
API call returning strict JSON (blind scores + review + questions), posted back
by Python. Flow control (clocks, kicks, sheet write-back) all lived in `flows.py`.

**Why we moved on:**
- **Robotic delivery.** Every line read like a form: `The Builder — opening read:` +
  numbered questions, identical cadence every case. On a big screen it screamed "AI".
- **Fixed structure.** Judges could not react to each other or to a team's direct
  question; everything was pre-generated before the participant answered.
- **No real-world verification.** The "Builder" could only cite what the smoke test
  had already recorded — it could not click the submitted URL itself.

**What survived:** this layer is still the reliability core. Deterministic intake,
dedupe, smoke tests, blind scoring JSON, aggregation, tie-breaks, Sheet sync,
verdict artifacts — all of it runs unchanged under the new courtroom.

## v1.5 — Hermes Foreman voice (`foreman/setup.sh`, `~/.hermes-foreman`)

**How it worked:** same Python orchestrator, but Foreman lines were phrased by a
dedicated Hermes Agent instance (one-shot `hermes -z "VOICE REQUEST..." --cli
--safe-mode`) with a SOUL.md persona. Jurors stayed template/Qwen.

**What it proved:**
- A persona file (SOUL.md) + hard rules ("never leak scores") gives consistently
  in-character, ceremonial lines — the courtroom tone finally landed.
- Fallback design worked: Hermes timeout → template line, flow never blocked.

**Why we moved on:**
- **One-shot = amnesia.** Each request was a fresh session; the Foreman could not
  remember what it had said 30 seconds ago, so handoffs repeated near-verbatim.
- **Foreman-only.** The three jurors were still robotic; the show's weakest links
  were unchanged.
- **Extra runtime to babysit** (Hermes home, warm-up, PATH plumbing in systemd)
  for one voice out of four.

## v2 (final) — Living-agent courtroom (`judging/agents/` + opencode)

Each of the four bots is now an **opencode CLI instance** (`.opencode/agent/*.md`
personas) driven through a thin Discord shell:

- **Persistent per-case sessions** — Builder remembers its own opening question 40
  minutes later; handoffs never repeat verbatim.
- **Tools.** The agents curl the submitted URL themselves (caught a Vercel 404 mid-
  rehearsal), read the repo, and pull the evidence bundle from disk.
- **They see the thread.** Whole history goes into every turn, so Skeptic builds on
  Builder's exchange and answers direct @mentions conversationally.
- **Sequential by design with wait-for-reply**, 2-minute nudges, varied handoffs,
  post-kick deliberation statements posted before the verdict.

Determinism is preserved where it matters: scoring, tie-breaks, Sheet write-back,
and verdict artifacts remain the v1 Python service, invoked by the courtroom as a
substrate (`judging.service summon/deliberate`). Reliability beats cleverness —
the LLMs talk; the pipeline records.

**Operational notes:** run via `deploy/judging-agents.service`; mock rehearsal
still available with `--mock`; reset any team with `scripts/reset-team.sh <n>`.
