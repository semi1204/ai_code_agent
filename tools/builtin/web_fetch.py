"""web_fetch: GET a URL and return its body as text."""

from urllib.error import HTTPError
from urllib.request import Request, urlopen

from tools.base import tool

MAX_BYTES = 100 * 1024
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


@tool(
    "web_fetch",
    "Fetch an http(s) URL and return the response body as text (redirects followed, 100KB cap).",
    {"url": "string", "timeout": "integer?"},
    kind="network",
)
def web_fetch(args, s):
    url = args["url"]
    if not url.startswith(("http://", "https://")):
        return "error: url must start with http:// or https://"
    timeout = min(max(int(args.get("timeout") or 30), 5), 120)
    try:
        with urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=timeout) as resp:
            body = resp.read(MAX_BYTES + 1)
            charset = resp.headers.get_content_charset() or "utf-8"
    except HTTPError as e:
        return f"error: HTTP {e.code}: {e.reason}"
    except OSError as e:
        return f"error: request failed: {e}"
    return body[:MAX_BYTES].decode(charset, "replace") + ("\n... [content truncated]" if len(body) > MAX_BYTES else "")
