// DEV ONLY. A fake Part A server that returns the contract's example payloads with realistic delays.
// Never imported in a production build (see getApi in api.ts). Never used in the demo.
//
// The WebSocket is faked with a BroadcastChannel per room, so /stage and /play open as tabs
// in the same browser talk to each other like they would through the real hub.

import type {
  AnalyzeRes,
  Api,
  CallRes,
  ClientMsg,
  ClipKind,
  ClipRes,
  CreateRoundRes,
  RevealRes,
  RoomSocket,
  RosterEntry,
  ServerMsg,
} from './contract';

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const jitter = (base: number, spread = 0.3) => base * (1 - spread + Math.random() * spread * 2);

// `conn` identifies one socket, so the roster can drop exactly the phone that left.
type Envelope =
  | { from: 'server'; msg: ServerMsg }
  | { from: 'client'; conn: string; msg: ClientMsg }
  | { from: 'leave'; conn: string };

const channels = new Map<string, BroadcastChannel>();
function chan(room: string) {
  let c = channels.get(room);
  if (!c) {
    c = new BroadcastChannel(`poker-face-mock-ws:${room}`);
    channels.set(room, c);
  }
  return c;
}

// BroadcastChannel never delivers to the sender, so local listeners are notified directly too.
const localListeners = new Map<string, Set<(e: Envelope) => void>>();
function emit(room: string, e: Envelope) {
  chan(room).postMessage(e);
  localListeners.get(room)?.forEach((fn) => fn(e));
}
const broadcast = (room: string, msg: ServerMsg) => emit(room, { from: 'server', msg });

interface MockRound {
  room: string;
  lieIndex: number; // 0-based
  analyses: number;
  hadFollowup: boolean;
  followups: number; // answers recorded; the mock asks two follow-ups before it's confident
  votes: Map<string, number>;
}
const rounds = new Map<string, MockRound>();
const scoreboard = { gemini: 0, room: 0 };
const rosters = new Map<string, Map<string, RosterEntry>>(); // room -> conn -> entry

// Closing a tab doesn't run close(), so announce every socket in this tab as leaving.
const openSockets = new Map<string, string>(); // conn -> room
addEventListener('pagehide', () => openSockets.forEach((room, conn) => emit(room, { from: 'leave', conn })));
let seq = 0;

function roundOf(id: string): MockRound {
  const r = rounds.get(id);
  if (!r) throw new Error(`mock: unknown round ${id}`);
  return r;
}

// Hybrid mode (VITE_REAL): the real server owns some endpoints, and the mock is told about
// rounds and clips it did not create so its later endpoints keep working.
export function adoptRound(round_id: string, room: string, lieIndex = 1) {
  rounds.set(round_id, { room, lieIndex, analyses: 0, hadFollowup: false, followups: 0, votes: new Map() });
  broadcast(room, { type: 'phase', phase: 'baseline' });
}
export function noteClip(round_id: string, kind: ClipKind) {
  const r = rounds.get(round_id);
  if (!r) return;
  if (kind === 'statement') broadcast(r.room, { type: 'phase', phase: 'statements' });
  if (kind === 'followup') {
    r.hadFollowup = true;
    r.followups += 1;
  }
}

const PROMPTS: [string, string, string][] = [
  ['A place you have been', 'Something you can cook', 'A time you got in trouble'],
  ['Your first job', 'A pet you had', 'A famous person you met'],
  ['A sport you played', 'A city you lived in', 'A weird thing you ate'],
];

const TRANSCRIPTS = [
  "Okay, so, I'm Sam and I came here from Brooklyn this morning.",
  "Uh, I had cereal for breakfast. Pretty normal day so far.",
  'I once climbed Mount Kilimanjaro with my dad.',
  "I can, um, I can make fresh pasta from scratch. Like, no machine.",
  'I got sent home from school for selling candy out of my locker.',
  "Yeah, it was, it was the Machame route. Six days. We, uh, we didn't really train.",
];

