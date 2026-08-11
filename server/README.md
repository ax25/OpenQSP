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

The runtime optionally reads simple `KEY=VALUE` entries from `.env` in the
working directory. Existing environment variables take precedence. Copy
`.env.example` and replace its APRS placeholders; `.env` is git-ignored.

## TCP only

```bash
OPENQSP_TCP_ENABLED=true \
OPENQSP_APRS_ENABLED=false \
openqsp-server
```

Defaults are database `openqsp.db`, TCP `127.0.0.1:8023`, and APRS disabled.
`--database`, `--host`, and `--port` override environment values.

## APRS-IS only

Put your operator-supplied credentials in `.env` (never commit this file):

```env
OPENQSP_TCP_ENABLED=false
OPENQSP_APRS_ENABLED=true
OPENQSP_APRS_CALLSIGN=OPENQSP
OPENQSP_APRS_PASSCODE=...
OPENQSP_APRS_HOST=rotate.aprs2.net
OPENQSP_APRS_PORT=14580
OPENQSP_APRS_FILTER=g/OPENQSP
```

Then run `openqsp-server`. If `OPENQSP_APRS_FILTER` is omitted, the runtime
uses `g/<OPENQSP_APRS_CALLSIGN>`. It reconnects automatically after link loss.

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
