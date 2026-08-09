# Protocol

This directory will contain the OpenQSP protocol specification and related documentation.

M6 adds authenticated capability discovery through canonical `GET_CAPABILITIES` (`01 05 00 00`) and `CAPABILITIES` (`01 46 00 05 01 00 00 00 0F`) frames. Proactive private messages reuse `MESSAGE` with the `UNSOLICITED` header flag; they never participate in request completion.
