import concurrent.futures, sqlite3
import pytest
from openqsp.protocol import *
from openqsp.protocol.constants import Operation
from openqsp.storage import Database, MessageStore, BulletinStore, InvalidCursorError
from openqsp.server import ServerCore

def stores(path):
 d=Database(path);d.initialize();return d,MessageStore(d),BulletinStore(d)
def decoded(core,user,obj): return [decode_frame(x) for x in core.handle_frame(user,encode_frame(obj))]
def test_wire_models_and_sizes():
 assert not hasattr(SendMessage(1,'EA3GNU','x'),'message_id')
 assert not hasattr(Message(1,1,'EA1ABC','EA3GNU','x'),'message_id')
 assert len(encode_frame(SendMessage(1,'EA3GNU','x')))==17
 assert len(encode_frame(GetNewMessages(0,20)))==9
 assert len(encode_frame(GetBulletin(1)))==8
 assert len(encode_frame(Stored()))==4
 assert decode_frame(encode_frame(Stored()))==Stored()
def test_mailbox_local_sequences_and_access(tmp_path):
 d,m,b=stores(tmp_path/'x.db');c=ServerCore(message_store=m,bulletin_store=b)
 assert decoded(c,'EA1SRC',SendMessage(1,'EA3GNU','one'))==[Stored()]
 decoded(c,'EA2SRC',SendMessage(2,'EA3GNU','two'));decoded(c,'EA1SRC',SendMessage(3,'EA3ABC','other'))
 mine=decoded(c,'EA3GNU',GetNewMessages(0,20)); assert [x.sequence for x in mine[:-1]]==[1,2]
 other=decoded(c,'EA3ABC',GetNewMessages(0,20)); assert [x.sequence for x in other[:-1]]==[1]
 assert all(x.recipient=='EA3GNU' for x in mine[:-1])
def test_cursor_is_mailbox_scoped(tmp_path):
 d,m,b=stores(tmp_path/'x.db');m.store_message(created_at=1,author='EA1SRC',recipient='EA3GNU',body='x')
 with pytest.raises(InvalidCursorError):m.get_new_messages(callsign='EA3ABC',since=1,limit=20)
def test_concurrent_and_restart_safe(tmp_path):
 path=tmp_path/'x.db';d,m,b=stores(path)
 def send(i): return m.store_message(created_at=i+1,author='EA1SRC',recipient='EA3GNU',body=str(i)).sequence
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool: values=list(pool.map(send,range(30)))
 assert sorted(values)==list(range(1,31))
 d2=Database(path);d2.initialize(); assert MessageStore(d2).store_message(created_at=40,author='EA1SRC',recipient='EA3GNU',body='next').sequence==31
def test_bulletin_sequence_is_identity(tmp_path):
 d,m,b=stores(tmp_path/'x.db'); assert b.store_bulletin(created_at=1,author='EA1SRC',title='t',body='b').sequence==1
 item=b.get_bulletin(sequence=1); assert item.sequence==1
 core=ServerCore(message_store=m,bulletin_store=b)
 assert decoded(core,'EA3GNU',GetBulletin(1))==[Bulletin(1,1,'EA1SRC','t','b')]
def test_v1_migration_preserves_and_localizes(tmp_path):
 from openqsp.storage.migrations import migrate,encode_u64
 path=tmp_path/'x.db'; c=sqlite3.connect(path,isolation_level=None);migrate(c,0,target_version=1)
 for oid,seq,recipient,body in [(1,1,'EA3GNU',b'a'),(2,2,'EA3ABC',b'b'),(3,3,'EA3GNU',b'c')]:
  e=encode_u64(oid);c.execute("INSERT INTO objects VALUES(?,'message')",(e,));c.execute('INSERT INTO messages VALUES(?,?,?,?,?,?,?,?)',(encode_u64(seq),e,1,1,'EA1SRC',recipient,body,b'x'))
 e=encode_u64(9);c.execute("INSERT INTO objects VALUES(?,'bulletin')",(e,));c.execute('INSERT INTO bulletins VALUES(?,?,?,?,?,?,?,?)',(encode_u64(4),e,1,1,'EA1SRC','t',b'b',b'x'));c.close()
 d=Database(path);d.initialize(); ms=MessageStore(d)
 assert [x.sequence for x in ms.get_new_messages(callsign='EA3GNU',since=0,limit=20).messages]==[1,2]
 assert BulletinStore(d).get_bulletin(sequence=1).title=='t'
def test_unsolicited_flag_preserved():
 obj=Message(1,1,'EA1SRC','EA3GNU','x'); raw=encode_frame(obj,unsolicited=True)
 assert decode_frame_with_flags(raw)==(obj,1)
def test_reference_client_has_no_uuid_or_message_id():
 import inspect
 from openqsp.client.tcp import OpenQSPClient
 source=inspect.getsource(OpenQSPClient.send_message)
 assert 'uuid' not in source and 'message_id' not in source
 assert 'Stored' in source
