import re
from urllib.parse import urlsplit, urlunsplit


_URL_RE = re.compile(r"(https?://[^\s<>()]+)", re.IGNORECASE)


def _defang_url(url: str) -> str:
    parts = urlsplit(url)
    scheme = "hxxps" if parts.scheme.lower() == "https" else "hxxp"
    netloc = parts.netloc.replace(".", "[.]")
    return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))


def defang_text(text: str) -> str:
    if not text:
        return text
    return _URL_RE.sub(lambda match: _defang_url(match.group(1)), text)
