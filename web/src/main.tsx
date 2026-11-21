import '@fontsource/fredoka/500.css';
import '@fontsource/fredoka/700.css';
import './styles.css';
import { lazy, StrictMode, Suspense } from 'react';
import { createRoot } from 'react-dom/client';
import { createBrowserRouter, Link, Navigate, RouterProvider } from 'react-router-dom';

// Stage pulls in Babylon; phones on /play never download it.
const Stage = lazy(() => import('./pages/Stage'));
const Play = lazy(() => import('./pages/Play'));

const router = createBrowserRouter([
  { path: '/', element: <Home /> },
  { path: '/stage', element: <Stage /> },
  { path: '/play', element: <Play /> },
  { path: '*', element: <Navigate to="/" replace /> },
]);

function Home() {
  return (
    <div className="play">
      <div className="brand">POKER FACE</div>
      <Link className="btn big" to="/stage">Stage</Link>
      <Link className="btn ghost" to="/play">Play</Link>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Suspense fallback={<div className="play"><div className="brand">…</div></div>}>
      <RouterProvider router={router} />
    </Suspense>
  </StrictMode>,
);
