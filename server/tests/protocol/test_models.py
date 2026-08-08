from dataclasses import FrozenInstanceError, fields
import pytest
from openqsp.protocol.constants import *
from openqsp.protocol.models import *


def test_operation_codes():
    assert {x.name: x.value for x in Operation} == {
        "SEND_MESSAGE": 1,
        "GET_NEW_MESSAGES": 2,
        "GET_NEW_BULLETINS": 3,
        "GET_BULLETIN": 4,
        "MESSAGE": 64,
        "BULLETIN_HEADER": 65,
        "BULLETIN": 66,
        "END": 67,
        "STORED": 68,
        "ERROR": 69,
    }


def test_protocol_constants():
    assert (PROTOCOL_VERSION, HEADER_SIZE, MAX_PAYLOAD_SIZE, MAX_FRAME_SIZE) == (
        1,
        4,
        255,
        259,
    )
    assert (MIN_CALLSIGN_LENGTH, MAX_CALLSIGN_LENGTH) == (3, 12)
    assert (MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH) == (1, 208)
    assert (MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH) == (1, 64)
    assert (MIN_BULLETIN_BODY_LENGTH, MAX_BULLETIN_BODY_LENGTH) == (1, 164)


CASES = [
    (SendMessage, (1, "EA1ABC", "Hola"), ("created_at", "recipient", "body")),
    (GetNewMessages, (3, 4), ("since", "max")),
    (GetNewBulletins, (5, 6), ("since", "max")),
    (GetBulletin, (7,), ("sequence",)),
    (
        Message,
        (8, 10, "EA3GNU", "EA1ABC", "Hola"),
        ("sequence", "created_at", "author", "recipient", "body"),
    ),
    (
        BulletinHeader,
        (11, 13, "EA1ABC", "Test"),
        ("sequence", "created_at", "author", "title"),
    ),
    (
        Bulletin,
        (14, 15, "EA1ABC", "Test", "Body"),
        ("sequence", "created_at", "author", "title", "body"),
    ),
    (
        End,
        (Operation.GET_NEW_MESSAGES, 1, 16, False),
        ("request_operation", "returned_count", "next_since", "has_more"),
    ),
    (Stored, (), ()),
    (
        Error,
        (Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "no"),
        ("request_operation", "error_code", "detail"),
    ),
]


@pytest.mark.parametrize("typ,values,names", CASES)
def test_models(typ, values, names):
    obj = typ(*values)
    assert tuple(x.name for x in fields(typ)) == names
    assert obj == typ(*values)
    if names:
        with pytest.raises(FrozenInstanceError):
            setattr(obj, names[0], values[0])


def test_send_has_no_author_or_id():
    assert {x.name for x in fields(SendMessage)} == {"created_at", "recipient", "body"}
