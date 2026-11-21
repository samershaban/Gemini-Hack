# Poker Face: web (Part B, the show)

Vite + React + TypeScript. `/stage` runs on the laptop/projector, `/play` on phones.

```sh
npm install
npm run dev            # uses src/mock.ts (fake Part A with realistic delays)
VITE_MOCK=0 npm run dev  # proxies /rounds, /frames, /ws to Part A at http://localhost:8000 (API_TARGET to override)
npm run build          # production build: the mock is compiled out and can never run in the demo
```

- `src/contract.ts`: the Part A/B contract types (assumptions about indexing are noted at the top)
- `src/api.ts`: the real client; `getApi()` picks the mock only in dev
- `src/mock.ts`: dev-only fake server; the WebSocket is faked over BroadcastChannel so `/stage` and `/play` tabs in one browser talk
- `src/lib/media.ts`: camera hook, one-tap clip recorder (`MediaRecorder`), still-frame grab, host voice
- `src/eye/EyeScene.ts`: Ogle, the Eye (Babylon.js, original mascot drawn in code: no external assets)

Dev poking: `/stage?mood=busted&sus=0.9`, or `ogle.setMood('dizzy')` in the console.
Moods: `idle`, `thinking`, `squint`, `busted`, `dizzy`, `smug`.
