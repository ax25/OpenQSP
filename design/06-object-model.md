# Object model

OpenQSP separates persistent application objects, synchronization cursors, and
transport reliability identifiers.

A private Message is `(sequence:u32, created_at, author, recipient, body)`.
Its identity is scoped to the recipient mailbox: `(recipient, sequence)`.
Different mailboxes can each contain sequence 17. The node assigns the sequence
only inside the durable insert transaction.

A Bulletin is `(sequence:u32, created_at, author, title, body)`. Its node-local
sequence is its sole identifier. A Bulletin Header omits only the body.

Cursors are positions in those streams, not object IDs. Transport transaction
IDs are envelope metadata owned by unreliable adapters and are not persistent
application object fields.
