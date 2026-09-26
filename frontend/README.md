# PackSure AI frontend

This React + Vite application provides the inspector and administrator interfaces for PackSure AI.

- Development: `npm run dev`
- Lint: `npm run lint`
- Production build: `npm run build`

The development API defaults to `http://127.0.0.1:8000`. Set `VITE_API_BASE_URL` when another API base is required. The production container builds with `/api` and nginx proxies that path to the backend service.

Authentication tokens use browser `localStorage` for this SIH prototype. A hardened public deployment should move authentication to secure, HttpOnly cookies or a server-managed session.
