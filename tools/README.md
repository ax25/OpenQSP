# OpenQSP Development Tools

## Purpose

The `tools/` directory contains maintained development and laboratory utilities used to inspect the protocol, emulate clients, reproduce workflows and later simulate constrained transports.

These tools are part of the development strategy of OpenQSP. They are not disposable scripts and must reuse production protocol code wherever possible.

They must not implement a second, independent interpretation of OpenQSP semantics.

---

## 1. Tool progression

The planned tools evolve with the implementation milestones:

```text
Milestone 1
    frame_tool.py
        -> inspect, encode and validate OpenQSP Core frames

Milestone 2
    storage scenarios
        -> exercise deduplication, conflicts, cursors and restart persistence

Milestone 3
    client_sim.py
        -> emulate one OpenQSP user against the local node core

Milestone 4
    scenarios/
        -> reproduce complete multi-user workflows and failures

Milestone 5
    client_sim.py Internet mode
        -> run the same workflows against a remote node

Milestone 6
    aprs_sim.py
        -> encode, fragment, fault-inject and reassemble APRS carriage
```

---

## 2. `frame_tool.py`

`frame_tool.py` is the first laboratory utility and is implemented together with the protocol codec.

It must call the production encoder, decoder and validators from the server protocol package.

Expected capabilities:

```text
frame_tool.py decode <hex-frame>
frame_tool.py validate <hex-frame>
frame_tool.py encode <operation> [fields...]
```

Typical uses:

- inspect a captured or manually constructed Core frame;
- compare an encoded frame with `design/09-protocol-examples.md`;
- generate request and response frames while developing the server;
- identify the validation category of malformed data.

Example concept:

```text
$ frame_tool.py decode "01 02 00 09 00 00 00 00 00 00 00 05 0A"

operation: GET_NEW_MESSAGES
since: 5
max: 10
```

The exact CLI syntax may evolve, but the tool must remain a thin interface over the production codec.

---

## 3. `client_sim.py`

`frame_tool.py` is the protocol/frame laboratory; `client_sim.py` is a logical
client that sends production-encoded frames either directly to `ServerCore` or
to the development TCP server. Each invocation uses an explicit callsign. In
local mode a persistent SQLite node database can be reused to observe restarts;
in remote mode the node owns persistence.

It emulates one explicit OpenQSP user and generates real OpenQSP requests using the production codec.

From the repository root:

```bash
python tools/client_sim.py --db /tmp/openqsp.db --callsign K1ABC \
  send-message --to EA3GNU --id 1001 --timestamp 1786200000 --body "Hello"
python tools/client_sim.py --db /tmp/openqsp.db --callsign EA3GNU \
  get-new-messages --since 0 --max 20
python tools/client_sim.py --db /tmp/openqsp.db --callsign EA3GNU \
  get-new-bulletins --since 0 --max 20
python tools/client_sim.py --db /tmp/openqsp.db --callsign EA3GNU \
  get-bulletin --id 123
```

For explicit remote mode, first run the development node and then address it
with `--tcp-host` (and optionally `--tcp-port`):

```bash
PYTHONPATH=server/src python -m openqsp.server.tcp \
  --host 127.0.0.1 --port 8023 --database /tmp/openqsp-remote.db

python tools/client_sim.py --tcp-host 127.0.0.1 --tcp-port 8023 \
  --callsign EA3GNU get-new-messages --since 0 --max 20
```

Remote mode uses one TCP connection per request, performs the development-only
`CALLSIGN` handshake, reads complete frames from the byte stream, and stops at
the terminal response defined for that request. This handshake is not
production authentication. Bulletin seeding remains local node/test setup and
is deliberately unavailable through TCP.

Version 0.1 has no bulletin-publication wire operation. For laboratory setup,
the explicitly labelled development command below validates and seeds a
bulletin through `BulletinStore`; it is node setup, not a simulated client
request:

```bash
python tools/client_sim.py --db /tmp/openqsp.db --callsign EA9SRC \
  seed-bulletin --id 123 --timestamp 1786200001 \
  --title "Node news" --body "Complete bulletin body"
```

All four client commands construct a production protocol object, call
`encode_frame()`, pass the bytes through the selected transport, and decode the
returned bytes with `decode_frame()`. Local transport calls
`ServerCore.handle_frame()` directly; remote transport moves the same bytes
over TCP. Both transports use the same
`DevelopmentClient` encoding and decoding path.

The simulator must not:

- insert or modify database rows directly;
- supply a forged message author inside `SEND_MESSAGE`;
- bypass the protocol codec;
- depend on APRS-specific logic for ordinary Core operations.

---

## 4. Scenario tools

Repeatable scenarios exercise behaviour across multiple operations or users.

Planned location:

