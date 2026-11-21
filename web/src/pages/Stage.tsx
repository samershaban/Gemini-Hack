import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { assetUrl, getApi, isMock, mockLabel } from '../api';
import type { AnalyzeRes, CallRes, ClipKind, ClipRes, CreateRoundRes, Measures, Phase, RevealRes, RosterEntry, Scoreboard, ServerMsg, Tell } from '../contract';
import { JoinQr } from '../components/JoinQr';
import { Eye, type EyeHandle } from '../eye/Eye';
import type { Mood } from '../eye/EyeScene';
import { ClipRecorder, frameAt, say, useCamera } from '../lib/media';
import { fmtT, newRoomCode, useRoom } from '../lib/room';

type SlotKey = `${ClipKind}-${number}`;
type Slot =
  | { s: 'empty' }
  | { s: 'recording'; since: number }
  | { s: 'uploading'; blob: Blob }
  | { s: 'done'; blob: Blob; res: ClipRes }
  | { s: 'failed'; blob: Blob; error: string };

const SLOTS: { key: SlotKey; kind: ClipKind; index: number; label: string }[] = [
  { key: 'baseline-1', kind: 'baseline', index: 1, label: 'Baseline 1' },
  { key: 'baseline-2', kind: 'baseline', index: 2, label: 'Baseline 2' },
  { key: 'statement-1', kind: 'statement', index: 1, label: 'Statement 1' },
  { key: 'statement-2', kind: 'statement', index: 2, label: 'Statement 2' },
  { key: 'statement-3', kind: 'statement', index: 3, label: 'Statement 3' },
];
const FOLLOWUP: (typeof SLOTS)[number] = { key: 'followup-1', kind: 'followup', index: 1, label: 'Follow-up' };

type Busy = null | 'round' | 'analyze' | 'call' | 'reveal';

function roomFromUrl() {
  const q = new URLSearchParams(location.search).get('room');
  if (q) return q.toUpperCase();
  const code = newRoomCode();
  history.replaceState(null, '', `?room=${code}`);
  return code;
}

