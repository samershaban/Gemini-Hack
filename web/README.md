# Poker Face: web (Part B, the show)

Vite + React + TypeScript. `/stage` runs on the laptop/projector, `/play` on phones.

```sh
npm install
npm run dev            # uses src/mock.ts (fake Part A with realistic delays)
npm run dev:brain      # everything goes to Part A (brain branch) at http://localhost:8000 (API_TARGET to override)
VITE_REAL=rounds,clips npm run dev  # mix: listed endpoints real, the rest mocked
npm run build          # production build: the mock is compiled out and can never run in the demo
```

- `src/contract.ts`: the Part A/B contract types (assumptions about indexing are noted at the top)
- `src/api.ts`: the real client; `getApi()` picks the mock only in dev
- `src/mock.ts`: dev-only fake server; the WebSocket is faked over BroadcastChannel so `/stage` and `/play` tabs in one browser talk
- `src/lib/media.ts`: camera hook, one-tap clip recorder (`MediaRecorder`), still-frame grab, host voice
- `src/eye/EyeScene.ts`: Ogle, the Eye (Babylon.js, original mascot drawn in code: no external assets)

**Phones join by scanning the QR code on the stage** (`src/components/JoinQr.tsx`). The QR code points at the stage's own address, so phones must be able to reach it:

- Easiest: run `cloudflared tunnel --url http://localhost:5173` and open `/stage` through the `https://…trycloudflare.com` link.
- Or keep the stage on `localhost` and run `VITE_PUBLIC_URL=https://xxx.trycloudflare.com npm run dev:brain`.
- Don't open the stage on a plain `http://` LAN IP: the browser blocks the camera there. On `localhost` without `VITE_PUBLIC_URL`, the QR card shows a warning.

Dev poking: `/stage?mood=busted&sus=0.9`, or `ogle.setMood('dizzy')` in the console.
Moods: `idle`, `thinking`, `squint`, `busted`, `dizzy`, `smug`.
