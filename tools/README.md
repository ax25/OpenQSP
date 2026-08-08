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

`frame_tool.py` is the protocol/frame laboratory; `client_sim.py` is a local
logical client that sends production-encoded frames to `ServerCore`. It is not
a network client and opens no listener or connection. Each invocation uses the
explicit callsign as authenticated context and a persistent SQLite node
database, so the same file can be reused to observe restarts.

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
`encode_frame()`, pass the bytes to `ServerCore.handle_frame()`, and decode the
returned bytes with `decode_frame()`. A future milestone may add transport
modes to the same simulator without changing these user-level operations.

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
lost_ack_retry
conflicting_object_id
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

The M4.2 scenario processes a message normally, intentionally ignores the
first `STORED` acknowledgement, and submits the exact same `SendMessage`
again. It then synchronizes the recipient mailbox twice to demonstrate that
the retry returns `ALREADY_STORED`, creates no duplicate, and consumes no new
sequence:

```bash
python tools/scenarios/message_retry_after_lost_ack.py /tmp/openqsp-m4.2.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this scenario.

The M4.3 scenario stores one message, then submits the same object identifier,
authenticated sender, recipient, and timestamp with only the body changed. It
expects the existing `CONFLICT` acknowledgement and synchronizes twice to show
that the original body and sequence remain intact, with no duplicate or new
sequence:

```bash
python tools/scenarios/message_id_conflict.py /tmp/openqsp-m4.3.db
```

Use a new database path (or remove the previous laboratory database) before
repeating this scenario.

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
tools/scenarios/message_retry_after_lost_ack.py
tools/scenarios/message_id_conflict.py
```

They use the production protocol codec directly; the client simulator also
uses the production server core and persistent stores without a network.
