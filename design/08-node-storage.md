# Node storage

Schema version 2 stores private messages as `recipient, mailbox_sequence,
author, created_at, accepted_at, body`, with
`PRIMARY KEY(recipient, mailbox_sequence)`. `mailbox_sequences` persists each
recipient's highest u32 value. `BEGIN IMMEDIATE`, allocation, insertion, state
update, and commit form one transaction, so concurrent writers cannot allocate
the same value and an uncommitted sequence is never visible.

Bulletins use `sequence INTEGER PRIMARY KEY` and a singleton persistent u32
high-water mark. No global object table or content hashes remain.

## Migration from development schema 1

Migration 2 is explicit and atomic. It renames the old tables, creates the new
schema, and copies all content. Messages receive `ROW_NUMBER()` independently
per recipient, ordered deterministically by old sequence then old message ID.
Bulletins receive a single sequence ordered by old sequence then old bulletin
ID. It initializes high-water marks from migrated rows and only then drops old
objects, hashes, IDs, and global sequence state. Old numeric identities are not
preserved because they have no meaning in the corrected model; content,
authors, recipients, timestamps, titles, bodies, and relative ordering are.
