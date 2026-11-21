import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import { EyeScene, type Mood } from './EyeScene';

export type EyeHandle = EyeScene;

/** Full-bleed canvas hosting Ogle. The ref exposes the EyeScene API. */
export const Eye = forwardRef<EyeHandle | null, { className?: string }>(function Eye({ className }, ref) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<EyeScene | null>(null);

  // layout effect, declared before useImperativeHandle, so the handle sees the scene
  useLayoutEffect(() => {
    const s = new EyeScene(canvas.current!);
    scene.current = s;
    if (import.meta.env.DEV) {
      // dev poking: /stage?mood=busted&sus=0.9, or window.ogle.setMood('dizzy') in the console
      (window as unknown as { ogle: EyeScene }).ogle = s;
      const q = new URLSearchParams(location.search);
      const mood = q.get('mood');
      if (mood) setTimeout(() => s.setMood(mood as Mood), 50);
      if (q.get('sus')) s.setSuspicion(Number(q.get('sus')));
    }
    return () => {
      s.dispose();
      scene.current = null;
    };
  }, []);

  useImperativeHandle(ref, () => scene.current!, []);

  return <canvas ref={canvas} className={className} style={{ width: '100%', height: '100%', display: 'block', outline: 'none' }} />;
});
