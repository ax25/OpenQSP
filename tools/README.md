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

`client_sim.py` is introduced when the minimum server core exists.

It emulates one explicit OpenQSP user and generates real OpenQSP requests using the production codec.

Expected operations include conceptually:

```text
client_sim.py --user EA3GNU send EA1ABC "Hola"
client_sim.py --user EA1ABC messages
client_sim.py --user EA1ABC bulletins
client_sim.py --user EA1ABC bulletin <id>
```

In local development mode it may call the node-core interface directly. Later it should gain an Internet transport mode without changing the user-level commands.

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

No development tool is implemented yet.

The first implementation target is:

```text
tools/frame_tool.py
```

It will be created as part of Milestone 1 immediately after the protocol package exposes a working encoder and decoder.