export default function Stage() {
  const [room] = useState(roomFromUrl);
  const cam = useCamera();
  const eye = useRef<EyeHandle | null>(null);
  const preview = useRef<HTMLVideoElement>(null);
  const recorder = useRef<ClipRecorder | null>(null);

  const [round, setRound] = useState<CreateRoundRes | null>(null);
  const [slots, setSlots] = useState<Record<string, Slot>>({});
  const [phase, setPhase] = useState<Phase>('lobby');
  const [tells, setTells] = useState<Tell[]>([]);
  const [analysis, setAnalysis] = useState<AnalyzeRes | null>(null);
  // kept separately: a re-analyze after the follow-up returns no follow_up
  const [followUp, setFollowUp] = useState<AnalyzeRes['follow_up'] | null>(null);
  const [verdict, setVerdict] = useState<CallRes | null>(null);
  const [frame, setFrame] = useState<string | null>(null);
  const [stamp, setStamp] = useState(false);
  const [reveal, setReveal] = useState<RevealRes | null>(null);
  const [trick, setTrick] = useState(false);
  const [score, setScore] = useState<Scoreboard>({ gemini: 0, room: 0 });
  const [roster, setRoster] = useState<RosterEntry[]>([]);
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<string | null>(null);
  const [, force] = useState(0);

  // ---- camera ----
  useEffect(() => {
    if (cam.status !== 'ready') return;
    recorder.current = new ClipRecorder(cam.stream);
    if (preview.current) preview.current.srcObject = cam.stream;
  }, [cam]);

  // recording timer redraw
  const anyRecording = Object.values(slots).some((s) => s.s === 'recording');
  useEffect(() => {
    if (!anyRecording) return;
    const id = setInterval(() => force((n) => n + 1), 100);
    return () => clearInterval(id);
  }, [anyRecording]);

  // ---- room socket ----
  const onMsg = useCallback((m: ServerMsg) => {
    switch (m.type) {
      case 'phase':
        setPhase(m.phase);
        break;
      case 'suspicion':
        eye.current?.setSuspicion(m.value);
        break;
      case 'tell':
        addTells([{ statement: m.statement, t_s: m.t_s, label: m.label }]);
        break;
      case 'scoreboard': {
        const { type: _type, ...board } = m;
        setScore(board);
        break;
      }
      case 'roster':
        setRoster(m.players);
        break;
    }
  }, []);
  useRoom(room, onMsg);

  const addTells = (ts: Tell[]) =>
    setTells((prev) => {
      const seen = new Set(prev.map(tellKey));
      return [...prev, ...ts.filter((t) => !seen.has(tellKey(t)))];
    });

  // ---- mood from phase / results ----
  const mood: Mood = useMemo(() => {
    if (reveal) return reveal.correct ? 'smug' : 'dizzy';
    if (verdict) return 'busted';
    if (busy === 'analyze' || busy === 'call' || phase === 'thinking') return 'thinking';
    if (analysis?.escalate) return 'squint';
    return 'idle';
  }, [reveal, verdict, busy, phase, analysis]);
  useEffect(() => eye.current?.setMood(mood), [mood]);

  // pointer drives the gaze until face tracking lands
  useEffect(() => {
    const move = (e: PointerEvent) => eye.current?.setLook((e.clientX / innerWidth) * 2 - 1, -((e.clientY / innerHeight) * 2 - 1));
    addEventListener('pointermove', move);
    return () => removeEventListener('pointermove', move);
  }, []);

  // ---- actions ----
  const guard = async <T,>(what: Busy, fn: () => Promise<T>): Promise<T | undefined> => {
    setBusy(what);
    setError(null);
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  };

  const newRound = () =>
    guard('round', async () => {
      const api = await getApi();
      const r = await api.createRound({ room });
      setRound(r);
      setSlots({});
      setTells([]);
      setAnalysis(null);
      setFollowUp(null);
      setVerdict(null);
      setFrame(null);
      setStamp(false);
      setReveal(null);
      setTrick(false);
      eye.current?.setSuspicion(0);
    });

  const upload = async (slot: (typeof SLOTS)[number], blob: Blob) => {
    if (!round) return;
    setSlots((s) => ({ ...s, [slot.key]: { s: 'uploading', blob } }));
    try {
      const api = await getApi();
      const res = await api.postClip(round.round_id, { file: blob, kind: slot.kind, index: slot.index, camera_id: 'stage' });
      setSlots((s) => ({ ...s, [slot.key]: { s: 'done', blob, res } }));
    } catch (e) {
      setSlots((s) => ({ ...s, [slot.key]: { s: 'failed', blob, error: e instanceof Error ? e.message : String(e) } }));
    }
  };

  const tapSlot = async (slot: (typeof SLOTS)[number]) => {
    const rec = recorder.current;
    const cur = slots[slot.key] ?? { s: 'empty' };
    if (!rec || !round) return;
    if (cur.s === 'failed') return upload(slot, cur.blob);
    if (cur.s === 'recording') {
      const { blob } = await rec.stop();
      eye.current?.blink();
      if (blob.size === 0) {
        // the recorder produced nothing (seen once under heavy load); don't send an empty file
        setSlots((s) => ({ ...s, [slot.key]: { s: 'empty' } }));
        setError(`${slot.label} came out empty. Record it again.`);
        return;
      }
      return upload(slot, blob);
    }
    if (rec.recording) return; // one clip at a time
    rec.start();
    setSlots((s) => ({ ...s, [slot.key]: { s: 'recording', since: performance.now() } }));
  };

  const analyze = () =>
    guard('analyze', async () => {
      const api = await getApi();
      const a = await api.analyze(round!.round_id);
      setAnalysis(a);
      addTells(a.tells);
      eye.current?.setSuspicion(Math.max(...a.lie_probs));
      if (a.escalate && a.follow_up) {
        setFollowUp(a.follow_up);
        say(a.follow_up.question);
      }
    });

  const call = () =>
    guard('call', async () => {
      const api = await getApi();
      const c = await api.call(round!.round_id);
      setVerdict(c);
      setStamp(false);
      setFrame(c.frame_url ? assetUrl(c.frame_url) : null);
      say(`${c.line} I'm ${Math.round(c.confidence * 100)} percent sure.`);
      setTimeout(() => setStamp(true), 900); // squint + zoom first, then slam
    });

  // frame_url failed (or empty): grab the frame locally from the clip we recorded
  const localFrame = async () => {
    if (!verdict) return;
    const followup = slots[FOLLOWUP.key];
    const stmt = slots[`statement-${verdict.statement}`];
    const src = followUp?.statement === verdict.statement && followup && 'blob' in followup ? followup : stmt;
    const blob = src && 'blob' in src ? src.blob : null;
    setFrame(blob ? await frameAt(blob, verdict.t_s ?? 1) : null); // no timestamp: an early frame
  };

  const doReveal = () =>
    guard('reveal', async () => {
      const api = await getApi();
      const r = await api.reveal(round!.round_id, { tried_to_trick: trick });
      setReveal(r);
      setScore(r.scoreboard);
      setStamp(false);
      say(r.correct ? 'Busted. The Eye sees all.' : 'You got me. Well played.');
    });

  // ---- derived ----
  const slotState = (k: string): Slot => slots[k] ?? { s: 'empty' };
  const statementsDone = SLOTS.filter((s) => s.kind === 'statement').every((s) => slotState(s.key).s === 'done');
  const followupDone = slotState(FOLLOWUP.key).s === 'done';
  const needsFollowup = !!followUp && !followupDone;
  // also callable if the server escalated without a follow-up question, so a round never gets stuck
  const canCall = !!analysis && (!analysis.escalate || followupDone || !followUp) && !verdict;
  const reAnalyze = !!analysis?.escalate && followupDone;
  const visibleTells = tells.slice(-8);

  return (
    <div className="stage">
      <Eye ref={eye} className="stage-eye" />

      <header className="stage-top">
        <div className="brand">POKER FACE</div>
        <div className="room-code">
          ROOM <b>{room}</b>
        </div>
        <div className="board">
          <span>EYE {score.gemini}</span>
          <span className="vs">vs</span>
          <span>ROOM {score.room}</span>
        </div>
        {isMock && <div className="mock-badge">{mockLabel}</div>}
      </header>

      <div className="pip">
        {cam.status === 'ready' ? (
          <video ref={preview} autoPlay muted playsInline />
        ) : (
          <div className="pip-msg">{cam.status === 'error' ? `No camera: ${cam.error}` : 'Starting camera…'}</div>
        )}
        {anyRecording && <div className="rec-dot">REC</div>}
      </div>

      <aside className="side-right">
        {round && !verdict && (
          <ol className="prompts">
            {round.prompts.map((p, i) => (
              <li key={i}>
                <b>{i + 1}</b> {p}
              </li>
            ))}
          </ol>
        )}
        {!verdict && <Roster players={roster} points={score.players} />}
      </aside>

      {!verdict && !reveal && <JoinQr room={room} big={!round} />}
      <div className="chips">
        {visibleTells.map((t, i) => (
          <div key={tellKey(t)} className="chip" style={chipPos(i)}>
            <span className="chip-s">S{t.statement}</span> {fmtT(t.t_s)} {t.label}
          </div>
        ))}
      </div>

      {verdict && !reveal && (
        <div className="busted">
          <div className="busted-frame">
            {frame ? <img src={frame} onError={localFrame} alt="" /> : <FrameLoader onMount={localFrame} />}
            {stamp && <div className="stamp">BUSTED</div>}
          </div>
          <div className="busted-line">
            <div className="busted-big">
              STATEMENT {verdict.statement} <span>{Math.round(verdict.confidence * 100)}% sure</span>
            </div>
            {(verdict.t_s != null || verdict.cue) && (
              <div>{[fmtT(verdict.t_s), verdict.cue].filter(Boolean).join(' · ')}</div>
            )}
            <div className="busted-why">{verdict.line}</div>
          </div>
        </div>
      )}

      {reveal && (
        <div className={`reveal ${reveal.correct ? 'win' : 'lose'}`}>
          <div className="reveal-big">{reveal.correct ? 'THE EYE WINS' : 'YOU FOOLED THE EYE'}</div>
          <div>
            The lie was statement {reveal.lie_index + 1} ·{' '}
            {reveal.room_accuracy == null ? 'nobody voted' : `the room got it ${Math.round(reveal.room_accuracy * 100)}%`}
          </div>
        </div>
      )}

      <footer className="controls">
        {needsFollowup && followUp && (
          <div className="followup-card">
            <div className="followup-tag">ABOUT STATEMENT {followUp.statement}…</div>
            <div className="followup-q">{followUp.question}</div>
          </div>
        )}
        {!round ? (
          <button className="btn big" disabled={busy === 'round'} onClick={newRound}>
            {busy === 'round' ? 'Starting…' : 'New round'}
          </button>
        ) : (
          <>
            <div className="slots" hidden={!!verdict}>
              {[...SLOTS, ...(followUp ? [FOLLOWUP] : [])].map((slot) => (
                <SlotButton
                  key={slot.key}
                  label={slot.label}
                  slot={slotState(slot.key)}
                  disabled={cam.status !== 'ready' || (anyRecording && slotState(slot.key).s !== 'recording')}
                  onClick={() => tapSlot(slot)}
                />
              ))}
            </div>
            <div className="actions">
              {!analysis && (
                <button className="btn" disabled={!statementsDone || busy !== null} onClick={analyze}>
                  {busy === 'analyze' ? 'Reading…' : 'Analyze'}
                </button>
              )}
              {needsFollowup && <span className="hint">Record the follow-up answer →</span>}
              {reAnalyze && !verdict && (
                <button className="btn ghost" disabled={busy !== null} onClick={analyze}>
                  {busy === 'analyze' ? 'Reading…' : 'Re-analyze'}
                </button>
              )}
              {canCall && (
                <button className="btn hot" disabled={busy !== null} onClick={call}>
                  {busy === 'call' ? 'Deciding…' : 'Call it'}
                </button>
              )}
              {verdict && !reveal && (
                <>
                  <label className="toggle">
                    <input type="checkbox" checked={trick} onChange={(e) => setTrick(e.target.checked)} />
                    Trying to trick it?
                  </label>
                  <button className="btn hot" disabled={busy !== null} onClick={doReveal}>
                    {busy === 'reveal' ? '…' : 'Reveal'}
                  </button>
                </>
              )}
              {reveal && (
                <button className="btn" onClick={newRound}>
                  Next round
                </button>
              )}
            </div>
          </>
        )}
        {error && <div className="error">{error}</div>}
      </footer>
    </div>
  );
}

