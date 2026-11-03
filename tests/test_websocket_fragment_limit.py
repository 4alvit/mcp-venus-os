"""Exercise the installed dependency fix, without implying a Uvicorn limit."""

import asyncio

import pytest
from websockets.asyncio.messages import Assembler
from websockets.exceptions import TooManyFragments
from websockets.frames import CONT, TEXT, Frame


@pytest.mark.asyncio
async def test_fragmented_text_preserves_utf8() -> None:
    assembler = Assembler()
    assembler.put(Frame(TEXT, b"a\xe2", fin=False))
    assembler.put(Frame(CONT, b"\x82", fin=False))
    assembler.put(Frame(CONT, b"\xac"))
    try:
        assert await asyncio.wait_for(assembler.get(), 1) == "a\u20ac"
    finally:
        assembler.close()


@pytest.mark.asyncio
async def test_empty_fragments_at_limit_complete() -> None:
    assembler = Assembler()
    assembler.put(Frame(TEXT, b"", fin=False))
    for _ in range(4094):
        assembler.put(Frame(CONT, b"", fin=False))
    assembler.put(Frame(CONT, b"done"))
    try:
        assert await asyncio.wait_for(assembler.get(), 1) == "done"
    finally:
        assembler.close()


@pytest.mark.asyncio
async def test_unfinished_empty_fragments_fail_before_eof() -> None:
    assembler = Assembler()
    assembler.put(Frame(TEXT, b"", fin=False))
    for _ in range(4096):
        assembler.put(Frame(CONT, b"", fin=False))
    try:
        # No final frame or EOF is supplied. Payload bytes alone cannot bound this.
        with pytest.raises(TooManyFragments):
            await asyncio.wait_for(assembler.get(), 1)
    finally:
        assembler.close()
