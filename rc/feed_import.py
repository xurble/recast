"""Import validated responses without feed-reader's unrestricted HTTP calls."""
from io import BytesIO, StringIO
from urllib.parse import urljoin
from xml.etree import ElementTree

import feedparser
from feeds.utils_internal import parse_feed

from .public_http import UnsafeFeedURL, public_get


def import_public_feed(source, response, headers):
    seen = set()
    for page in range(20):
        if response.url in seen or response.status_code != 200:
            raise UnsafeFeedURL("Invalid feed pagination.")
        seen.add(response.url)
        body = response.content.strip()
        content_type = response.headers.get("Content-Type", "")
        next_url = None
        if "xml" in content_type or body[:1] == b"<":
            # The library follows rel=next itself. Remove these declarations
            # from the bytes it receives and fetch each page here instead.
            # Require well-formed XML so this removal has unambiguous semantics.
            try:
                root = ElementTree.fromstring(body)
            except ElementTree.ParseError as error:
                raise UnsafeFeedURL("Invalid feed XML.") from error
            parsed = feedparser.parse(BytesIO(body))
            for link in parsed.feed.get("links", []):
                if link.get("rel") == "next":
                    next_url = urljoin(response.url, link.get("href", ""))
                    break
            for parent in root.iter():
                for child in list(parent):
                    if (child.tag.rsplit("}", 1)[-1].lower() == "link"
                            and any(key.rsplit("}", 1)[-1].lower() == "rel"
                                    and value.strip().lower() == "next"
                                    for key, value in child.attrib.items())):
                        parent.remove(child)
            body = ElementTree.tostring(root, encoding="utf-8")
        ok, changed = parse_feed(source, body, content_type, StringIO())
        if not ok:
            raise UnsafeFeedURL("The feed could not be imported.")
        source.save()
        if not next_url:
            return
        if page == 19:
            raise UnsafeFeedURL("Too many feed pages.")
        response = public_get(next_url, headers=headers)
