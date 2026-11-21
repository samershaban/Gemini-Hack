import { useEffect, useRef } from 'react';
import { getApi } from '../api';
import type { ClientMsg, RoomSocket, ServerMsg } from '../contract';

/** Joins /ws/{room}. `onMsg` may change every render; the latest one is always used. */
export function useRoom(room: string | null, onMsg: (m: ServerMsg) => void) {
  const handler = useRef(onMsg);
  handler.current = onMsg;
  const sock = useRef<RoomSocket | null>(null);

  useEffect(() => {
    if (!room) return;
    let live = true;
    getApi().then((api) => {
      if (!live) return;
      sock.current = api.connect(room, (m) => handler.current(m));
    });
    return () => {
      live = false;
      sock.current?.close();
      sock.current = null;
    };
  }, [room]);

  return (m: ClientMsg) => sock.current?.send(m);
}

const ALPHA = 'ABCDEFGHJKLMNPQRSTUVWXYZ';
export function newRoomCode() {
  return Array.from({ length: 4 }, () => ALPHA[Math.floor(Math.random() * ALPHA.length)]).join('');
}

/** "0:03.4" */
export function fmtT(t: number) {
  const m = Math.floor(t / 60);
  const s = (t - m * 60).toFixed(1).padStart(4, '0');
  return `${m}:${s}`;
}
