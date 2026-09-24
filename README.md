# Recast

Recast is a django based podcast feed rebroadcaster.  There is a running version at https://recastthis.com if you want to try it out.

Recast is designed to make it convenient to listen to all the old episodes of a podcast from the beginning.

Most podcast clients will only automatically present the latest episode of a podcast and leave you to manually download previous episodes one by one, eliminating the convenience of automatic delivery.

Instead of subscribing directly to the podcast, you give Recast the address of the website or feed of the podcast and it will return you a unique, personalized feed. Simply subscribe to the Recast feed instead.

By default Recast will feed you a new episode of the podcast every five days - enough to slowly catch up with most weekly podcasts. At any time, you can change the frequency new episodes are released, or just release the next episode.

## Installation

Recast is a pretty simple django (4.2) application.

Install it using `pip -r requirements.txt`

There are a number of settings that are not in `settings.py`. They are imported
from `recast/server_settings.py`, which you will need to create.

The settings are as follows:

### Standard Django Settings

* `ALLOWED_HOSTS` 
* `STATIC_ROOT`
* `DEBUG`
* `SECRET_KEY` 
* `DATABASES` - The full database dictionary 

### HTTPS deployment

Django enforces the production HTTPS boundary when `DEBUG = False`:

* HTTP requests are permanently redirected to HTTPS.
* Session and CSRF cookies use the `Secure` attribute.
* HTTPS responses send HSTS with a one-year lifetime. The policy deliberately
  excludes subdomains and the browser preload list because this repository does
  not control or verify every subdomain.

Terminate TLS either in the application server or in a trusted reverse proxy. If
TLS terminates in a proxy, add this to `recast/server_settings.py`:

```python
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
```

Only set that value when the proxy removes any client-supplied
`X-Forwarded-Proto` header and replaces it with the connection's real scheme.
Otherwise clients could spoof secure requests. A missing or incorrect proxy
setting can also cause an HTTPS redirect loop.

For local HTTP development, set `DEBUG = True`. This explicitly disables the
redirect, Secure-cookie requirement, and HSTS; never use that setting in
production. HSTS is intentionally enabled only after a successful HTTPS request,
so deploy and verify TLS before directing production traffic to the application.


### Recast Specific Settings

Recast will work with a Cloudflare account (a free one will do) to provide caching.  To take advantage of this, provide the following details

* `CLOUDFLARE_TOKEN` = Cloudflare API token if you are using it
* `CLOUDFLARE_ZONE` = Cloudflare Zone if you are using it

You can use a Cloudflare web worker to bust through Cloudlflare protected feeds.  Set up a new worker with the code in
[this file](https://raw.githubusercontent.com/xurble/django-feed-reader/master/support/cloudflare_worker.js) and then
put the url into the following setting.

* `FEEDS_CLOUDFLARE_WORKER` -  The url to your cloudflare worker if you are using them e.g. `https://foo.bar.workers.dev`


### Updating feeds

Once Recast is running, in order to keep it ticking over and reading feeds you need to periodically call `manage.py refreshfeeds`

I have a cron job that does this every 10 minutes.  

And that's it.

### Bounded public feed discovery

Initial imports remain synchronous. Recast fetches and parses an unknown source
once in a disposable subprocess, then imports the validated entries atomically.
The subprocess has no Django settings or deployment environment. It verifies TLS,
does not use environment proxy credentials, and cannot access the database.
Every request resolves and validates all DNS answers, connects to a validated
numeric public address, and preserves the hostname for HTTP Host, HTTPS SNI, and
certificate validation. Private, loopback, link-local, reserved, multicast,
shared, mixed public/private, and IPv6 transition destinations are rejected.
Redirect destinations are checked the same way before a connection is made.
Initial imports never follow feed pagination or invoke `read_feed`; scheduled
`refreshfeeds` behavior is unchanged and is outside these initial-import limits.

The default `RECAST_DISCOVERY_LIMITS` can be overridden by a dictionary in
`recast/server_settings.py` (omitted keys retain their defaults):

| Key | Default | Meaning |
| --- | ---: | --- |
| `wire_bytes` | 2097152 | 2 MiB of compressed/received body bytes |
| `body_bytes` | 8388608 | 8 MiB after decompression |
| `entries` | 500 | Reject larger feeds; do not silently truncate history |
| `attachments_per_entry` | 10 | Maximum enclosure/media declarations per entry |
| `attachments` | 2000 | Maximum enclosure/media declarations across the feed |
| `redirects` | 3 | HTTP redirect hops; redirect bodies are not downloaded |
| `seconds` | 15 | Wall-clock subprocess deadline, including startup, DNS, headers, body, parsing and result serialization |
| `attempts_per_hour` | 30 | Global unknown-source discovery attempts in any rolling hour |
| `sources` | 10000 | Lifetime successful public source creations after this migration |

Values must be positive integers. Identity and single-member gzip responses are
accepted; other encodings, concatenated/truncated gzip and XML entity declarations
are rejected. HTML discovery offers at most 20 alternate links. Parsed worker
output is additionally capped at 16 MiB. These conservative defaults bound work
while accommodating typical podcast feeds; operators can raise them deliberately
for larger archives. They do not impose a total cap on existing sources or future
scheduled refreshes.

Run `manage.py migrate` before enabling the new code. Migration `0004` creates
and seeds one `DiscoveryQuota` row; it does not modify existing feeds. Quotas use
database write locking, not process-local cache or client IPs. Only one discovery
may run at once across workers. Admissions older than one hour are discarded, so
the limit applies continuously rather than at fixed boundaries. Errors and
HTML-only discoveries consume an attempt. Returning an existing source needs no
worker or quota slot. Successful imports increment the lifetime counter, which
does not decrease when sources are deleted. Reaching that cap requires an
operator to raise `sources`; it never silently resets.

A lease expires after the worker deadline plus 30 seconds, recovering a crashed
request without allowing a stale worker to commit or release a newer lease. The
bounded database import uses a transaction and checks the lease before and after
its writes; a limit violation or persistence failure leaves no partial source,
posts or enclosures. The 15-second hard deadline applies to fetching/parsing;
database availability and individual SQL execution remain subject to deployment
DB timeouts. Operators should configure finite connection/lock/statement timeouts.
The lease does not cancel an SQL statement already in progress.

Busy/rate/capacity responses use HTTP 429; feed limits and malformed feeds use 422;
upstream HTTP failures use 502; unavailable quota/database access uses 503. The
submission page displays the returned explanation and stops its progress indicator.
No background queue or additional infrastructure is introduced. Roll back the
application before reversing `0004`; otherwise discovery fails closed when the
quota table/seed is absent.

### Isolated checks

Use Python 3.12 and a worktree-local environment, with mysqlclient build
prerequisites available:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python manage.py test rc --settings=recast.test_settings
./scripts/check
```

The test settings provide an ephemeral secret, SQLite database, local memory cache
and temporary static/media paths. They never load `server_settings.py` or production
credentials. Discovery network tests mock DNS and HTTP boundaries; subprocess deadline tests use
an inert local sleeping process. No feed or Cloudflare service is required.