function SlotButton({ label, slot, disabled, onClick }: { label: string; slot: Slot; disabled: boolean; onClick: () => void }) {
  const sub =
    slot.s === 'recording'
      ? `● ${((performance.now() - slot.since) / 1000).toFixed(1)}s · tap to stop`
      : slot.s === 'uploading'
        ? 'uploading…'
        : slot.s === 'done'
          ? measureLine(slot.res.measures)
          : slot.s === 'failed'
            ? 'failed · tap to retry'
            : 'tap to record';
  return (
    <button className={`slot ${slot.s}`} disabled={disabled || slot.s === 'uploading'} onClick={onClick} title={slot.s === 'done' ? slot.res.transcript : slot.s === 'failed' ? slot.error : undefined}>
      <span className="slot-label">
        {slot.s === 'done' && '✓ '}
        {label}
      </span>
      <span className="slot-sub">{sub}</span>
    </button>
  );
}

function Roster({ players, points }: { players: RosterEntry[]; points?: Scoreboard['players'] }) {
  const pts = new Map(points?.map((p) => [p.name, p.points]));
  // the stage player first, then voters in join order
  const sorted = [...players].sort((a, b) => Number(b.role === 'player') - Number(a.role === 'player'));
  return (
    <div className="roster">
      <div className="roster-tag">IN THE ROOM · {players.length}</div>
      {players.length === 0 ? (
        <div className="roster-empty">Scan the QR code to join</div>
      ) : (
        <ul>
          {sorted.map((p) => (
            <li key={`${p.role}:${p.name}`}>
              <span className="roster-name">{p.name}</span>
              {p.role === 'player' && <span className="roster-role">PLAYER</span>}
              {pts.has(p.name) && <span className="roster-pts">{pts.get(p.name)}</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function FrameLoader({ onMount }: { onMount: () => void }) {
  useEffect(onMount, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <div className="frame-empty" />;
}

function measureLine(m: Measures) {
  const delay = m.delay_ms == null ? 'no speech' : `${m.delay_ms}ms delay`;
  const gaze = m.gaze_breaks == null ? 'no face' : `${m.gaze_breaks} gaze`;
  return `${delay} · ${gaze}`;
}

const tellKey = (t: Tell) => `${t.statement}|${t.t_s}|${t.label}`;

// chips flank the Eye (whose size scales with viewport height): alternate left/right, step down
function chipPos(i: number): React.CSSProperties {
  const side = i % 2 === 0 ? -1 : 1;
  const row = Math.floor(i / 2);
  const rot = ((i * 37) % 9) - 4;
  return {
    left: `calc(50% + ${side} * (24vh + ${150 + (row % 2) * 24}px))`,
    top: `${30 + row * 9}vh`,
    ['--rot' as string]: `${rot}deg`,
  };
}
