"""web_search: DuckDuckGo results scraped from html.duckduckgo.com."""

from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from tools.base import tool
from tools.builtin.web_fetch import USER_AGENT


class _DDGParser(HTMLParser):
    """Pulls title/href/body out of html.duckduckgo.com result markup."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._field = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = a.get("class", "")
        if tag == "a" and "result__a" in cls:
            href = a.get("href", "")
            href = parse_qs(urlparse(href).query).get("uddg", [href])[0]  # unwrap redirect
            self.results.append({"title": "", "href": href, "body": ""})
            self._field = "title"
        elif tag == "a" and "result__snippet" in cls and self.results:
            self._field = "body"

    def handle_endtag(self, tag):
        if tag == "a":
            self._field = None

    def handle_data(self, data):
        if self._field and self.results:
            self.results[-1][self._field] += data


def _ddg_search(query: str, max_results: int = 10) -> list[dict]:
    url = "https://html.duckduckgo.com/html/?" + urlencode({"q": query})
    html = urlopen(Request(url, headers={"User-Agent": USER_AGENT}), timeout=30).read()
    parser = _DDGParser()
    parser.feed(html.decode("utf-8", "replace"))
    return [{k: v.strip() for k, v in r.items()} for r in parser.results[:max_results]]


@tool(
    "web_search",
    "Search the web (DuckDuckGo); returns numbered results with title, URL and snippet.",
    {"query": "string", "max_results": "number?"},
    kind="network",
)
def web_search(args, s):
    results = _ddg_search(args["query"], min(int(args.get("max_results") or 10), 20))
    if not results:
        return f"No results for: {args['query']}"
    return "\n\n".join(f"{i}. {r['title']}\n   {r['href']}\n   {r['body']}" for i, r in enumerate(results, 1))
