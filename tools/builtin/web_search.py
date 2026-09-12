from html.parser import HTMLParser
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.request import Request, urlopen

from tools.base import Tool, ToolInvocation, ToolKind, ToolResult
from pydantic import BaseModel, Field

_UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"


class WebSearchParams(BaseModel):
    query: str = Field(..., description="Search query")
    max_results: int = Field(
        10,
        ge=1,
        le=20,
        description="Maximum results to return (default: 10)",
    )


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
    html = urlopen(Request(url, headers={"User-Agent": _UA}), timeout=30).read()
    parser = _DDGParser()
    parser.feed(html.decode("utf-8", "replace"))
    return [{k: v.strip() for k, v in r.items()} for r in parser.results[:max_results]]


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web for information. Returns search results with titles, URLs and snippets"
    kind = ToolKind.NETWORK
    schema = WebSearchParams

    async def execute(self, invocation: ToolInvocation) -> ToolResult:
        params = WebSearchParams(**invocation.params)

        try:
            results = _ddg_search(params.query, params.max_results)
        except Exception as e:
            return ToolResult.error_result(f"Search failed: {e}")

        if not results:
            return ToolResult.success_result(
                f"No results found for: {params.query}",
                metadata={
                    "results": 0,
                },
            )

        output_lines = [f"Search results for: {params.query}"]

        for i, result in enumerate(results, start=1):
            output_lines.append(f"{i}. Title: {result['title']}")
            output_lines.append(f"   URL: {result['href']}")
            if result.get("body"):
                output_lines.append(f"   Snippet: {result['body']}")

            output_lines.append("")

        return ToolResult.success_result(
            "\n".join(output_lines),
            metadata={
                "results": len(results),
            },
        )
