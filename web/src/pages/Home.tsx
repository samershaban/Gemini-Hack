import { lazy, Suspense, useCallback, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import type { EyeHandle } from '../eye/Eye';
import type { HomeProps } from '../eye/HomeProps';

// Lazy so the Babylon bundle never blocks the buttons (and phones heading to /play can skip it).
const Eye = lazy(() => import('../eye/Eye').then((m) => ({ default: m.Eye })));

const TITLE = 'POKER FACE';

export default function Home() {
  const eye = useRef<EyeHandle | null>(null);
  const props = useRef<HomeProps | null>(null);

  // When the Eye's 3D scene is ready: drop Ogle in and add the cards, chips, and sunburst.
  // (The SVG fallback has no scene, so it just shows the flat Eye.)
  const setEye = useCallback((handle: EyeHandle | null) => {
    eye.current = handle;
    if (!handle || props.current) return;
    handle.dropIn?.();
    const scene = handle.babylonScene?.();
    if (!scene) return;
    import('../eye/HomeProps').then(({ addHomeProps }) => {
      if (eye.current === handle && !props.current) props.current = addHomeProps(scene);
    });
  }, []);

  useEffect(
    () => () => {
      try {
        props.current?.dispose();
      } catch {
        // the Eye may have disposed the whole scene already
      }
      props.current = null;
    },
    [],
  );

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

  // the Eye reacts to the buttons: squints at New Game, looks smug at Join Game
  const react = (mood: 'squint' | 'smug' | 'idle') => () => eye.current?.setMood(mood);

  return (
    <div className="home">
      <div className="home-scene">
        <Suspense fallback={null}>
          <Eye ref={setEye} />
        </Suspense>
      </div>

      <div className="home-ui">
        <h1 className="home-title" aria-label={TITLE}>
          {TITLE.split('').map((letter, i) => (
            <span key={i} style={{ ['--i' as string]: i }} aria-hidden="true">
              {letter === ' ' ? ' ' : letter}
            </span>
          ))}
        </h1>

        <div className="home-bottom">
          <p className="home-tagline">Two truths and a lie. Gemini reads the tells. Can the room beat it?</p>
          <div className="home-buttons">
            <Link
              className="btn big"
              to="/stage"
              onPointerEnter={react('squint')}
              onPointerLeave={react('idle')}
              onClick={() => eye.current?.blink()}
            >
              New Game
            </Link>
            <Link className="btn ghost" to="/play" onPointerEnter={react('smug')} onPointerLeave={react('idle')}>
              Join Game
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
