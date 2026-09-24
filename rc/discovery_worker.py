"""Fetch and parse untrusted feeds without Django, credentials, or database access.

Invoked as a subprocess: the parent enforces the wall-clock deadline, including
DNS, response headers, trickle bodies and parser CPU time.
"""
import calendar
import hashlib
import json
import sys
import zlib
from datetime import datetime, timezone
from urllib.parse import urljoin, urlsplit
from xml.parsers import expat

import feedparser
import requests
import urllib3
from bs4 import BeautifulSoup
from feedparser.sanitizer import _sanitize_html

from .public_http import UnsafeFeedURL, resolve_public_url


class DiscoveryError(Exception):
    def __init__(self, message, reason="limit", status=422):
        super().__init__(message)
        self.reason = reason
        self.status = status


def http_url(value):
    if not isinstance(value, str) or len(value) > 512:
        raise DiscoveryError("The feed URL is invalid.", "invalid")
    try:
        parts = urlsplit(value)
        parts.port  # Validate malformed/out-of-range ports before admission.
    except ValueError as error:
        raise DiscoveryError("The feed URL is invalid.", "invalid") from error
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        raise DiscoveryError("Use an HTTP or HTTPS feed URL without credentials.", "invalid")
    return value


def fetch(url, limits, agent):
    headers = {"User-Agent": agent, "Accept-Encoding": "gzip, identity"}
    for hop in range(limits["redirects"] + 1):
        try:
            normalized, hostname, port, address, authority = resolve_public_url(http_url(url))
        except UnsafeFeedURL as error:
            raise DiscoveryError("A public HTTP(S) feed URL is required.", "invalid") from error
        parts = urlsplit(normalized)
        target = requests.Request("GET", normalized).prepare().path_url
        request_headers = headers | {"Host": authority}
        pool_class = urllib3.HTTPConnectionPool
        options = {}
        if parts.scheme == "https":
            pool_class = urllib3.HTTPSConnectionPool
            options = {"cert_reqs": "CERT_REQUIRED", "ca_certs": requests.certs.where(),
                       "assert_hostname": hostname, "server_hostname": hostname}
        try:
            with pool_class(address, port=port, **options) as pool:
                response = pool.urlopen(
                    "GET", target, headers=request_headers,
                    timeout=urllib3.Timeout(connect=3, read=3), redirect=False,
                    retries=False, preload_content=False, decode_content=False,
                )
                try:
                    if response.status in {301, 302, 303, 307, 308}:
                        location = response.headers.get("Location")
                        if hop == limits["redirects"] or not location:
                            raise DiscoveryError("The feed redirected too many times.")
                        url = http_url(urljoin(normalized, location))
                        continue
                    if response.status != 200:
                        reason = "cloudflare" if response.status == 403 and "cloudflare" in response.headers.get("Server", "").lower() else str(response.status)
                        raise DiscoveryError("The podcast server refused the request.", reason, 502)
                    encoding = response.headers.get("Content-Encoding", "identity").strip().lower()
                    if encoding not in {"identity", "gzip"}:
                        raise DiscoveryError("The feed uses unsupported compression.")
                    length = response.headers.get("Content-Length")
                    try:
                        if length and int(length) > limits["wire_bytes"]:
                            raise DiscoveryError("The feed response is too large.")
                    except ValueError as error:
                        raise DiscoveryError("The feed response is invalid.", "invalid") from error
                    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS) if encoding == "gzip" else None
                    body = bytearray()
                    wire = 0
                    while True:
                        chunk = response.read(16 * 1024, decode_content=False)
                        if not chunk:
                            break
                        wire += len(chunk)
                        if wire > limits["wire_bytes"]:
                            raise DiscoveryError("The feed response is too large.")
                        remaining = limits["body_bytes"] - len(body)
                        decoded = decoder.decompress(chunk, remaining + 1) if decoder else chunk
                        if len(decoded) > remaining or (decoder and decoder.unconsumed_tail):
                            raise DiscoveryError("The expanded feed is too large.")
                        body.extend(decoded)
                        if decoder and decoder.unused_data:
                            raise DiscoveryError("Concatenated or trailing compressed data is not supported.")
                    if decoder and not decoder.eof:
                        raise DiscoveryError("The compressed feed is incomplete.", "invalid")
                    return bytes(body), response.headers.get("Content-Type", ""), normalized
                finally:
                    response.close()
        except (urllib3.exceptions.HTTPError, OSError) as error:
            raise DiscoveryError("The podcast server could not be reached.", "unavailable", 502) from error
    raise DiscoveryError("No feed response was received.", "invalid")


def text(value, maximum=None):
    value = value if isinstance(value, str) else ""
    return value[:maximum] if maximum else value


def clean_html(value):
    return _sanitize_html(text(value), "utf-8", "text/html")


def date_value(value):
    try:
        if isinstance(value, (tuple, list)):
            return datetime.fromtimestamp(calendar.timegm(value), timezone.utc).isoformat()
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=result.tzinfo or timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError, OverflowError):
        return datetime.now(timezone.utc).isoformat()


def enclosure(value):
    href = text(value.get("href") or value.get("url"), 512)
    try:
        length = max(0, min(int(value.get("length", value.get("size_in_bytes", value.get("filesize", 0)))), 2**31 - 1))
    except (ValueError, TypeError):
        length = 0
    return {"href": href, "length": length,
            "type": text(value.get("type") or value.get("mime_type") or "audio/mpeg", 256),
            "medium": text(value.get("medium"), 25),
            "description": text(value.get("description"), 512)}


