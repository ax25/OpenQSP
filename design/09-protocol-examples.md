# Protocol examples

## Purpose

These canonical vectors use hexadecimal octets, network byte order, and the
four-byte Core header `version operation flags payload_length`. They are
normative examples for codec and integration tests.

## 1. Common values

| Field | Value |
|---|---|
| created time | `0x65000000` |
| sender | `EA1ABC` |
| recipient | `EA3GNU` |
| body | `Hola` |
| mailbox sequence | `1` |
| bulletin sequence | `3` |

## 2. SEND_MESSAGE

Fields are `created_at:u32`, length-prefixed recipient, and length-prefixed
body. No client retry or object identifier is present.

```text
01 01 00 10
65 00 00 00
06 45 41 31 41 42 43
04 48 6F 6C 61
```

Payload size is 16 bytes, eight fewer than the former development layout.
After the transaction commits durably the response is:

```text
01 44 00 00
```

`STORED` has no payload. Failures use `ERROR`.

## 3. GET_NEW_MESSAGES

`since=124`, `max=5`:

```text
01 02 00 05 00 00 00 7C 05
```

The authenticated mailbox determines the stream. Another mailbox may have the
same sequence values without collision.

## 4. MESSAGE

Sequence 1, timestamp 2, author `EA1ABC`, recipient `EA3GNU`, body `x`:

```text
01 40 00 18
00 00 00 01 00 00 00 02
06 45 41 31 41 42 43
06 45 41 33 47 4E 55
01 78
```

The 24-byte payload is twelve bytes smaller than the former layout: eight bytes
of redundant identifier and four bytes from narrowing the sequence were removed.

## 5. END for messages

One result, `next_since=125`, no additional page:

```text
01 43 00 07 02 01 00 00 00 7D 00
```

An empty result repeats the request cursor and has returned count zero.

## 6. GET_NEW_BULLETINS

```text
01 03 00 05 00 00 00 00 14
```

This requests at most 20 headers from the beginning of the node-local stream.

## 7. BULLETIN_HEADER

Sequence 1, timestamp 2, author `EA1ABC`, title `t`:

```text
01 41 00 11
00 00 00 01 00 00 00 02
06 45 41 31 41 42 43
01 74
```

## 8. GET_BULLETIN

Bulletin sequence 3:

```text
01 04 00 04 00 00 00 03
```

The payload is four bytes. The same sequence appears in its header and full
object and is the bulletin's sole reference.

## 9. BULLETIN

Sequence 1, timestamp 2, author `EA1ABC`, title `t`, body `b`:

```text
01 42 00 13
00 00 00 01 00 00 00 02
06 45 41 31 41 42 43
01 74 01 62
```

## 10. ERROR / NOT_FOUND

A missing bulletin may produce:

```text
01 45 00 15
04 07 12 62 75 6C 6C 65 74 69 6E 20 6E 6F 74 20 66 6F 75 6E 64
```

This is `request_operation=GET_BULLETIN`, `error_code=NOT_FOUND`, followed by a
length-prefixed detail.

## 11. Pagination

A client starts with cursor zero. If the node returns sequences 1 and 2 with
`has_more=1`, the client requests again with `since=2`. Only after receiving a
valid terminal `END` does it persist `next_since`. An unsolicited item does not
belong to the page and does not affect that cursor.

## 12. Invalid vectors

### Unsupported version

```text
02 04 00 04 00 00 00 03
```

Result: `ERROR / UNSUPPORTED_VERSION` when a response is possible.

### Non-zero unsupported flag

```text
01 04 80 04 00 00 00 03
```

Result: invalid frame. Flag `0x01` is accepted only for node-originated
`MESSAGE` and `BULLETIN_HEADER` by the server-frame decoder.

### Truncated bulletin request

```text
01 04 00 03 00 00 00
```

Result: invalid payload length; `GET_BULLETIN` requires exactly four bytes.

### Retrieval max zero

```text
01 02 00 05 00 00 00 00 00
```

Result: `ERROR / INVALID_FIELD` because max is 1 through 20.

### Empty message body

```text
01 01 00 0B 65 00 00 00 06 45 41 33 47 4E 55 00
```

Result: `ERROR / INVALID_FIELD`.

### Invalid recipient or UTF-8

Recipients that violate canonical callsign rules and malformed UTF-8 in any
text field produce `ERROR / INVALID_FIELD`. A declared payload size that does
not match the complete frame produces `ERROR / INVALID_FRAME`.

## 13. Required implementation checks

Implementations must round-trip every valid vector; reject truncated, trailing,
oversized, wrong-version, unknown-operation, invalid-flag, invalid-callsign,
invalid-UTF-8, out-of-range u32, and invalid boolean inputs; enforce mailbox
privacy and cursor scope; and preserve `UNSOLICITED` during request interleaving.
