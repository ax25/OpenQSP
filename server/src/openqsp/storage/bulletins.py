"""Atomic node-local bulletin sequence storage."""
from __future__ import annotations
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from ._common import MAX_U32,InvalidCursorError,SequenceExhaustedError,StoreOutcome,StoreResult,require_u32
from .database import Database
MAX_RETRIEVAL_LIMIT=20
@dataclass(frozen=True)
class StoredBulletinHeader: sequence:int; created_at:int; author:str; title:str
@dataclass(frozen=True)
class StoredBulletin: sequence:int; created_at:int; author:str; title:str; body:str
@dataclass(frozen=True)
class BulletinPage: headers:tuple[StoredBulletinHeader,...]; next_since:int; has_more:bool
class BulletinStore:
 def __init__(self,database:Database,*,clock:Callable[[],int]|None=None): self._database=database; self._clock=clock or (lambda:int(time.time()))
 def store_bulletin(self,*,created_at:int,author:str,title:str,body:str)->StoreOutcome:
  require_u32('created_at',created_at)
  with closing(self._database.connect()) as c:
   c.execute('BEGIN IMMEDIATE')
   try:
    last=int(c.execute('SELECT last_value FROM bulletin_sequence WHERE singleton=1').fetchone()[0])
    if last==MAX_U32: raise SequenceExhaustedError('bulletin sequence exhausted')
    seq=last+1;c.execute('INSERT INTO bulletins VALUES(?,?,?,?,?,?)',(seq,created_at,self._clock(),author,title,body.encode()));c.execute('UPDATE bulletin_sequence SET last_value=? WHERE singleton=1',(seq,));c.commit();return StoreOutcome(StoreResult.STORED,seq)
   except BaseException:c.rollback();raise
 def get_new_bulletins(self,*,since:int,limit:int)->BulletinPage:
  require_u32('since',since)
  with closing(self._database.connect()) as c:
   highest=int(c.execute('SELECT last_value FROM bulletin_sequence').fetchone()[0])
   if since>highest: raise InvalidCursorError('bulletin cursor ahead')
   rows=c.execute('SELECT sequence,created_at,author,title FROM bulletins WHERE sequence>? ORDER BY sequence LIMIT ?',(since,limit+1)).fetchall()
  hs=tuple(StoredBulletinHeader(*r) for r in rows[:limit]);return BulletinPage(hs,hs[-1].sequence if hs else since,len(rows)>limit)
 def get_bulletin(self,*,sequence:int)->StoredBulletin|None:
  require_u32('sequence',sequence)
  with closing(self._database.connect()) as c:r=c.execute('SELECT sequence,created_at,author,title,body FROM bulletins WHERE sequence=?',(sequence,)).fetchone()
  return None if r is None else StoredBulletin(int(r[0]),int(r[1]),str(r[2]),str(r[3]),bytes(r[4]).decode())