def check_xml(body, limits):
    """Reject entity expansion and count entries before building a feed tree."""
    parser = expat.ParserCreate(namespace_separator="}")
    count = 0
    def start(name, attrs):
        nonlocal count
        if name.rsplit("}", 1)[-1].lower() in {"item", "entry"}:
            count += 1
            if count > limits["entries"]:
                raise DiscoveryError("The feed has too many entries.")
    def entity(*args):
        raise DiscoveryError("XML entities are not supported.")
    parser.StartElementHandler = start
    parser.EntityDeclHandler = entity
    parser.ExternalEntityRefHandler = entity
    try:
        parser.Parse(body, True)
    except expat.ExpatError as error:
        raise DiscoveryError("The XML feed is malformed.", "invalid") from error


def parse(body, content_type, url, limits):
    body = body.lstrip()
    content_type = content_type.lower()
    prefix = body[:256].lower()
    is_json = body.startswith(b"{") or "json" in content_type
    is_xml_feed = prefix.startswith((b"<?xml", b"<rss", b"<feed"))
    is_html = prefix.startswith((b"<!doctype html", b"<html")) or (
        "html" in content_type and not is_json and not is_xml_feed
    )
    if is_html:
        soup = BeautifulSoup(body, "html.parser")
        links = []
        for link in soup.find_all("link", href=True):
            if "alternate" in link.get("rel", []) and link.get("type") in {"application/rss+xml", "application/atom+xml", "application/feed+json"}:
                links.append({"url": http_url(urljoin(url, link["href"])), "title": text(link.get("title") or "Feed", 255)})
                if len(links) > 20:
                    raise DiscoveryError("The page advertises too many feeds.")
        return {"kind": "links", "links": links}
    if is_json:
        try:
            data = json.loads(body)
        except (TypeError, ValueError) as error:
            raise DiscoveryError("The JSON feed is malformed.", "invalid") from error
        entries = data.get("items", [])
        if not isinstance(entries, list) or data.get("expired"):
            raise DiscoveryError("The JSON feed is invalid or expired.", "invalid")
        meta = {"name": clean_html(data.get("title"))[:255],
                "site_url": text(data.get("home_page_url"), 255),
                "description": clean_html(data.get("description")),
                "image_url": text(data.get("icon"), 512)}
    else:
        check_xml(body, limits)
        data = feedparser.parse(body, response_headers={"content-location": url})
        entries = data.entries
        meta = {"name": text(data.feed.get("title"), 255),
                "site_url": text(data.feed.get("link"), 255),
                "description": text(data.feed.get("description") or data.feed.get("subtitle")),
                "image_url": text(data.feed.get("image", {}).get("href"), 512)}
    if not entries:
        raise DiscoveryError("The feed contains no entries.", "invalid")
    if len(entries) > limits["entries"]:
        raise DiscoveryError("The feed has too many entries.")
    posts = []
    attachment_count = 0
    seen = set()
    for item in reversed(entries):
        if is_json:
            body_text = clean_html(item.get("content_html")) if "content_html" in item else clean_html(item.get("content_text"))
            title = clean_html(item.get("title"))
            link = text(item.get("url"), 512)
            guid = item.get("id")
            created = date_value(item.get("date_published"))
            author = item.get("author", {})
            author = author.get("name", "") if isinstance(author, dict) else author
            attachments = item.get("attachments", [])
            image = text(item.get("image") or item.get("banner_image"), 512)
        else:
            bodies = [text(item.get("summary")), text(item.get("description"))]
            bodies += [text(c.get("value")) for c in item.get("content", []) if c.get("type") == "text/html"]
            body_text = max(bodies, key=len)
            title = text(item.get("title"))
            link = text(item.get("link"), 512)
            guid = item.get("id") or item.get("guid")
            created = date_value(item.get("published_parsed") or item.get("updated_parsed"))
            author = item.get("author")
            attachments = item.get("enclosures", []) + item.get("media_content", [])
            image = text(item.get("image", {}).get("href"), 512)
        if not isinstance(attachments, list) or len(attachments) > limits["attachments_per_entry"]:
            raise DiscoveryError("An entry has too many attachments.")
        attachment_count += len(attachments)
        if attachment_count > limits["attachments"]:
            raise DiscoveryError("The feed has too many attachments.")
        guid = guid if isinstance(guid, str) and 0 < len(guid) <= 768 else link or hashlib.md5(body_text.encode()).hexdigest()
        if guid in seen:
            continue
        seen.add(guid)
        enclosures = {e["href"]: e for e in map(enclosure, attachments) if e["href"]}
        posts.append({"title": title, "body": body_text, "link": link, "guid": guid,
                      "created": created, "author": text(author, 255), "image_url": image,
                      "enclosures": list(enclosures.values())})
    posts.sort(key=lambda p: datetime.fromisoformat(p["created"]))
    return {"kind": "feed", "source": meta, "posts": posts}


def discover(payload):
    body, content_type, url = fetch(payload["url"], payload["limits"], payload["agent"])
    return parse(body, content_type, url, payload["limits"])


def main():
    try:
        payload = json.load(sys.stdin)
        result = discover(payload)
        encoded = json.dumps(result)
        if len(encoded.encode()) > 16 * 1024 * 1024:
            raise DiscoveryError("The parsed feed is too large.")
    except DiscoveryError as error:
        encoded = json.dumps({"error": str(error), "reason": error.reason, "status": error.status})
    except Exception:
        encoded = json.dumps({"error": "The feed could not be read.", "reason": "invalid", "status": 422})
    sys.stdout.write(encoded)


if __name__ == "__main__":
    main()
