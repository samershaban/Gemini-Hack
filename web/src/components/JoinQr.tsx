import QRCode from 'qrcode';
import { useEffect, useState } from 'react';

// The address phones can reach. On localhost that's nobody, so set VITE_PUBLIC_URL to the
// tunnel URL, or just open /stage through the tunnel and location.origin is already right.
const PUBLIC_URL = (import.meta.env.VITE_PUBLIC_URL as string | undefined)?.replace(/\/$/, '');
const LOCAL_HOSTS = ['localhost', '127.0.0.1', '[::1]'];

/** Big "scan to play" QR code. Drawn in the browser, so it works without venue internet. */
export function JoinQr({ room, big }: { room: string; big: boolean }) {
  const origin = PUBLIC_URL ?? location.origin;
  const joinUrl = `${origin}/play?room=${room}`;
  const phonesCantReachIt = !PUBLIC_URL && LOCAL_HOSTS.includes(location.hostname);
  const [svg, setSvg] = useState('');

  useEffect(() => {
    let live = true;
    QRCode.toString(joinUrl, {
      type: 'svg',
      margin: 2,
      errorCorrectionLevel: 'M',
      color: { dark: '#111111', light: '#ffffff' },
    }).then((markup) => {
      if (live) setSvg(markup);
    });
    return () => {
      live = false;
    };
  }, [joinUrl]);

  return (
    <div className={`join-qr ${big ? 'lobby' : ''}`}>
      <div className="join-qr-tag">SCAN TO PLAY</div>
      <div className="join-qr-code" dangerouslySetInnerHTML={{ __html: svg }} />
      <div className="join-qr-room">
        ROOM <b>{room}</b>
      </div>
      <div className="join-qr-url">{joinUrl.replace(/^https?:\/\//, '')}</div>
      {phonesCantReachIt && <div className="join-qr-warn">Phones can't reach localhost: open this stage through the tunnel link.</div>}
    </div>
  );
}
