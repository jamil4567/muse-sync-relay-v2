# Muse Sync Relay v2

Tiny relay server between Muse and the Android Studio "Muse Sync" plugin.
Muse pushes files here; the plugin polls every 2 seconds and writes them
into the open project. Build/run errors travel the other way: the plugin
posts them here, Muse reads them and pushes fixes.

Based on the v1 relay (github.com/jamil4567/muse-sync-relay), plus a
separate error channel (`POST /error`, `GET /errors`).

## Run locally

```bash
python3 relay_server.py   # listens on $PORT or 8765
```

No dependencies — Python standard library only.

## Deploy (SnapDeploy, free tier, no card)

1. Create a new **public** GitHub repo and push these files
   (`relay_server.py`, `Dockerfile`, `requirements.txt`, `README.md`).
2. On SnapDeploy, sign in with GitHub and deploy from that repo
   (Dockerfile deploy). Note the public URL.
3. Free tier sleeps after ~15 minutes idle — wake it by opening the URL
   (or `GET /health`). A restart wipes stored messages (ephemeral disk).

## Protocol (all JSON)

| Call | Body / query | Returns |
|---|---|---|
| `POST /push` | `{"code", "action": "create"\|"update"\|"delete", "path", "content_b64"}` | `{"ok": true, "id"}` |
| `GET /poll?code=...&since=0` | — | `{"messages": [...], "next": N}` |
| `POST /error` | `{"code", "source": "build"\|"run", "text"}` | `{"ok": true, "id"}` |
| `GET /errors?code=...&since=0` | — | `{"errors": [...], "next": N}` |
| `GET /health` | — | `{"ok": true}` |

- `code` is the secret pairing code (namespace key). Never commit it.
- `path` is relative to the project root; `..` is rejected.
- `content_b64` is base64 file content (empty for `delete`).
- Last 500 messages / 100 error reports are kept per code.

## Clients: set the User-Agent

Some hosts return 403 for Python's default User-Agent. Every client
(Muse's push script, the plugin's HTTP client) must send:

```
User-Agent: Mozilla/5.0
```
