# Poker Face: Room Edition PRD

Nov 21, 2026 · @belal

A live bluffing game where Gemini 4 plays against the whole room, built for Problem Statement Two (Element 119) at the Gemini 4 NYC Hackathon.

## Summary

**Pitch line:** A transcript can't tell a lie from the truth. We measured how much raw video and audio can, how many players Gemini can watch at once before it breaks, and whether it knows when it's guessing.

**The moment:** a player on stage says two truths and a lie on camera. Gemini studies the tells, asks one follow-up question, then calls the lie out loud with its confidence. Everyone in the room votes on their phones at the same time. The reveal is a live Gemini vs. the Room scoreboard.

**Why it wins:** it is fun to watch, the judges and audience play it live on inputs we never saw, and every round played during the day becomes unscripted eval data.

**Problem statement:** Two (Element 119). Tells such as pauses, gaze breaks and pitch changes only exist in raw media, which is exactly what this statement asks us to prove.

**Out of scope:** this is a game opponent reading in-the-moment signals. It is not a lie detector, and we never claim it is.

## Problem statement fit

We enter Element 119 because our core claim, that tells live in raw media and not in text, is the question it asks. We skip 5 Sigma: it asks for reliability, and people catch lies only about 54% of the time ([source](https://arxiv.org/pdf/2211.13035)), so we cannot promise that.

| Element 119 asks | What it is really testing | Our answer | What we show |
| --- | --- | --- | --- |
| Build something that only works because Gemini 4 can see, hear and generate media | Is media the core, or decoration? | Camera and mic are the only inputs; the game cannot run on text | Live round with judges |
| What does your project get from the raw video, audio or images that a text description would lose? | Proof the media matters | Modality ablation: every round scored on transcript only, audio only, video only, and all combined | One bar chart: transcript near chance, all combined highest |
| What's the hardest input you can throw at it, and does it still hold up? | Stress beyond the happy path | Rounds tagged hard: poker face, loud room, rehearsed lie, people talking over each other | Accuracy per tag, plus calibration showing it knows when it is unsure |
| How far did you push before it broke, and what did you change? | Engineering mindset | Multi-stream test at 1, 2, 4 and 8 phone cameras, then a stream-gating fix | Before and after: broke at N streams, handled M after the fix |
| Push them as far as they go: longer footage, messier audio, more streams at once, faster real-time loops | Scale or speed, not just a demo | We push "more streams at once" and "faster real-time loops" | Latency per stream count |
| Use any Gemini 4 models plus the Decisions API | Depth of use | Hydrogen and Carbon each with one job; Decision 1 used five ways | Model jobs table, Decisions API section |
| Not allowed: text-only chatbots, scripted-input demos, evals made only of team-written examples | Honesty | Live players, crowd-played rounds, a held-out split | "N rounds from real players, none scripted" |

## Judging criteria

Round one weights the live demo and proof most heavily, so both are built in from the first hour, not added at the end. Round two (top six, on stage) weights all four equally, where the crowd moment matters most.

| Criterion | Weight (round one) | What judges ask | How we score |
| --- | --- | --- | --- |
| Live Demo | 35% | Does it work live on real, unrehearsed inputs? | Judges play a round cold; the room votes on phones; Gemini always shows its confidence, so a wrong call reads as "it told you it was unsure" |
| Proof It Works | 25% | Test against a baseline, an honest look at failures, or a plan the agent checks itself against | Three baselines, modality ablation, multi-stream stress test, calibration plot, failure tags, held-out split |
| Creativity | 20% | A problem others avoid; beyond a text interface in a way that matters | A room-scale game where the audience competes with Gemini; the media is the whole point |
| Gemini 4 and Decisions API use | 20% | At least two Gemini 4 models with clear jobs; how far they push reasoning, speed or multimodality | Hydrogen for speed, Carbon for reasoning, Decision 1 used five ways including routing and stream gating |

## How it works

A round takes about 90 seconds, and every step runs on live camera and mic input.

1. **Join:** the room scans a QR code; phones open the voting page. Players at the table also stream their front camera.
2. **Statements:** the stage player says three statements. Hydrogen transcribes and splits them into three clips.
3. **Tells:** Decision 1 scores each clip with one batched call (pause, gaze break, hedging, pitch rise, self-correction) and a choice question: which statement is the lie?
4. **Route:** if Decision 1 is confident, Gemini calls it right away. If not, Carbon picks the statement to press on and writes one follow-up question.
5. **Follow-up:** the player answers; that clip is scored again.
6. **Call:** Carbon makes the final call and explains it in one line ("Statement 2: a 1.4 second pause and a gaze break when pressed"). The host voice reads it out.
7. **Reveal:** the player reveals the lie. The scoreboard shows Gemini vs. the Room, with bonus points for catching the lie when most of the room missed it.
8. **Log:** the round, its scores and the true answer are saved for the eval.

A second round type flips it: Gemini tells two truths and a lie, and the room guesses. It always works and keeps the energy up if a call goes wrong.

| Component | Its one job | Why this one |
| --- | --- | --- |
| Gemini 4 Hydrogen | Fast live transcription, splitting statements, the host's table talk | The fast, low-cost tier, built for high-throughput work; takes audio and video input |
| Gemini 4 Carbon | Combine all signals, choose the follow-up question, make and explain the final call | The deep-reasoning tier, for the decisions that need it |
| Gemini Decision 1 (Decisions API) | Score tells, choose the lie, route to Carbon, gate streams | Calibrated closed-set answers in about 200 ms, cheap enough to call on every clip |
| Phone web app | Votes, per-player camera streams | Room-scale interactivity, served from a hosted URL with a tunnel as backup |
| Browser text-to-speech | The host's voice | Saves build time; swap for a Gemini voice model if time allows |

## Decisions API

We use every major feature of the Decisions API, not just yes/no checks. Decision 1 answers up to 1,000 closed questions against one multimodal input, with a 0 to 1 confidence on each answer and no output tokens ([source](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/)).

| Use | Question type | What it does in the game |
| --- | --- | --- |
| Batched tells | Yes/no | Dozens of tell checks per clip in one call: pause before answering, gaze break, hedging words, pitch rise, self-correction |
| Pick the lie | Choice | "Which of the three statements is false?" across all three clips |
| Hesitation level | Score | Scores the behavior in that moment (never the person), feeding the tells meter on screen |
| Routing | Yes/no with confidence | Confident: call it now. Unsure: escalate to Carbon for a follow-up question. Google uses the API the same way, as a router to the right model tier |
| Stream gating | Yes/no | "Is this player speaking right now?" on every phone stream, so only active streams get full analysis. This is our fix for the multi-stream breaking point |

The calibrated confidences also power the calibration check in the eval: when Gemini says 70% sure, is it right about 70% of the time?

## Proof it works

Our headline number is how often Gemini catches the lie on rounds played by people outside the team, against three baselines. Nothing is trained, so there is nothing to overfit; the data only measures the system.

**Data**

- Every round played all day is logged with the true answer: hackers at lunch, judges in round one. Target: 40 or more rounds.
- The team never scripts statements. Players get verbal consent; clips are deleted after the event.
- Lock a held-out set of the first 15 rounds before any prompt tuning. Report it separately.

**Baselines**

- Random guessing: 33%.
- One Hydrogen call on the whole round video: "which statement is the lie?"
- The room: the share of phone votes that picked the right statement.

**Tests**

1. **Modality ablation:** score every round four ways (transcript only, audio only, video only, all combined). This answers what raw media gives that text loses.
2. **Hard inputs:** tag rounds as poker face, loud room, rehearsed lie or crosstalk, and report accuracy per tag.
3. **Multi-stream stress test:** run 1, 2, 4 and 8 phone streams; measure latency per round and accuracy. Add stream gating, rerun, show before and after.
4. **Calibration:** bucket calls by confidence and compare with actual accuracy.
5. **Agent loop check:** accuracy with and without Carbon's follow-up question.

| Run | Rounds | Accuracy | Avg latency (s) | Notes |
| --- | --- | --- | --- | --- |
| Random |  | 33% |  |  |
| Single Hydrogen call |  |  |  |  |
| The room (phone votes) |  |  |  |  |
| Poker Face, transcript only |  |  |  |  |
| Poker Face, all modalities |  |  |  |  |
| Poker Face, with follow-up |  |  |  |  |

Even a modest win over 33% is a real, honest result. We report it as is, with the failures.

## Live demo

The judges are the players, so every input is unrehearsed. Three minutes, then two minutes of Q&A.

1. **0:00 to 0:20, hook:** "A transcript can't tell a lie from the truth. Can Gemini read a room?" QR code on screen; judges join on their phones.
2. **0:20 to 1:30, round one:** a judge gives two truths and a lie. The tells meter moves live, Gemini asks its follow-up, then calls the lie with its confidence. Phone votes reveal Gemini vs. the judges.
3. **1:30 to 2:10, round two:** Gemini bluffs; the judges guess.
4. **2:10 to 2:50, proof:** the ablation chart, the stream test before and after, the calibration plot, the result against the baselines.
5. **2:50 to 3:00, limits:** where it fails (poker faces, crosstalk) and what's next.

**Backup:** a recorded round, shown only if the live one stalls, and we say it is a backup.

**Q&A prep**

- *Isn't this a lie detector?* No. It is a game opponent reading in-the-moment signals, and the calibration plot shows it knows when it is guessing.
- *How do you know the media matters?* The ablation: transcript only vs. all modalities.
- *Why two models?* Hydrogen for speed on every clip, Carbon only when a call is hard; Decision 1 routes between them.
- *What did you build today?* All of it. The repo's first commit is from today.
- *Prior experience?* Only if true: experience with fast structured-decision models, which is why the design is built around closed-set questions.

## Revisions (v2): tells, cameras, UI

These changes replace the matching parts of the technical design and build plan below.

**1. Tells come from three layers, not Decision 1 alone.** Decision 1 is a single-pass classifier: great at calibrated choices and gates, weak at millisecond timing. So each layer does what it is best at.

| Layer | Tool | What it produces |
| --- | --- | --- |
| Measure | Code: audio onset, transcript word timestamps, MediaPipe Face Mesh | Response delay, fillers, self-corrections, speech rate, blink rate, gaze breaks, face touches, each as a difference from that player's baseline |
| Observe | Neon, agentic video | Timestamped observations a formula can't catch: detail level, a smile that doesn't match, a hesitation right when pressed |
| Decide | Decision 1 | Input: the clips plus the measured differences and Neon's notes as text. Output: calibrated choice of the lie. Also gates: is the speech clear (if not, down-weight audio), is the player in frame |

**2. The room becomes cameras, not players.** One person speaks at a time, so venue noise stays the same no matter how many phones join. Audience phones point at the stage player from different angles. The stress test becomes: does Gemini read the same person better from 1, 2, 4 or 8 angles at once, and where does latency break? A replay test (saved rounds sent in parallel) measures load without crowd noise. Phones still vote.

**3. Crazy UI: "The Eye."** Inspired by Probe's bold, flat, high-contrast style and Chambara's phone-to-screen setup, rebuilt from scratch today with an original mascot (rules: new work only, assets we own).

- **Stage (Babylon.js):** a giant cartoon eyeball fills the screen. It follows the player's face (MediaPipe position), the pupil dilates as suspicion rises, and tells pop out as floating chips with timestamps ("0:03.4 gaze break").
- **The call:** the Eye squints, zooms in, and slams a BUSTED stamp over the still frame at the exact tell moment. Fooled it? The Eye spins dizzy.
- **Phones (Chambara pattern):** scan a QR code, enter a room, and the phone either becomes an extra Eye (camera angle) or a voting pad. It vibrates when your vote locks; your score sits on the Gemini vs. the Room board.
- **Palette:** orange, yellow, black and white with one chunky rounded typeface.

**4. Plan changes.** The teammate owns the Eye scene in Babylon.js and the phone pages. Belal adds MediaPipe and audio-onset measurement to `/clips` and builds the fused Decision 1 call. The multi-angle stress test replaces the multi-player stream test.

## Technical design

One laptop runs everything: a Python FastAPI server for all Gemini calls and a React app with two screens (stage and phone). Phones reach the laptop through a Cloudflare tunnel; they only send votes and short clips, so load stays small.

### Two parts, built in parallel

The build splits into Part A (the brain) and Part B (the show). They meet only at the contract below, so each person can build and test alone until the 1:00 PM integration.

|  | **Part A: Brain** (Belal) | **Part B: Show** (teammate) |
| --- | --- | --- |
| Folders | `server/`, `eval/` | `web/` |
| Owns | FastAPI server, ffmpeg, measurement layer (audio onset, transcript timestamps, MediaPipe Face Mesh), Gemini calls (Hydrogen, Neon, Decision 1), SQLite, room state and WebSocket hub, eval and stress tests | The Eye stage in Babylon.js, clip recording on stage and phones, phone pages (join, camera angle, vote), scoreboard, reveal, Wall of Busted, host voice, Cloudflare tunnel and QR code |
| Builds against | Saved test clips and curl, no browser needed | `web/src/mock.ts`: a fake server that returns the example payloads below with realistic delays (development only, never in the demo) |
| Done when | `curl` on a recorded round returns a call with confidence and a timestamp | A full round plays on the Eye screen against the mock, with two phones joined |

**The contract (agree at 11:45, change only by telling each other)**

| Endpoint | Sent by B | Returned by A |
| --- | --- | --- |
| `POST /rounds` | `{room}` | `{round_id, prompts: [p1, p2, p3]}`; the server secretly picks the lie |
| `POST /rounds/{id}/clips` | multipart: `file`, `kind` (baseline, statement, followup, angle), `index`, `camera_id` | `{clip_id, transcript, measures: {delay_ms, fillers, blink_rate, gaze_breaks}}` |
| `POST /rounds/{id}/analyze` | none | `{lie_probs: [0.2, 0.7, 0.1], confidence, tells: [{statement, t_s, label}], escalate, follow_up?: {statement, question}}` |
| `POST /rounds/{id}/call` | none | `{statement, confidence, t_s, cue, line, frame_url}` |
| `POST /rounds/{id}/reveal` | `{tried_to_trick}` | `{correct, lie_index, room_accuracy, scoreboard}` |

**WebSocket `/ws/{room}` messages** (JSON with a `type` field)

- From A to all screens: `phase` (`lobby`, `baseline`, `statements`, `thinking`, `followup`, `call`, `reveal`), `suspicion` (0 to 1, drives pupil size), `tell` (`{statement, t_s, label}` to pop a chip), `scoreboard`.
- From phones to A: `join` (`{name, role: "eye" | "voter"}`), `vote` (`{statement}`), `secret` (A sends the player's phone which prompt to lie on, only to that phone).

**Integration checkpoints**

1. **12:15:** B points `api.ts` at A's real server for `/clips` only; one stage clip uploads and returns measures.
2. **1:00:** swap the mock out completely; one full round runs end to end.
3. **2:45:** phone camera angles feed real clips; votes reach the scoreboard.

**Stack**

- **Backend:** Python 3.11, FastAPI, uvicorn, `google-genai>=3.2.0`, SQLite, ffmpeg (clip conversion, audio-only and video-only variants, still frames).
- **Frontend:** Vite + React + TypeScript. `/stage` on the laptop and projector, `/play` on phones. `getUserMedia` + `MediaRecorder` for clips, a WebSocket for room state, browser `speechSynthesis` for the host voice.
- **Clients:** `client = genai.Client()` for Neon and Hydrogen; `beta_client = genai.Client(http_options={"api_version": "v1beta"})` for the Decisions API and Managed Agents. Keep all model IDs in one `models.py`.

**Model IDs:** `gemini-decision-1`, `gemini-4-neon`, `gemini-4-hydrogen`, `gemini-4-carbon` (Tell Reports, stretch), `antigravity-preview-09-2026` (eval agent, stretch), `gemini-omni-1.2-flash` (BUSTED clip, stretch), `gemini-3.8-live` (interruptions, stretch).

**Round pipeline**

1. **Record.** The stage operator taps Baseline 1, Baseline 2, Statement 1, 2, 3. Each tap records one clip. Manual taps beat auto-splitting for demo reliability.
2. **Upload.** The server converts each WebM clip to MP4 with ffmpeg and uploads it with `client.files.upload`.
3. **Transcribe (Hydrogen, low thinking).** One call per clip returns the transcript. Needed for the transcript-only condition and the host's lines.
4. **Score tells (Decision 1).** One call per statement. Input: both baseline clips, then the statement clip, with text labels. Questions: about 10 `noul` tells ("longer pause than in BASELINE?", "gaze breaks away?", "hedging words?", "pitch rises?", "self-correction?", "cues look exaggerated compared with BASELINE?") plus one `score` question for hesitation level.
5. **Pick the lie (Decision 1).** One `choice` call over all three statement clips. Keys: `statement_1`, `statement_2`, `statement_3`, `other`.
6. **Route.** Confidence at or above 0.75: go to the call. Below 0.75: escalate.
7. **Escalate (Neon, medium thinking, agentic video).** Input: the two closest statement clips with `"processing": "agentic"`. Structured output: `{suspect_statement, timestamp_s, cue, follow_up_question}`. The host reads the question; the player answers; that clip goes back through steps 2 to 5. Cap: 1 follow-up live, 3 in eval runs.
8. **Call (Neon, low thinking).** One line with the statement, confidence and the timestamped cue.
9. **Reveal.** The player taps the true lie and "Were you trying to trick it?" on their phone. The server saves the round, extracts a still frame at `timestamp_s` for the BUSTED screen, and updates the scoreboard.

**Eval harness (`eval/run_eval.py`)**

- Reads every saved round from SQLite; the first 15 rounds are the locked holdout.
- Conditions: random; one Hydrogen call on the whole round video; room votes; Decision 1 on transcript only, audio only (ffmpeg `-vn`), video only (ffmpeg `-an`), all combined; with and without the follow-up.
- Limit tests: Decision questions per call at 10, 100 and 1,000; Neon default frame sampling vs agentic on the same clips; streams at 1, 2, 4 and 8 sent at once with `asyncio`, before and after the speaking-gate fix.
- Calibration: bucket calls by confidence and compare with accuracy.
- Writes `results.json` and matplotlib PNGs into `docs/`; the README table reads from them.

**Repo layout**

```
poker-face/
  server/  main.py  models.py  pipeline.py  decisions.py  db.py  media.py
  web/     src/pages/Stage.tsx  src/pages/Play.tsx  src/api.ts
  eval/    run_eval.py  stress_streams.py
  docs/    results.json  *.png
  README.md
```

## Build plan for two

One round working end to end by 1:00 PM comes before any polish. Feature freeze at 4:00, submit by 4:45. Belal owns the server, Gemini calls and eval; the teammate owns everything in the browser. Swap if your strengths run the other way.

| Time | Belal: server, Gemini, eval | Teammate: stage and phone apps | Checkpoint |
| --- | --- | --- | --- |
| 11:30 to 11:45 | Public repo, `models.py`, API key in `.env`, `pip install -U "google-genai>=3.2.0"` | Vite + React app, `/stage` and `/play` routes, Cloudflare tunnel up | Both can push |
| 11:45 to 12:15 | Time three calls on one 5-second clip: Decision 1, Neon agentic video, Omni 5 seconds | Webcam and mic capture: one tap records one clip and posts it to `/clips` | API contract agreed; latencies written in README |
| 12:15 to 1:00 | `/clips` (ffmpeg, upload, Hydrogen transcript), `/analyze` (tells + choice) | Stage flow: Baseline 1, 2, Statement 1, 2, 3 buttons; tells meter from `/analyze` | **One round end to end** |
| 1:00 to 1:45 | Lunch: run rounds with other hackers; build escalation (Neon follow-up) | Lunch: run rounds; `/play` voting over the WebSocket; QR code on stage | 10+ rounds saved |
| 1:45 to 2:45 | `/call`, `/reveal`, still frame at the timestamp; `run_eval.py` baselines | Reveal screen, scoreboard, host voice, BUSTED overlay, "trying to trick it?" toggle | Full round with phones |
| 2:45 to 3:30 | Ablation, calibration, questions-per-call and frame-sampling tests, stream stress test and gate fix | Keep collecting rounds; polish stage UI; fallback for no camera or audio | 30+ rounds; first results |
| 3:30 to 4:00 | Fix the biggest failure category; rerun for v2 numbers; charts into `docs/` | README: problem, pipeline, model jobs, results, failures | **Feature freeze** |
| 4:00 to 4:30 | Rehearse the 3-minute demo twice | Record the 1-minute video | Video uploaded |
| 4:30 to 4:45 | Submit: repo public, both teammates added | Check the demo link from a phone off Wi-Fi | **Submitted** |

**Stretch, only if ahead at 3:30 (in this order):** Omni BUSTED clip, 3.8 Live interruptions, Carbon Tell Reports, Managed Agent that reruns `run_eval.py` in its sandbox (also makes us eligible for the Managed Agents prize).

**Cut list if behind:** streams test drops to 1, 2 and 4; then the questions-per-call test; then the frame-sampling test. The modality ablation, baselines and calibration are never cut.

**Rules for the day**

- [ ] Every API call has a fallback so one failure never stops a round
- [ ] No mocked responses in the demo
- [ ] Get verbal consent before recording anyone; delete clips after the event
- [ ] Check in with the Google mentors early to sanity-check the pipeline and demo flow

## Risks and rules

Any rule break means disqualification, so these come before features.

**Rules we can't break**

- No code written before today; the demo shows only what we built today.
- The repo is public.
- The eval is not made only of examples we wrote.
- No Streamlit, and no dashboard as the main feature: the results stay one screen inside the game.
- Only data we have rights to: no courtroom or TV deception datasets; rounds come from consenting players today.

| Risk | What we do |
| --- | --- |
| Read as a banned "personality analyzer" or lie detector | Always called a game opponent; scores behaviors in the moment, never people; calibration shows its limits |
| Wrong call on stage | Confidence always on screen; Gemini bluff round as a guaranteed win |
| Accuracy near chance | Report it honestly; the ablation and calibration still prove what the media adds |
| Too many phones hit the laptop | Hosted phone page; tunnel only as backup |
| Noisy venue audio | Clip-on or close phone mic for the stage player; tag noisy rounds |
| Gemini access arrives late | Whoever has access first runs the calls |
| Privacy | Verbal consent before recording; clips deleted after the event; no names stored |

## Sources

- Gemini 4 NYC Hackathon Participant Guide (from the organizers): problem statements, rules, judging, schedule
- [Gemini Decisions API: Fast, calibrated multimodal decisions](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/) (Google, Nov 11, 2026)
- [Gemini 4 Neon launch and model picker](https://9to5google.com/2026/11/18/gemini-4-neon/) (9to5Google, Nov 18, 2026)
- [Gemini 4 Hydrogen specifications](https://cometapi.com/models/google/gemini-4-hydrogen/) (input modalities, context window)
- [Can lies be faked? Low-stakes vs. high-stakes deception datasets](https://arxiv.org/pdf/2211.13035) (human accuracy of about 54%)
