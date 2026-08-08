# OpenQSP Core protocol 0.1

Every frame is `version:u8, operation:u8, flags:u8, payload_length:u8, payload`.
All integers use network byte order. Synchronization cursors and sequences are
unsigned 32-bit values; zero means that the client has no prior cursor.

## Operations and exact payloads

| Code | Operation | Payload |
|---|---|---|
| `01` | `SEND_MESSAGE` | `created_at:u32, recipient_len:u8, recipient, body_len:u8, body` |
| `02` | `GET_NEW_MESSAGES` | `since:u32, max:u8` |
| `03` | `GET_NEW_BULLETINS` | `since:u32, max:u8` |
| `04` | `GET_BULLETIN` | `sequence:u32` |
| `40` | `MESSAGE` | `sequence:u32, created_at:u32, author_len:u8, author, recipient_len:u8, recipient, body_len:u8, body` |
| `41` | `BULLETIN_HEADER` | `sequence:u32, created_at:u32, author_len:u8, author, title_len:u8, title` |
| `42` | `BULLETIN` | `sequence:u32, created_at:u32, author_len:u8, author, title_len:u8, title, body_len:u8, body` |
| `43` | `END` | `request_operation:u8, returned_count:u8, next_since:u32, has_more:u8` |
| `44` | `STORED` | empty |
| `45` | `ERROR` | `request_operation:u8, error_code:u8, detail_len:u8, detail` |

Sequences in objects are nonzero. `SEND_MESSAGE` has no author field: the node
uses authenticated session context. `STORED` means the storage transaction has
committed durably and carries no identifier. Failures use `ERROR`.

`GET_NEW_MESSAGES` returns only the authenticated recipient's messages whose
mailbox-local sequence is greater than `since`, followed by `END`. A cursor
ahead of that mailbox is `INVALID_CURSOR`. Bulletin sequences are node-local
and are both synchronization positions and bulletin references.

Flag `0x01` is `UNSOLICITED`. It is valid only on proactive node-originated
`MESSAGE` and `BULLETIN_HEADER` frames, allowing clients to separate events from
items belonging to an active request.

Compared with the previous development codec, `SEND_MESSAGE` saves 8 payload
bytes; each `MESSAGE` saves 12 (removed ID plus u64-to-u32 sequence); each
bulletin header saves 12; `BULLETIN` saves 4; retrieval requests save 4;
`GET_BULLETIN` saves 4; `END` saves 4; and successful storage responses save 9.
