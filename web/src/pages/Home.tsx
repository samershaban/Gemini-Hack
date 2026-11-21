import { lazy, Suspense, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { EyeHandle } from '../eye/Eye';

// Lazy so the Babylon bundle never blocks the buttons (and phones heading to /play can skip it).
const Eye = lazy(() => import('../eye/Eye').then((m) => ({ default: m.Eye })));

export default function Home() {
  const eye = useRef<EyeHandle | null>(null);

  // Ogle watches the pointer (or a finger) anywhere on the page
  useEffect(() => {
    const look = (e: PointerEvent) =>
      eye.current?.setLook((e.clientX / innerWidth) * 2 - 1, -((e.clientY / innerHeight) * 2 - 1));
    addEventListener('pointermove', look);
    addEventListener('pointerdown', look);
    return () => {
      removeEventListener('pointermove', look);
      removeEventListener('pointerdown', look);
    };
  }, []);

  return (
    <div className="play home">
      <div className="brand">POKER FACE</div>
      <div className="home-eye">
        <Suspense fallback={null}>
          <Eye ref={eye} />
        </Suspense>
      </div>
      <p className="home-tagline">Two truths and a lie. Gemini reads the tells. Can the room beat it?</p>
      <Link className="btn big" to="/stage">New Game</Link>
      <Link className="btn ghost" to="/play">Join Game</Link>
    </div>
  );
}