export const mockApi: Api = {
  async createRound({ room }): Promise<CreateRoundRes> {
    await sleep(jitter(180));
    const round_id = `r${++seq}-${Date.now().toString(36)}`;
    const prompts = PROMPTS[seq % PROMPTS.length];
    adoptRound(round_id, room);
    return { round_id, prompts, baseline_prompts: ["Say your name and where you're from.", 'What did you eat today?'] };
  },

  async postClip(roundId, clip): Promise<ClipRes> {
    const r = roundOf(roundId);
    // ffmpeg convert + files.upload + Hydrogen transcript, scaled roughly by clip size
    await sleep(jitter(1400 + Math.min(clip.file.size / 2000, 1500)));
    noteClip(roundId, clip.kind);
    const t =
      clip.kind === 'baseline'
        ? TRANSCRIPTS[(clip.index - 1) % 2]
        : clip.kind === 'statement'
          ? TRANSCRIPTS[1 + clip.index]
          : TRANSCRIPTS[5];
    const isLie = clip.kind === 'followup' || (clip.kind === 'statement' && clip.index - 1 === r.lieIndex);
    return {
      clip_id: `c-${clip.kind}-${clip.index}-${Math.random().toString(36).slice(2, 7)}`,
      transcript: t,
      measures: {
        delay_ms: Math.round(isLie ? jitter(1400, 0.15) : jitter(450, 0.3)),
        fillers: isLie ? 3 : Math.round(Math.random()),
        blink_rate: +(isLie ? jitter(0.62, 0.1) : jitter(0.33, 0.2)).toFixed(2),
        gaze_breaks: isLie ? 2 : Math.round(Math.random()),
      },
    };
  },

  async analyze(roundId): Promise<AnalyzeRes> {
    const r = roundOf(roundId);
    r.analyses++;
    broadcast(r.room, { type: 'phase', phase: 'thinking' });

    const confident = r.followups >= 2; // like the real server: keep asking until sure
    const tells = confident
      ? [
          { statement: 2, t_s: 0.6, label: 'pause 1.4s' },
          { statement: 2, t_s: 2.1, label: 'gaze break' },
          { statement: 2, t_s: 3.4, label: 'self-correction' },
        ]
      : [
          { statement: 1, t_s: 1.2, label: 'filler "um"' },
          { statement: 2, t_s: 0.4, label: 'pause 1.4s' },
          { statement: 2, t_s: 3.4, label: 'gaze break' },
          { statement: 3, t_s: 2.0, label: 'speech rate up' },
        ];

    // Stream tells + suspicion while "thinking", like the real hub would.
    const steps = 12;
    const target = confident ? 0.86 : 0.62;
    const tellAt = new Map(tells.map((t, k) => [Math.round(((k + 1) * steps) / (tells.length + 1)), t]));
    for (let i = 1; i <= steps; i++) {
      await sleep(jitter(220, 0.4));
      broadcast(r.room, { type: 'suspicion', value: +(target * (i / steps) + Math.random() * 0.06).toFixed(3) });
      const tell = tellAt.get(i);
      if (tell) broadcast(r.room, { type: 'tell', ...tell });
    }

    if (!confident) {
      broadcast(r.room, { type: 'phase', phase: 'followup' });
      return {
        lie_probs: [0.2, 0.7, 0.1],
        confidence: 0.58,
        tells,
        escalate: true,
        follow_up:
          r.followups === 0
            ? { statement: 2, question: 'Which route did you take up the mountain, and how long did it take?' }
            : { statement: 1, question: 'What was the name of the restaurant, and what did you order?' },
      };
    }
    return { lie_probs: [0.08, 0.86, 0.06], confidence: 0.86, tells, escalate: false };
  },

  async call(roundId): Promise<CallRes> {
    const r = roundOf(roundId);
    await sleep(jitter(1100));
    broadcast(r.room, { type: 'phase', phase: 'call' });
    return {
      statement: 2,
      confidence: r.hadFollowup ? 0.86 : 0.7,
      t_s: 3.4,
      cue: 'gaze break',
      line: 'Statement 2: a 1.4 second pause and a gaze break when pressed.',
      frame_url: '/frames/mock-does-not-exist.jpg', // intentionally 404s to exercise the local-frame fallback
    };
  },

  async reveal(roundId, { tried_to_trick, lie_statement }): Promise<RevealRes> {
    const r = roundOf(roundId);
    r.lieIndex = lie_statement - 1; // the player says which one was the lie
    await sleep(jitter(300));
    const correct = r.lieIndex === 1; // mock call always says statement 2
    const votes = [...r.votes.values()];
    const room_accuracy = votes.length ? votes.filter((v) => v - 1 === r.lieIndex).length / votes.length : null;
    if (correct) scoreboard.gemini += room_accuracy != null && room_accuracy < 0.5 ? 2 : 1;
    if (room_accuracy != null && room_accuracy >= 0.5) scoreboard.room += 1;
    void tried_to_trick;
    broadcast(r.room, { type: 'phase', phase: 'reveal' });
    broadcast(r.room, { type: 'scoreboard', ...scoreboard });
    return { correct, lie_index: r.lieIndex, room_accuracy, scoreboard: { ...scoreboard } };
  },

  connect(room, onMsg): RoomSocket {
    const c = chan(room);
    const conn = Math.random().toString(36).slice(2);
    const players = rosters.get(room) ?? new Map<string, RosterEntry>();
    rosters.set(room, players);
    const sendRoster = () => onMsg({ type: 'roster', players: [...players.values()] });

    const handle = (e: Envelope) => {
      if (e.from === 'server') {
        onMsg(e.msg);
        return;
      }
      // Act as the hub for client messages. The roster: each tab keeps the one it has seen and reports
      // it to its own listeners only (a tab opened later would otherwise broadcast an incomplete list).
      if (e.from === 'leave') {
        if (players.delete(e.conn)) sendRoster();
        return;
      }
      if (e.msg.type === 'join') {
        players.set(e.conn, { name: e.msg.name, role: e.msg.role });
        sendRoster();
        return;
      }
      // Votes: record against the latest round in this room.
      if (e.msg.type === 'vote') {
        const latest = [...rounds.values()].filter((r) => r.room === room).at(-1);
        latest?.votes.set(`${Math.random()}`, e.msg.statement);
      }
    };
    const onEvent = (ev: MessageEvent<Envelope>) => handle(ev.data);
    c.addEventListener('message', onEvent);
    let set = localListeners.get(room);
    if (!set) localListeners.set(room, (set = new Set()));
    set.add(handle);
    openSockets.set(conn, room);
    setTimeout(() => {
      onMsg({ type: 'phase', phase: 'lobby' });
      sendRoster(); // like the real hub: a new connection gets the current roster
    }, jitter(120));
    return {
      send: (msg) => emit(room, { from: 'client', conn, msg }),
      close() {
        c.removeEventListener('message', onEvent);
        set!.delete(handle);
        openSockets.delete(conn);
        emit(room, { from: 'leave', conn });
      },
    };
  },
};
