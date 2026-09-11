"""HTTP requests whose connection address cannot change after validation."""
import ipaddress
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
import urllib3
from requests.structures import CaseInsensitiveDict


class UnsafeFeedURL(ValueError):
    """A destination is not suitable for unauthenticated public discovery."""


def public_address(value):
    address = ipaddress.ip_address(value)
    if (not address.is_global or address.is_multicast or address.is_reserved
            or getattr(address, "ipv4_mapped", None)
            or getattr(address, "sixtofour", None)
            or getattr(address, "teredo", None)
            or (address.version == 6 and address not in ipaddress.ip_network("2000::/3"))):
        raise UnsafeFeedURL("A public destination is required.")
    return str(address)


def resolve_public_url(url):
    if not isinstance(url, str) or not url or len(url) > 2048:
        raise UnsafeFeedURL("Invalid feed URL.")
    if any(ord(c) <= 32 or ord(c) == 127 for c in url) or "\\" in url:
        raise UnsafeFeedURL("Invalid feed URL.")
    try:
        parts = urlsplit(url)
        if (parts.scheme not in {"http", "https"} or not parts.hostname
                or parts.username is not None or parts.password is not None
                or "%" in parts.hostname):
            raise ValueError()
        hostname = parts.hostname.encode("idna").decode("ascii")
        port = parts.port if parts.port is not None else (443 if parts.scheme == "https" else 80)
        if not 1 <= port <= 65535:
            raise ValueError()
        # Resolve all answers before choosing any one. A mixed public/private
        # answer is rejected, even when the first address looks safe.
        answers = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        addresses = [public_address(answer[4][0]) for answer in answers]
        if not addresses:
            raise ValueError()
    except (ValueError, UnicodeError, OSError) as error:
        raise UnsafeFeedURL("A public HTTP(S) destination is required.") from error
    authority = f"[{hostname}]" if ":" in hostname else hostname
    default_port = 443 if parts.scheme == "https" else 80
    if port != default_port:
        authority += f":{port}"
    normalized = urlunsplit((parts.scheme, authority, parts.path or "/", parts.query, ""))
    return normalized, hostname, port, addresses[0], authority


def public_get(url, headers=None, timeout=30):
    """Fetch with pinned DNS, verified TLS, no proxies, and checked redirects."""
    for hop in range(11):
        url, hostname, port, address, authority = resolve_public_url(url)
        parts = urlsplit(url)
        target = requests.Request("GET", url).prepare().path_url
        request_headers = dict(headers or {})
        request_headers["Host"] = authority
        pool_class = urllib3.HTTPConnectionPool
        options = {}
        if parts.scheme == "https":
            pool_class = urllib3.HTTPSConnectionPool
            options = {"cert_reqs": "CERT_REQUIRED", "ca_certs": requests.certs.where(),
                       "assert_hostname": hostname, "server_hostname": hostname}
        # Numeric pool host pins the connection; TLS and Host still use the
        # original name. No environment proxy, netrc or second hostname lookup.
        with pool_class(address, port=port, **options) as pool:
            raw = pool.urlopen("GET", target, headers=request_headers,
                               timeout=timeout, redirect=False, retries=False)
            response = requests.Response()
            response.status_code = raw.status
            response.headers = CaseInsensitiveDict(raw.headers)
            response._content = raw.data
            response.encoding = requests.utils.get_encoding_from_headers(response.headers)
            response.url = url
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response
        location = response.headers.get("Location")
        if not location or hop == 10:
            raise UnsafeFeedURL("Invalid redirect chain.")
        # Do not let urljoin silently strip controls before validation.
        if any(ord(c) <= 32 or ord(c) == 127 for c in location) or "\\" in location:
            raise UnsafeFeedURL("Invalid redirect destination.")
        url = urljoin(url, location)
    raise UnsafeFeedURL("Invalid redirect chain.")
