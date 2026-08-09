# M7 live APRS-IS acceptance — 2026-08-09

This record closes the live APRS-IS acceptance boundary for Milestone 7. Tests were run against the production APRS carriage/adapter code and a persistent SQLite node database. RF/IGate field validation remains a later activity.

## Results

| Test | Result | Evidence |
| --- | --- | --- |
| 1. OPENQSP verified APRS-IS login | PASS | `# logresp OPENQSP verified` observed on live Tier-2 infrastructure. |
| 2. `GET_CAPABILITIES` end-to-end | PASS | EA3GNU request ACKed; decoded response `Capabilities(protocol_version=1, capabilities=15)`; response ACK returned. |
| 3. Fragmented `SEND_MESSAGE` + `STORED` | PASS | Maximum-length 208-character body generated 7 APRS fragments; all 7 native ACKs received; Core reassembled and persisted the request; `STORED` returned and ACKed. |
| 4. Persistence after node restart | PASS | Node restarted against the same SQLite database; EA3ABC executed `GET_NEW_MESSAGES`; the Test-3 message was recovered in 7 response fragments followed by `END`; all response fragments ACKed. |
| 5. Proactive delivery | PASS | EA3ABC was made ACTIVE, then EA3GNU sent a new private message; EA3ABC received a 2-fragment unsolicited `MESSAGE` without issuing a subsequent `GET_NEW_MESSAGES`; UNSOLICITED semantics validated. |
| 6. APRS-IS disconnect/reconnect | PASS | A local fault proxy forcibly dropped the live upstream TCP connection while the OPENQSP process remained alive; `APRSISClient` automatically reconnected and a post-reconnect `GET_CAPABILITIES` succeeded. |
| 7A. Deliberate cross-server `GET_CAPABILITIES` | PASS | EA3GNU verified on T2UK; OPENQSP verified on T2RADOM; request ACK and Q1 response crossed the APRS-IS backbone successfully. |
| 7B. Deliberate cross-server `SEND_MESSAGE` + `STORED` | PASS | With EA3GNU on T2UK and OPENQSP on T2RADOM, request fragments were ACKed and the durable `STORED` response returned successfully across servers. |

## Notable observations

During the laboratory session one earlier APRS-IS service connection stopped receiving addressed traffic until the OPENQSP process was restarted. A controlled disconnect/reconnect test could not reproduce a reconnect-loop defect: forced socket loss was detected, automatic reconnection occurred, and the service handled subsequent requests correctly. This observation is therefore retained as a non-blocking field note rather than an M7 acceptance failure.

## Acceptance conclusion

M7 live APRS-IS acceptance is complete. The accepted path demonstrates:

- verified APRS-IS service operation;
- unchanged Core-frame carriage over APRS text messages;
- bounded fragmentation/reassembly and native APRS fragment ACK handling;
- durable `SEND_MESSAGE` storage and retrieval across node restart;
- ACTIVE-state proactive delivery;
- automatic service reconnection after TCP loss;
- deliberate Tier-2 cross-server request/response propagation.

Milestone 7 may be marked complete. RF/IGate tests can be performed later as field validation without reopening the software milestone unless they expose a protocol or implementation defect.
