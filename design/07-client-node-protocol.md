# Client/node behavior

`SEND_MESSAGE(created_at, recipient, body)` derives the author exclusively from
the authenticated session. After validation the node atomically allocates the
recipient's next mailbox sequence, inserts the message, commits, then responds
with zero-payload `STORED`. Any failure is `ERROR`; clients must not manufacture
an application ID for retry.

`GET_NEW_MESSAGES(since, max)` reads only the authenticated mailbox. Responses
are `MESSAGE* END`, ascending by mailbox sequence. `since=0` starts at the
beginning and `END.next_since` is the next cursor.

`GET_NEW_BULLETINS` similarly returns node-local `BULLETIN_HEADER` sequences.
`GET_BULLETIN(sequence)` retrieves the full bulletin by the same sequence.
Proactive messages and headers retain the `UNSOLICITED` flag even while another
request is active.
