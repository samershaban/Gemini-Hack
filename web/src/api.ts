import type { Api, ClientMsg, RoomSocket, ServerMsg } from './contract';

const BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, '') ?? '';

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(BASE + path, init);
  if (!res.ok) throw new Error(`${init?.method ?? 'GET'} ${path} -> ${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}
const post = <T>(path: string, body?: unknown) =>
  json<T>(path, {
    method: 'POST',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });

function wsUrl(room: string) {
  const origin = BASE || location.origin;
  return origin.replace(/^http/, 'ws') + `/ws/${encodeURIComponent(room)}`;
}

export const realApi: Api = {
  createRound: (req) => post('/rounds', req),
  postClip(roundId, clip) {
    const fd = new FormData();
    const ext = clip.file.type.includes('mp4') ? 'mp4' : 'webm';
    fd.append('file', clip.file, `${clip.kind}-${clip.index}.${ext}`);
    fd.append('kind', clip.kind);
    fd.append('index', String(clip.index));
    fd.append('camera_id', clip.camera_id);
    return json(`/rounds/${roundId}/clips`, { method: 'POST', body: fd });
  },
  analyze: (id) => post(`/rounds/${id}/analyze`),
  call: (id) => post(`/rounds/${id}/call`),
  reveal: (id, req) => post(`/rounds/${id}/reveal`, req),

  connect(room, onMsg): RoomSocket {
    let ws: WebSocket | null = null;
    let closed = false;
    let retry = 500;
    const queue: ClientMsg[] = [];
    const open = () => {
      ws = new WebSocket(wsUrl(room));
      ws.onopen = () => {
        retry = 500;
        while (queue.length) ws!.send(JSON.stringify(queue.shift()));
      };
      ws.onmessage = (e) => {
        try {
          onMsg(JSON.parse(e.data) as ServerMsg);
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setTimeout(open, retry);
        retry = Math.min(retry * 2, 5000);
      };
    };
    open();
    return {
      send(m) {
        if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify(m));
        else queue.push(m);
      },
      close() {
        closed = true;
        ws?.close();
      },
    };
  },
};

// The mock is dev-only. In a production build `import.meta.env.DEV` is the literal `false`,
// so this branch and the mock chunk are dropped entirely: the demo can never hit the mock.
//
// Dev modes:
//   VITE_MOCK=0                 everything goes to the real server
//   VITE_REAL=rounds,clips      only the listed endpoints go to the real server, the rest are mocked
//                               (names: rounds, clips, analyze, call, reveal, ws)
//   (neither)                   everything is mocked
type Endpoint = 'rounds' | 'clips' | 'analyze' | 'call' | 'reveal' | 'ws';
const REAL = new Set(
  ((import.meta.env.VITE_REAL as string | undefined) ?? '').split(',').map((s) => s.trim()).filter(Boolean) as Endpoint[],
);
const useMock = import.meta.env.DEV && import.meta.env.VITE_MOCK !== '0';

let apiPromise: Promise<Api> | null = null;
export function getApi(): Promise<Api> {
  if (!apiPromise) {
    apiPromise = import.meta.env.DEV && useMock
      ? import('./mock').then((m) => {
          const real = (e: Endpoint) => REAL.has(e);
          const via = (e: Endpoint) => (real(e) ? realApi : m.mockApi);
          console.info(
            `%c[poker-face] real: ${[...REAL].join(', ') || 'none'} · mocked: the rest`,
            'background:#ff7a00;color:#000;padding:2px 6px',
          );
          const hybrid: Api = {
            async createRound(req) {
              const r = await via('rounds').createRound(req);
              if (real('rounds')) m.adoptRound(r.round_id, req.room);
              return r;
            },
            async postClip(id, clip) {
              const r = await via('clips').postClip(id, clip);
              if (real('clips')) m.noteClip(id, clip.kind);
              return r;
            },
            analyze: (id) => via('analyze').analyze(id),
            call: (id) => via('call').call(id),
            reveal: (id, req) => via('reveal').reveal(id, req),
            connect: (room, onMsg) => via('ws').connect(room, onMsg),
          };
          return hybrid;
        })
      : Promise.resolve(realApi);
  }
  return apiPromise;
}

export const isMock = useMock;
/** Short label for the stage badge, e.g. "MOCK API" or "MOCK: analyze, call, reveal, ws". */
export const mockLabel = !useMock
  ? ''
  : REAL.size === 0
    ? 'MOCK API'
    : 'MOCK: ' + (['rounds', 'clips', 'analyze', 'call', 'reveal', 'ws'] as const).filter((e) => !REAL.has(e)).join(', ');

/** Server-relative URLs (e.g. frame_url "/frames/x.jpg") resolved against the API origin. */
export const assetUrl = (u: string) => (u.startsWith('/') ? BASE + u : u);
