// Mirror of the Part A <-> Part B contract in the PRD ("The contract").
// Change only by telling Belal.
//
// Open questions for Part A (assumptions used here):
//  - `statement` in tells / call / follow_up / vote is 1-based (1..3), matching "Statement 2" in `line`.
//  - `lie_index` in /reveal is 0-based, matching `lie_probs` indexing.
//  - clip `index` is 1-based within its kind (baseline 1-2, statement 1-3, followup 1).

export type ClipKind = 'baseline' | 'statement' | 'followup' | 'angle';

export interface CreateRoundReq {
  room: string;
}
export interface CreateRoundRes {
  round_id: string;
  prompts: [string, string, string];
}

export interface ClipUpload {
  file: Blob;
  kind: ClipKind;
  index: number;
  camera_id: string;
}
// Any measure is null when it couldn't be measured (no speech, no face found, transcription failed).
export interface Measures {
  delay_ms: number | null;
  fillers: number | null;
  blink_rate: number | null;
  gaze_breaks: number | null;
}
export interface ClipRes {
  clip_id: string;
  transcript: string;
  measures: Measures;
}

export interface Tell {
  statement: number;
  t_s: number;
  label: string;
}
export interface AnalyzeRes {
  lie_probs: [number, number, number];
  confidence: number;
  tells: Tell[];
  escalate: boolean;
  follow_up?: { statement: number; question: string };
}

export interface CallRes {
  statement: number;
  confidence: number;
  t_s: number;
  cue: string;
  line: string;
  frame_url: string;
}

export interface RevealReq {
  tried_to_trick: boolean;
}
export interface Scoreboard {
  gemini: number;
  room: number;
}
export interface RevealRes {
  correct: boolean;
  lie_index: number;
  room_accuracy: number;
  scoreboard: Scoreboard;
}

// ---- WebSocket /ws/{room} ----
export type Phase = 'lobby' | 'baseline' | 'statements' | 'thinking' | 'followup' | 'call' | 'reveal';

export type ServerMsg =
  | { type: 'phase'; phase: Phase }
  | { type: 'suspicion'; value: number }
  | { type: 'tell'; statement: number; t_s: number; label: string }
  | { type: 'scoreboard'; scoreboard: Scoreboard }
  | { type: 'secret'; statement: number };

export type ClientMsg =
  | { type: 'join'; name: string; role: 'eye' | 'voter' }
  | { type: 'vote'; statement: number };

export interface Api {
  createRound(req: CreateRoundReq): Promise<CreateRoundRes>;
  postClip(roundId: string, clip: ClipUpload): Promise<ClipRes>;
  analyze(roundId: string): Promise<AnalyzeRes>;
  call(roundId: string): Promise<CallRes>;
  reveal(roundId: string, req: RevealReq): Promise<RevealRes>;
  connect(room: string, onMsg: (m: ServerMsg) => void): RoomSocket;
}

export interface RoomSocket {
  send(m: ClientMsg): void;
  close(): void;
}
