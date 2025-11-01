import unicodedata
import re
from typing import Final

from werkzeug.utils import secure_filename as _secure_filename

_FILENAME_STRIP_RE: Final = re.compile(r"[^\w.-]", re.UNICODE)


def secure_filename(filename: str, allow_unicode: bool = False) -> str:
    """
    Wrapper around Werkzeug's secure_filename that keeps compatibility with older
    implementations which accepted allow_unicode. Werkzeug 3.1 dropped that argument,
    so we replicate the unicode-friendly behaviour when required.
    """
    if not allow_unicode:
        return _secure_filename(filename)

    try:
        return _secure_filename(filename, allow_unicode=True)  # type: ignore[arg-type]
    except TypeError:
        cleaned = _sanitize_unicode_filename(filename)
        return cleaned or _secure_filename(filename)


def _sanitize_unicode_filename(filename: str) -> str:
    value = str(filename).strip().replace("\\", " ")
    value = value.replace("/", " ")
    value = unicodedata.normalize("NFKC", value)
    value = _FILENAME_STRIP_RE.sub("_", value)
    return value.lstrip("._")

