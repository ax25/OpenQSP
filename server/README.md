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
