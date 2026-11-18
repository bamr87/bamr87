<!-- changelog.d/conformance-be-server-rendered.md -->
### Fixed

- `tools/conformance.py` 0.3.3: UPS-BE-10 (/healthz, /readyz) and UPS-BE-11 (/version) apply their `app (server-rendered)` qualifier from specs/BACKEND.md. An `app` repo with no server side (a browser-only SPA, a game, firmware, a mobile client) now passes both as N/A instead of failing two MUST rows it cannot meet. Kind `api`, a `manage.py`, `config.ru`, `Dockerfile`, `Procfile` or wrangler config, a server framework dependency (Django, FastAPI, Flask, Express, Next, Hono and others) or code that serves HTTP itself (a `BaseHTTPRequestHandler` subclass, an asyncio or wsgiref server, Go's net/http) keeps them checked as before. No spec row changed.
