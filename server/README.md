# OpenQSP server

The production runtime creates one SQLite-backed `ServerCore` and shares it
between every enabled transport. TCP and APRS-IS can therefore operate at the
same time without separate message, bulletin, or account state.

## Development install

```bash
cd server
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Use `pip install -e '.[test]'` when developing or running the complete suite.

## Internet API v1

The FastAPI Internet adapter shares the same SQLite database, account store and
message domain operation as TCP/APRS. Every transport calls `ServerCore.send_message`,
which validates, persists, allocates sequences, and publishes the single
post-commit event consumed by WebSocket clients. Enable it with a private signing
secret:

```bash
cd server
OPENQSP_API_ENABLED=true \
OPENQSP_API_TOKEN_SECRET='replace-with-a-long-random-production-secret' \
OPENQSP_TCP_ENABLED=false \
OPENQSP_APRS_ENABLED=false \
openqsp-server
```

Optional settings are `OPENQSP_API_HOST` (default `127.0.0.1`),
`OPENQSP_API_PORT` (default `8000`), `OPENQSP_API_TOKEN_LIFETIME` in seconds
(default `3600`), and comma-separated `OPENQSP_API_CORS_ORIGINS`. CORS is off
unless origins are explicitly configured; for local Flutter web development,
for example, set `OPENQSP_API_CORS_ORIGINS=http://localhost:3000`.

The safe development bind remains `127.0.0.1`. In the production reverse-proxy
topology, Apache terminates HTTPS/WSS and proxies ordinary HTTP/WebSocket traffic
to OpenQSP; OpenQSP itself does not need TLS configuration. If the proxy and API
run on different machines, set `OPENQSP_API_HOST` to the API server's LAN address,
or to `0.0.0.0` with an appropriate host firewall. The external URLs can remain
`https://openqsp.ddns.net/api/v1/...` and
`wss://openqsp.ddns.net/api/v1/ws` while the internal hop uses `http://`/`ws://`.

Provision accounts with `openqsp-server --create-account` as described below.
Interactive Swagger documentation is at <http://127.0.0.1:8000/docs> and the
schema at <http://127.0.0.1:8000/openapi.json>.

Login and send a message:

```bash
TOKEN=$(curl -s http://127.0.0.1:8000/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"callsign":"EA3GNU","password":"choose-a-password"}' |
  python -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')

curl -s http://127.0.0.1:8000/api/v1/messages \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Idempotency-Key: flutter-send-1' \
  -d '{"to":"EA3ABC","body":"Radio test"}'
```

Clients first call `GET /api/v1/sync`, persist its opaque cursor, and supply it
on later `GET /api/v1/sync?cursor=...` calls. Connect to
`ws://127.0.0.1:8000/api/v1/ws?token=<access-token>` for low-latency
`message.created` events. After every WebSocket disconnect, reconnect and run
sync with the last stored cursor; HTTP sync, not the socket, is the source of
truth. Access tokens expire and clients then log in again.

Run Internet API tests with `python -m pytest -q tests/api`; run all tests with
`python -m pytest -q tests`.

The runtime optionally reads simple `KEY=VALUE` entries from `.env` in the
working directory. Existing environment variables take precedence. Copy
`.env.example` and replace any environment-specific values; `.env` is
git-ignored.

## TCP only

```bash
OPENQSP_TCP_ENABLED=true \
OPENQSP_APRS_ENABLED=false \
openqsp-server
```

Defaults are database `openqsp.db`, TCP `127.0.0.1:8023`, and APRS disabled.
`--database`, `--host`, and `--port` override environment values.

## APRS identity

`OpenQSP` is the project and service name, but the APRS/AX.25 station identity
is **`OQSP`**.

Do not use `OPENQSP` as the APRS-IS login or packet source. AX.25 source
callsigns are limited to six characters, while `OPENQSP` has seven. During
real RF testing, APRS-IS accepted packets sourced from `OPENQSP`, but an
Internet-to-RF IGate could not retransmit that source as a valid AX.25 station.
Using `OQSP` allows the same identity to be used coherently for the APRS-IS
login, incoming message addressee, ACK source, and outbound OpenQSP packets.

The expected APRS flow is therefore:

```text
EA3GNU-5 -> OQSP      : message{1
OQSP     -> EA3GNU-5 : ack1
```

## APRS-IS only

Use the OpenQSP APRS service identity in `.env`:

```env
OPENQSP_TCP_ENABLED=false
OPENQSP_APRS_ENABLED=true
OPENQSP_APRS_CALLSIGN=OQSP
OPENQSP_APRS_PASSCODE=28643
OPENQSP_APRS_HOST=rotate.aprs2.net
OPENQSP_APRS_PORT=14580
OPENQSP_APRS_FILTER=g/OQSP
```

`28643` is the APRS-IS passcode corresponding to the `OQSP` service identity.
If `OPENQSP_APRS_FILTER` is omitted, the runtime automatically uses
`g/<OPENQSP_APRS_CALLSIGN>`, which is `g/OQSP` with this configuration.
The APRS-IS connection reconnects automatically after link loss.

A successful startup should include lines similar to:

```text
APRS-IS: connecting to rotate.aprs2.net:14580 as OQSP
APRS-IS: connected and verified
```

APRS clients and radios should address OpenQSP messages to `OQSP`, not
`OPENQSP`.

## TCP and APRS-IS

Set both `OPENQSP_TCP_ENABLED=true` and `OPENQSP_APRS_ENABLED=true`. Both
adapters share the same Core and configured `OPENQSP_DATABASE`.

## Account creation

Provision TCP credentials against the configured database and exit:

```bash
openqsp-server --create-account EA3GNU 'choose-a-password'
```

For a real APRS-IS smoke test, fill `.env`, then run exactly:

```bash
cd ~/Documents/OpenQSP/server
source .venv/bin/activate
openqsp-server
```

Then send a normal APRS message by RF to `OQSP`. With an APRS message ID, a
successful round trip should produce a server receive log followed by an ACK
sent back to the originating station.
