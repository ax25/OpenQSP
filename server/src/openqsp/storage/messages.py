"""Atomic recipient-local mailbox storage."""
from __future__ import annotations
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from ._common import MAX_SQLITE_INTEGER, MAX_U32, InvalidCursorError, SequenceExhaustedError, StorageIntegrityError, StoreOutcome, StoreResult, require_u32
from .database import Database
MAX_RETRIEVAL_LIMIT=20
@dataclass(frozen=True)
class StoredMessage:
    sequence:int; created_at:int; author:str; recipient:str; body:str
@dataclass(frozen=True)
class MessagePage:
    messages:tuple[StoredMessage,...]; next_since:int; has_more:bool
class MessageStore:
    def __init__(self,database:Database,*,clock:Callable[[],int]|None=None): self._database=database; self._clock=clock or (lambda:int(time.time()))
    def store_message(self,*,created_at:int,author:str,recipient:str,body:str)->StoreOutcome:
        require_u32('created_at',created_at)
        if not all(isinstance(x,str) for x in (author,recipient,body)): raise TypeError('message text fields must be strings')
        with closing(self._database.connect()) as c:
            c.execute('BEGIN IMMEDIATE')
            try:
                row=c.execute('SELECT last_value FROM mailbox_sequences WHERE recipient=?',(recipient,)).fetchone()
                last=0 if row is None else int(row['last_value'])
                if last==MAX_U32: raise SequenceExhaustedError('mailbox sequence is exhausted')
                seq=last+1; accepted=self._clock()
                if not isinstance(accepted,int) or isinstance(accepted,bool) or not 0<=accepted<=MAX_SQLITE_INTEGER: raise ValueError('clock returned invalid value')
                c.execute('INSERT INTO messages(recipient,mailbox_sequence,author,created_at,accepted_at,body) VALUES(?,?,?,?,?,?)',(recipient,seq,author,created_at,accepted,body.encode()))
                c.execute('INSERT INTO mailbox_sequences(recipient,last_value) VALUES(?,?) ON CONFLICT(recipient) DO UPDATE SET last_value=excluded.last_value',(recipient,seq)); c.commit()
                return StoreOutcome(StoreResult.STORED,seq)
            except BaseException: c.rollback(); raise
    def get_new_messages(self,*,callsign:str,since:int,limit:int)->MessagePage:
        require_u32('since',since)
        if not 1<=limit<=MAX_RETRIEVAL_LIMIT: raise ValueError('invalid limit')
        with closing(self._database.connect()) as c:
            c.execute('BEGIN')
            try:
                row=c.execute('SELECT last_value FROM mailbox_sequences WHERE recipient=?',(callsign,)).fetchone(); highest=0 if row is None else int(row['last_value'])
                if since>highest: raise InvalidCursorError('message cursor is ahead of mailbox')
                rows=c.execute('SELECT mailbox_sequence,created_at,author,recipient,body FROM messages WHERE recipient=? AND mailbox_sequence>? ORDER BY mailbox_sequence LIMIT ?',(callsign,since,limit+1)).fetchall(); c.commit()
            except BaseException:c.rollback();raise
        msgs=tuple(StoredMessage(int(r[0]),int(r[1]),str(r[2]),str(r[3]),bytes(r[4]).decode()) for r in rows[:limit])
        return MessagePage(msgs,msgs[-1].sequence if msgs else since,len(rows)>limit)
