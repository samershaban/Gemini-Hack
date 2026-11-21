import { useState } from 'react';
import { isMock, mockLabel } from '../api';
import type { Phase, Scoreboard } from '../contract';
import { useRoom } from '../lib/room';

export default function Play() {
  const params = new URLSearchParams(location.search);
  const [room, setRoom] = useState(params.get('room')?.toUpperCase() ?? '');
  const [name, setName] = useState('');
  const [joined, setJoined] = useState(false);
  const [phase, setPhase] = useState<Phase>('lobby');
  const [vote, setVote] = useState<number | null>(null);
  const [score, setScore] = useState<Scoreboard | null>(null);
  // set at the reveal: the real lie and how Gemini did
  const [outcome, setOutcome] = useState<{ lie: number; geminiCorrect: boolean } | null>(null);

  const send = useRoom(joined ? room : null, (m) => {
    if (m.type === 'phase') {
      setPhase(m.phase);
      if (m.phase === 'baseline') {
        // new round
        setVote(null);
        setOutcome(null);
      }
    }
    if (m.type === 'reveal_result') {
      setOutcome({ lie: m.lie_statement, geminiCorrect: m.gemini_correct });
      // right: one happy buzz; wrong: two short sad ones
      navigator.vibrate?.(vote === m.lie_statement ? [200] : [80, 60, 80]);
    }
    if (m.type === 'scoreboard') {
      const { type: _type, ...board } = m;
      setScore(board);
    }
  });

  // Phones only vote: the player is on stage and picks their own lie.
  const join = () => {
    if (!room || !name.trim()) return;
    setJoined(true);
    // useRoom connects on the next render; the real socket queues until open
    setTimeout(() => send({ type: 'join', name: name.trim(), role: 'voter' }), 0);
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
        <button className="btn big" disabled={!room || !name.trim()} onClick={join}>
          Vote
        </button>
        {isMock && <div className="mock-badge">{mockLabel}</div>}
      </div>
    );
  }

  // ---- reveal: full-screen right / wrong / didn't vote ----
  if (outcome) {
    const result = vote === null ? 'none' : vote === outcome.lie ? 'right' : 'wrong';
    const headline = { right: 'YOU GOT IT!', wrong: 'FOOLED YOU!', none: 'TOO LATE!' }[result];
    const detail =
      result === 'right'
        ? `It was #${outcome.lie}. Nice read.`
        : result === 'wrong'
          ? `You picked #${vote}. The lie was #${outcome.lie}.`
          : `You didn't vote. The lie was #${outcome.lie}.`;
    return (
      <div className={`play result result-${result}`}>
        <div className="result-big">{headline}</div>
        <div className="result-detail">{detail}</div>
        <div className="result-eye">{outcome.geminiCorrect ? 'The Eye got it too.' : 'The Eye got fooled.'}</div>
        {score && (
          <div className="board">
            <span>EYE {score.gemini}</span>
            <span className="vs">vs</span>
            <span>ROOM {score.room}</span>
          </div>
        )}
        <div className="result-next">Next round starts soon…</div>
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
