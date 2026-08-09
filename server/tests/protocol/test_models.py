from dataclasses import FrozenInstanceError, fields

import pytest
from openqsp.protocol.constants import (
    HEADER_SIZE,
    MAX_BULLETIN_BODY_LENGTH,
    MAX_BULLETIN_TITLE_LENGTH,
    MAX_CALLSIGN_LENGTH,
    MAX_ERROR_DETAIL_LENGTH,
    MAX_FRAME_SIZE,
    MAX_MESSAGE_BODY_LENGTH,
    MAX_PAYLOAD_SIZE,
    MAX_RETRIEVAL_MAX,
    MIN_BULLETIN_BODY_LENGTH,
    MIN_BULLETIN_TITLE_LENGTH,
    MIN_CALLSIGN_LENGTH,
    MIN_MESSAGE_BODY_LENGTH,
    MIN_RETRIEVAL_MAX,
    PROTOCOL_VERSION,
    ErrorCode,
    Operation,
)
from openqsp.protocol.models import (
    Bulletin,
    BulletinHeader,
    End,
    Error,
    GetBulletin,
    GetNewBulletins,
    GetNewMessages,
    Message,
    SendMessage,
    Stored,
)


def test_operation_codes() -> None:
    assert {operation.name: operation.value for operation in Operation} == {
        "SEND_MESSAGE": 0x01,
        "GET_NEW_MESSAGES": 0x02,
        "GET_NEW_BULLETINS": 0x03,
        "GET_BULLETIN": 0x04,
        "GET_CAPABILITIES": 0x05,
        "MESSAGE": 0x40,
        "BULLETIN_HEADER": 0x41,
        "BULLETIN": 0x42,
        "END": 0x43,
        "STORED": 0x44,
        "ERROR": 0x45,
        "CAPABILITIES": 0x46,
    }


def test_error_codes() -> None:
    assert {code.name: code.value for code in ErrorCode} == {
        "INVALID_FRAME": 0x01,
        "UNSUPPORTED_VERSION": 0x02,
        "UNKNOWN_OPERATION": 0x03,
        "INVALID_FIELD": 0x04,
        "INVALID_CURSOR": 0x05,
        "UNAUTHORIZED": 0x06,
        "NOT_FOUND": 0x07,
        "TOO_LARGE": 0x08,
        "BUSY": 0x09,
        "INTERNAL_ERROR": 0x0A,
        "REJECTED": 0x0B,
    }


def test_protocol_constants() -> None:
    assert PROTOCOL_VERSION == 0x01
    assert HEADER_SIZE == 4
    assert MAX_PAYLOAD_SIZE == 255
    assert MAX_FRAME_SIZE == 259
    assert (MIN_CALLSIGN_LENGTH, MAX_CALLSIGN_LENGTH) == (3, 12)
    assert (MIN_MESSAGE_BODY_LENGTH, MAX_MESSAGE_BODY_LENGTH) == (1, 208)
    assert (MIN_BULLETIN_TITLE_LENGTH, MAX_BULLETIN_TITLE_LENGTH) == (1, 64)
    assert (MIN_BULLETIN_BODY_LENGTH, MAX_BULLETIN_BODY_LENGTH) == (1, 164)
    assert (MIN_RETRIEVAL_MAX, MAX_RETRIEVAL_MAX) == (1, 20)
    assert MAX_ERROR_DETAIL_LENGTH == 64


MODEL_CASES = [
    (SendMessage, (2, "EA1ABC", "Hola"), ("created_at", "recipient", "body")),
    (GetNewMessages, (3, 4), ("since", "max")),
    (GetNewBulletins, (5, 6), ("since", "max")),
    (GetBulletin, (7,), ("sequence",)),
    (Message, (8, 10, "EA3GNU", "EA1ABC", "Hola"), ("sequence", "created_at", "author", "recipient", "body")),
    (BulletinHeader, (11, 13, "EA1ABC", "Test VHF"), ("sequence", "created_at", "author", "title")),
    (Bulletin, (14, 15, "EA1ABC", "Test VHF", "Actividad domingo"), ("sequence", "created_at", "author", "title", "body")),
    (End, (Operation.GET_NEW_MESSAGES, 1, 16, False), ("request_operation", "returned_count", "next_since", "has_more")),
    (Stored, (), ()),
    (Error, (Operation.GET_BULLETIN, ErrorCode.NOT_FOUND, "Not found"), ("request_operation", "error_code", "detail")),
]

@pytest.mark.parametrize(("model_type", "values", "field_names"), MODEL_CASES)
def test_model_fields_construction_and_equality(model_type, values, field_names) -> None:
    first = model_type(*values)
    second = model_type(*values)

    assert tuple(field.name for field in fields(model_type)) == field_names
    assert first == second


@pytest.mark.parametrize(("model_type", "values", "field_names"), MODEL_CASES)
def test_models_are_immutable(model_type, values, field_names) -> None:
    model = model_type(*values)

    with pytest.raises(FrozenInstanceError):
        setattr(model, field_names[0] if field_names else "unexpected", values[0] if values else 1)


def test_send_message_has_no_author() -> None:
    assert "author" not in {field.name for field in fields(SendMessage)}


def test_error_allows_unknown_request_operation_marker() -> None:
    assert Error(0, ErrorCode.INVALID_FRAME, "").request_operation == 0
