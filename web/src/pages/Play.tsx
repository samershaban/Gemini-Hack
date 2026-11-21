import { useState } from 'react';
import { isMock } from '../api';
import type { Phase, Scoreboard } from '../contract';
import { useRoom } from '../lib/room';

type Role = 'eye' | 'voter';

export default function Play() {
  const params = new URLSearchParams(location.search);
  const [room, setRoom] = useState(params.get('room')?.toUpperCase() ?? '');
  const [name, setName] = useState('');
  const [joined, setJoined] = useState<Role | null>(null);
  const [phase, setPhase] = useState<Phase>('lobby');
  const [vote, setVote] = useState<number | null>(null);
  const [score, setScore] = useState<Scoreboard | null>(null);

  const send = useRoom(joined ? room : null, (m) => {
    if (m.type === 'phase') {
      setPhase(m.phase);
      if (m.phase === 'baseline') setVote(null); // new round
    }
    if (m.type === 'scoreboard') setScore(m.scoreboard);
  });

  const join = (role: Role) => {
    if (!room || !name.trim()) return;
    setJoined(role);
    // useRoom connects on the next render; the real socket queues until open
    setTimeout(() => send({ type: 'join', name: name.trim(), role }), 0);
  };

  const cast = (statement: number) => {
    if (vote !== null) return;
    setVote(statement);
    send({ type: 'vote', statement });
    navigator.vibrate?.([30, 40, 80]);
  };

  if (!joined) {
    return (
      <div className="play">
        <div className="brand">POKER FACE</div>
        <input className="field" placeholder="ROOM" value={room} maxLength={4} onChange={(e) => setRoom(e.target.value.toUpperCase())} />
        <input className="field" placeholder="Your name" value={name} maxLength={16} onChange={(e) => setName(e.target.value)} />
        <button className="btn big" disabled={!room || !name.trim()} onClick={() => join('voter')}>
          Vote
        </button>
        <button className="btn ghost" disabled={!room || !name.trim()} onClick={() => join('eye')}>
          Be an extra Eye (camera)
        </button>
        {isMock && <div className="mock-badge">MOCK API</div>}
      </div>
    );
  }

  if (joined === 'eye') {
    return (
      <div className="play">
        <div className="brand">EYE · {room}</div>
        <p>Camera angle mode comes next.</p>
      </div>
    );
  }

  const open = phase !== 'reveal' && phase !== 'lobby';
  return (
    <div className="play">
      <div className="brand">ROOM {room}</div>
      <div className="phase">{vote !== null ? 'LOCKED IN' : open ? 'WHICH ONE IS THE LIE?' : phase === 'reveal' ? 'REVEAL!' : 'WAITING…'}</div>
      <div className="vote-pad">
        {[1, 2, 3].map((n) => (
          <button key={n} className={`vote ${vote === n ? 'picked' : ''}`} disabled={!open || vote !== null} onClick={() => cast(n)}>
            {n}
          </button>
        ))}
      </div>
      {score && (
        <div className="board">
          <span>EYE {score.gemini}</span>
          <span className="vs">vs</span>
          <span>ROOM {score.room}</span>
        </div>
      )}
    </div>
  );
}
