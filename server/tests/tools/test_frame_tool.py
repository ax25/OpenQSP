from contextlib import redirect_stderr, redirect_stdout
from importlib.util import module_from_spec, spec_from_file_location
from io import StringIO
from pathlib import Path
import pytest

P = Path(__file__).parents[3] / "tools/frame_tool.py"
spec = spec_from_file_location("frame_tool", P)
tool = module_from_spec(spec)
spec.loader.exec_module(tool)


def run(*args):
    out, err = StringIO(), StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = tool.main(list(args))
    return code, out.getvalue(), err.getvalue()


CASES = [
    (("GET_BULLETIN", "--sequence", "3"), "01 04 00 04 00 00 00 03"),
    (
        ("GET_NEW_MESSAGES", "--since", "124", "--max", "5"),
        "01 02 00 05 00 00 00 7C 05",
    ),
    (
        (
            "SEND_MESSAGE",
            "--created-at",
            "0x65000000",
            "--recipient",
            "EA1ABC",
            "--body",
            "Hola",
        ),
        "01 01 00 10 65 00 00 00 06 45 41 31 41 42 43 04 48 6F 6C 61",
    ),
    (("STORED",), "01 44 00 00"),
    (
        (
            "END",
            "--request-operation",
            "get_new_messages",
            "--returned-count",
            "1",
            "--next-since",
            "125",
            "--has-more",
            "false",
        ),
        "01 43 00 07 02 01 00 00 00 7D 00",
    ),
]


@pytest.mark.parametrize("args,wire", CASES)
def test_encode_vectors(args, wire):
    assert run("encode", *args) == (0, wire + "\n", "")


def test_decode_and_validate():
    code, out, _ = run("decode", "01 04 00 04 00 00 00 03")
    assert code == 0 and "Operation: GET_BULLETIN" in out and "sequence: 3" in out
    assert run("validate", "01 44 00 00")[1].startswith("VALID")


def test_invalid_hex():
    assert run("validate", "no")[0] == 1


def test_operation_case_insensitive():
    assert run("encode", "stored")[0] == 0


@pytest.mark.parametrize(
    "value,ending", [("true", "01"), ("1", "01"), ("false", "00"), ("0", "00")]
)
def test_boolean(value, ending):
    assert (
        run(
            "encode",
            "END",
            "--request-operation",
            "GET_NEW_MESSAGES",
            "--returned-count",
            "0",
            "--next-since",
            "0",
            "--has-more",
            value,
        )[1]
        .strip()
        .endswith(ending)
    )