```text
tools/scenarios/
```

Initial scenarios should cover at least:

```text
basic_message
two_users
incremental_sync
empty_mailbox
pagination
node_restart
bulletin_sync
```

The first implemented scenario is the M4.1 multi-user private-message flow.
It sends as `EA3AAA`, retrieves as `EA3BBB`, and also verifies that neither
the sender nor `EA3CCC` can read the recipient's message:

```bash
python tools/scenarios/multi_user_private_message.py /tmp/openqsp-m4.1.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this single-send scenario.

The M4.4 scenario interleaves messages for two mailboxes, synchronizes
`EA3BBB`, and obtains each follow-up cursor from the preceding response's
terminating `END`. It shows that only later messages appear in the second
synchronization and that a third synchronization preserves the cursor while
returning an empty `END`:

```bash
python tools/scenarios/incremental_mailbox_sync.py /tmp/openqsp-m4.4.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this deterministic scenario.

The M4.5 scenario makes empty synchronization an explicit end-to-end
guarantee. It checks both a mailbox queried from `since=0` and a previously
synchronized mailbox queried from its completed `END` cursor. Unrelated
mailbox activity advances the node's global sequence without changing the
empty response's cursor:

```bash
python tools/scenarios/empty_mailbox_sync.py /tmp/openqsp-m4.5.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this deterministic scenario.

The M4.6 scenario stores five messages for `EA3BBB`, with two messages for
other mailboxes interleaved in the global sequence. With a page size of two,
it follows only each response's completed `END.next_since` through two full
pages (`has_more=true`), one partial final page (`has_more=false`), and a
stable empty follow-up:

```bash
python tools/scenarios/mailbox_pagination.py /tmp/openqsp-m4.6.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this deterministic scenario. Its output labels `Page 1`, `Page 2`,
`Final page`, and `Empty follow-up`, and shows every `MESSAGE` sequence plus
the terminating `END` count, cursor, and `has_more` value.

The M4.7 scenario sends a private message, derives a synchronization cursor
from the completed `END`, discards every node and storage object, and rebuilds
the node against the same persistent database file. It then demonstrates
durable retrieval, an empty synchronization from the pre-restart cursor,
sequence continuity for a newly stored message, and unchanged mailbox
isolation:

```bash
python tools/scenarios/node_restart_persistence.py /tmp/openqsp-m4.7.db
```

The M4.8 scenario uses the development-only bulletin seeding path, then
synchronizes public bulletin headers and derives its bulletin cursor from the
terminating response. It retrieves a complete bulletin by the identifier in a
synchronized header, demonstrates incremental and empty synchronization, and
verifies `NOT_FOUND` for a missing bulletin:

```bash
python tools/scenarios/bulletin_sync_retrieval.py /tmp/openqsp-m4.8.db
```

Use a new database path (or remove the previous laboratory database) before
repeating either persistent scenario.

A scenario should clearly report the sequence of logical actions, frames and expected results.

Where practical, scenarios should also be executable from automated tests so that manual laboratory workflows and CI verification exercise the same code paths.

---

## 5. `aprs_sim.py`

`aprs_sim.py` is deferred until the OpenQSP APRS transport profile has been specified.

It will simulate carriage of complete OpenQSP Core frames over APRS without requiring APRS-IS or RF.

Its responsibilities are expected to include:

- text-safe APRS encoding;
- fragmentation of one Core frame;
- reassembly back into the identical Core frame;
- message and fragment correlation;
- APRS-level acknowledgement simulation;
- controlled fault injection.

Fault modes should include at least:

```text
drop fragment
duplicate fragment
reorder fragments
delay fragment
lose acknowledgement
```

A central invariant is:

```text
Core frame -> APRS simulation -> reassembled Core frame
```

must preserve the original Core-frame bytes exactly when transport succeeds.

The APRS simulator must test the transport profile, not redefine message, bulletin, synchronization or storage semantics.

---

## 6. Separation from automated tests

The project uses both automated tests and laboratory tools.

Automated tests answer questions such as:

- does this function produce the required bytes?;
- does the storage layer reject a conflict?;
- does a restart preserve the cursor state?

Laboratory tools answer questions such as:

- what exactly does this frame contain?;
- what happens when EA3GNU sends a message to EA1ABC?;
- what frames are exchanged during synchronization?;
- what happens if an acknowledgement or APRS fragment is lost?

The two layers should share production code and canonical fixtures rather than duplicate implementations.

---

## 7. Current status

The protocol laboratory, local logical client, and first multi-user scenario
are available:

```text
tools/frame_tool.py
tools/client_sim.py
tools/scenarios/multi_user_private_message.py
```

They use the production protocol codec directly; the client simulator also
uses the production server core and persistent stores without a network.
