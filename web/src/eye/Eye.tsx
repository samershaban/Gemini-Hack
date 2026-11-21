import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react';
import { EyeScene, type EyeApi, type Mood } from './EyeScene';
import { FlatEye } from './FlatEye';

export type EyeHandle = EyeApi;

/** Full-bleed Ogle. Uses the Babylon.js scene, or the SVG FlatEye if WebGL is unavailable. */
export const Eye = forwardRef<EyeHandle | null, { className?: string }>(function Eye({ className }, ref) {
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const eye = useRef<EyeApi | null>(null);

  // layout effect, declared before useImperativeHandle, so the handle sees the eye
  useLayoutEffect(() => {
    let e: EyeApi;
    try {
      e = new EyeScene(canvas.current!);
      canvas.current!.style.display = 'block';
    } catch (err) {
      // e.g. "WebGL not supported": blocked GPU, embedded browser, hardware acceleration off
      console.warn('[poker-face] WebGL unavailable, using the flat Eye:', err);
      canvas.current!.style.display = 'none';
      e = new FlatEye(box.current!);
    }
    eye.current = e;
    if (import.meta.env.DEV) {
      // dev poking: /stage?mood=busted&sus=0.9, or window.ogle.setMood('dizzy') in the console.
      // Add &flat to force the SVG fallback.
      const q = new URLSearchParams(location.search);
      if (q.has('flat') && e instanceof EyeScene) {
        e.dispose();
        canvas.current!.style.display = 'none';
        e = eye.current = new FlatEye(box.current!);
      }
      (window as unknown as { ogle: EyeApi }).ogle = e;
      const mood = q.get('mood');
      if (mood) setTimeout(() => e.setMood(mood as Mood), 50);
      if (q.get('sus')) e.setSuspicion(Number(q.get('sus')));
    }
    return () => {
      e.dispose();
      eye.current = null;
    };
  }, []);

  useImperativeHandle(ref, () => eye.current!, []);

  return (
    <div ref={box} className={className} style={{ width: '100%', height: '100%' }}>
      <canvas ref={canvas} style={{ width: '100%', height: '100%', display: 'block', outline: 'none' }} />
    </div>
  );
});
