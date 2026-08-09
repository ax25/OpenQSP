"""CLI tests for the OpenQSP frame laboratory tool."""

from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path

import pytest

TOOL_PATH = Path(__file__).parents[3] / "tools" / "frame_tool.py"
SPEC = spec_from_file_location("frame_tool", TOOL_PATH)
assert SPEC and SPEC.loader
frame_tool = module_from_spec(SPEC)
SPEC.loader.exec_module(frame_tool)


def run(*args: str) -> tuple[int, str, str]:
    stdout, stderr = StringIO(), StringIO()
    with redirect_stdout(stdout), redirect_stderr(stderr):
        result = frame_tool.main(list(args))
    return result, stdout.getvalue(), stderr.getvalue()


GET_BULLETIN = "01 04 00 04 11 12 13 14"
GET_NEW_MESSAGES = "01 02 00 05 00 00 00 7C 05"
SEND_MESSAGE = (
    "01 01 00 10 65 00 00 00 "
    "06 45 41 31 41 42 43 04 48 6F 6C 61"
)
STORED = "01 44 00 00"
ERROR = "01 45 00 0C 04 07 09 4E 6F 74 20 66 6F 75 6E 64"
END = "01 43 00 07 02 01 00 00 00 7D 00"


def test_decode_canonical_vector() -> None:
    code, output, error = run("decode", GET_BULLETIN)
    assert code == 0
    assert error == ""
    assert "Operation: GET_BULLETIN" in output
    assert "Frame size: 8 bytes" in output
    assert "Payload size: 4 bytes" in output
    assert "sequence: 286397204 (0x11121314)" in output
    assert GET_BULLETIN in output


def test_validate_valid_and_invalid_frames() -> None:
    valid_code, valid_output, _ = run("validate", GET_BULLETIN)
    assert valid_code == 0
    assert valid_output == "VALID\nOperation: GET_BULLETIN\n"

    invalid_code, invalid_output, _ = run("validate", "01 04 00 04 11")
    assert invalid_code != 0
    assert invalid_output.startswith("INVALID\nPayloadLengthError:")


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (("GET_BULLETIN", "--sequence", "0x11121314"), GET_BULLETIN),
        (("GET_NEW_MESSAGES", "--since", "124", "--max", "5"), GET_NEW_MESSAGES),
        (
            (
                "SEND_MESSAGE", "--created-at", "0x65000000", "--recipient", "EA1ABC",
                "--body", "Hola",
            ),
            SEND_MESSAGE,
        ),
        (("STORED",), STORED),
        (
            (
                "ERROR", "--request-operation", "get_bulletin", "--error-code",
                "not_found", "--detail", "Not found",
            ),
            ERROR,
        ),
        (
            (
                "END", "--request-operation", "get_new_messages", "--returned-count",
                "1", "--next-since", "0x7D", "--has-more", "false",
            ),
            END,
        ),
    ],
)
def test_encode_canonical_vectors(arguments: tuple[str, ...], expected: str) -> None:
    code, output, error = run("encode", *arguments)
    assert (code, output.strip(), error) == (0, expected, "")


def test_decimal_and_hexadecimal_integers_are_equivalent() -> None:
    decimal = run("encode", "GET_BULLETIN", "--sequence", "286397204")
    hexadecimal = run("encode", "GET_BULLETIN", "--sequence", "0x11121314")
    assert decimal == hexadecimal


@pytest.mark.parametrize(("value", "wire_value"), [("true", "01"), ("1", "01"), ("false", "00"), ("0", "00")])
def test_end_boolean_parsing(value: str, wire_value: str) -> None:
    code, output, _ = run(
        "encode", "END", "--request-operation", "GET_NEW_BULLETINS",
        "--returned-count", "0", "--next-since", "0", "--has-more", value,
    )
    assert code == 0
    assert output.strip().endswith(wire_value)


def test_error_accepts_unknown_request_marker() -> None:
    code, output, _ = run(
        "encode", "ERROR", "--request-operation", "0", "--error-code",
        "UNKNOWN_OPERATION", "--detail", "",
    )
    assert code == 0
    assert output.strip() == "01 45 00 03 00 03 00"


def test_invalid_hexadecimal_has_nonzero_exit_without_traceback() -> None:
    code, output, error = run("decode", "not-hex")
    assert code != 0
    assert output == ""
    assert error == "ERROR: invalid hexadecimal input\n"


def test_codec_validation_error_has_nonzero_exit() -> None:
    code, output, error = run("encode", "GET_NEW_MESSAGES", "--since", "0", "--max", "21")
    assert code != 0
    assert output == ""
    assert "InvalidFieldError: max must be between 1 and 20" in error


def test_compact_hexadecimal_is_accepted() -> None:
    code, output, _ = run("validate", GET_BULLETIN.replace(" ", ""))
    assert code == 0
    assert output.startswith("VALID\n")


def test_operation_name_is_case_insensitive() -> None:
    code, output, _ = run("encode", "get_bulletin", "--sequence", "0x11121314")
    assert code == 0
    assert output.strip() == GET_BULLETIN
