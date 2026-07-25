from __future__ import annotations

from functools import cache

import easyocr


@cache
def get_reader() -> easyocr.Reader:
    return easyocr.Reader(["en"], gpu=False, verbose=False)
