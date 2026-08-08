# Protocol examples

For `SEND_MESSAGE(created_at=1, recipient=EA3GNU, body=hello)`:

```text
01 01 00 11  00 00 00 01  06 45 41 33 47 4e 55  05 68 65 6c 6c 6f
```

A committed transaction returns zero-payload `STORED`:

```text
01 44 00 00
```

`GET_NEW_MESSAGES(since=0,max=20)`:

```text
01 02 00 05  00 00 00 00 14
```

`GET_BULLETIN(sequence=3)`:

```text
01 04 00 04  00 00 00 03
```

`END(GET_NEW_MESSAGES,count=2,next_since=2,has_more=false)`:

```text
01 43 00 07  02 02 00 00 00 02 00
```
