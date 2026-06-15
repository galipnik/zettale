# Zettale — Personal Task PWA

Single-user todo PWA. Browser + Android (installable), self-hosted.
Quick capture, assignment via `@context`, overview grouped by context.
Tasks and thoughts, English/German UI (default English).

```
todo-pwa/
├── backend/        FastAPI + SQLite (the API)
│   ├── main.py
│   └── requirements.txt
└── frontend/       Static PWA (index.html + sw.js + manifest + fonts + icons)
```

---

## 1. Run the backend locally (for testing)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TODO_TOKEN="$(openssl rand -hex 24)"   # keep it!
export TODO_ORIGINS="http://localhost:8012"   # your frontend URL
uvicorn main:app --port 8001
```

Endpoints: `GET /tasks`, `POST /tasks`, `PATCH /tasks/{id}`,
`DELETE /tasks/{id}`, `GET /thoughts`, `POST /thoughts`,
`PATCH /thoughts/{id}/archive`, `DELETE /thoughts/{id}`,
`GET /export` (todo.txt), `GET /health`.
Everything except `/health` requires the header `Authorization: Bearer <TOKEN>`.

## 2. Run the frontend locally

```bash
cd frontend
python3 -m http.server 8012
```

Open `http://localhost:8012` → on first launch enter the API URL
(`http://localhost:8001`) and token. Stored only in the browser
(localStorage), never in code.

---

## 3. Deploy to your server (Apache + reverse proxy)

### Backend as a systemd service

`/etc/systemd/system/todo-api.service`:

```ini
[Unit]
Description=Zettale API
After=network.target

[Service]
WorkingDirectory=/opt/todo/backend
Environment="TODO_TOKEN=YOUR_SECRET_TOKEN"
Environment="TODO_DB=/opt/todo/data/todo.db"
Environment="TODO_ORIGINS=https://todo.yourserver.com"
ExecStart=/opt/todo/backend/.venv/bin/uvicorn main:app --host 127.0.0.1 --port 8001
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable --now todo-api
```

### Apache vhost

```apache
<VirtualHost *:443>
    ServerName todo.yourserver.com

    # Frontend (static)
    DocumentRoot /opt/todo/frontend

    # API under /api → FastAPI on 127.0.0.1:8001
    ProxyPass        /api/  http://127.0.0.1:8001/
    ProxyPassReverse /api/  http://127.0.0.1:8001/

    SSLEngine on
    # ... your existing cert lines (Let's Encrypt) ...
</VirtualHost>
```

Modules: `sudo a2enmod proxy proxy_http ssl headers`

In the frontend setup, enter the API URL as `https://todo.yourserver.com/api`
(without a trailing slash).

> **HTTPS is required** for PWA installation + service worker — covered by
> your existing certificate.

---

## 4. Install on Android

1. Open `https://todo.yourserver.com` in Chrome
2. Menu → "Add to Home screen"
3. Launches like a native app afterwards (own window, offline-capable)

Tasks captured offline are queued locally and synced automatically once
back online.

---

## Notes

- **Language**: English by default; switch to German in Settings → Language.
  The choice is stored in the browser.
- **Due dates**: tasks store an ISO date (`YYYY-MM-DD`). Quick tokens
  `!today`/`!heute`, `!week`/`!woche`, or a date picker (`!2026-07-01`).
  Lists are sorted by due date, then by creation date (oldest first).
- **Categories**: editable in Settings; one can be marked as the default
  (★) — used when no `@context` is given and as the preselected filter.

## Extendable later (without a rewrite)

- **Multi-user (read-only viewer):** `users` table + `owner_id` on `tasks`,
  static token → per-user token. Endpoints stay the same.
- **Recurring tasks:** `rec` field + cron job or lazy re-create on check-off.
