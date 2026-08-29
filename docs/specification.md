# Recast Current-State Specification

## Status

This document describes the behavior of the existing Recast implementation. It
is a current-state specification, not a proposal for future behavior.

The specification was reconstructed from the application code, templates,
migrations, repository documentation, and the adjacent `django-feed-reader`
implementation. Where implementation appeared accidental or defective, that
behavior is recorded separately rather than made normative.

## Scope

This specification covers the Recast Django application and the externally
observable feed-reading behavior supplied by `django-feed-reader` that Recast
directly depends upon.

It excludes:

- hosting, process supervision, cron configuration, and other deployment details;
- behavior of podcast clients and remote podcast servers;
- Django administration behavior not customized by this repository;
- proposed product improvements or defect fixes.

## Purpose

Recast lets a listener replay the known back catalogue of a podcast from the
beginning. It creates a private, personalized RSS feed that releases episodes at
a configurable interval without requiring the listener to create an account.

## Actors and terminology

- **Listener** — finds a podcast, creates a Recast subscription, consumes its RSS
  feed, and controls its release schedule.
- **Administrator** — monitors source-feed health and can test or revive sources.
- **Podcast client** — polls a personalized Recast RSS feed.
- **Source** — a podcast feed and its imported metadata and posts, stored by
  `django-feed-reader`.
- **Post** — an imported source-feed item, normally a podcast episode.
- **Subscription** — one listener's personalized progression through a source.
- **Subscription post** — the record that fixes when a post first became visible
  in one subscription.

## Product decisions confirmed during backfill

- Possession of the unguessable subscription key is the intended authorization
  model for the personalized feed and its settings. No user account is required.
- Completion is terminal. A completed subscription does not reopen merely because
  the source later gains more episodes.
- `/refresh/` is an operational feed-refresh endpoint in the current product.
- Cloudflare-assisted initial feed discovery is an intended capability, although
  its current implementation contains defects described below.
- Feed Garden, source testing, and source revival intentionally require an
  authenticated user; they do not additionally require staff or superuser status.
- The adjacent `django-feed-reader` checkout represents the dependency behavior
  relevant to this specification.

## User workflows and functional requirements

### Discovering a podcast

**FR-001 — Start from a URL.** The home page shall accept the URL of either a
podcast website or a podcast feed. A `feed` query parameter shall prepopulate the
input, enabling the documented bookmarklet workflow.

Evidence: `rc.views.index`; `rc/templates/index.html`;
`rc/templates/help.html`.

**FR-002 — Reuse known sources.** When a submitted URL case-insensitively matches
an existing source's feed URL or site URL, Recast shall reuse that source rather
than importing a duplicate.

Evidence: `rc.views.addfeed`.

**FR-003 — Prevent recursive Recasts.** Recast shall reject a submitted URL that
contains the current Recast host so that a personalized Recast feed cannot itself
be recast.

Evidence: `rc.views.addfeed`.

**FR-004 — Recognize direct feeds.** For a successful HTTP response, Recast shall
treat XML with at least one parsed entry or JSON Feed content with at least one
item as a direct feed. It shall derive the source title and homepage from feed
metadata when available.

Evidence: `rc.views.addfeed`; `feedparser`; JSON parsing in `rc/views.py`.

**FR-005 — Discover feeds from web pages.** If a successful response is not a
direct feed, Recast shall inspect HTML `link` elements for RSS or Atom alternate
feeds. It shall report that no feeds were found or offer the discovered feeds for
selection.

Evidence: `rc.views.addfeed`; `rc/templates/index.html`.

**FR-006 — Import a new source.** A newly recognized feed shall create a Source,
schedule it for polling, and immediately ask `django-feed-reader` to import its
entries. The resulting public source page shall be returned to the listener.

Evidence: `rc.views.addfeed`; `feeds.utils.read_feed`.

**FR-007 — Report discovery failures.** Recast shall distinguish Cloudflare-like
HTTP 403 responses, other HTTP 403 responses, other non-success status codes, and
general connection or processing failures in its response to the listener.

Evidence: `rc.views.addfeed`; `rc/templates/index.html`.

### Browsing and subscribing

**FR-008 — Show source details.** A public source page shall show source metadata,
a subscription action, and up to 100 known posts. It shall indicate when more
posts exist than are displayed.

Evidence: `rc.views.source`; `rc/templates/source.html`.

**FR-009 — Create an account-free subscription.** A POST to a source's subscribe
endpoint shall create a Subscription with a random UUID key, the source display
name, an initial episode index of 1, and a default release frequency of five days.
It shall update the source's stored subscription count and redirect to the new
settings page.

Evidence: `rc.views.subscribe`; `rc.models.Subscription`.

**FR-010 — Use the key as a bearer secret.** Anyone possessing a valid subscription
key may fetch its RSS feed and view or change its settings. The listener is
responsible for keeping the URL private.

Evidence: `rc.views.feed`; `rc.views.editfeed`; `rc/templates/help.html`; confirmed
backfill decision.

### Controlling a subscription

**FR-011 — Display subscription controls.** The settings page shall show the
personalized feed URL, current release interval, next release date, and a window
of source episodes around the current position.

Evidence: `rc.views.editfeed`; `rc/templates/feed.html`.

**FR-012 — Change frequency.** A listener may set the release frequency to one of
the values presented by the settings page: 1 through 14 days.

Evidence: `rc.views.editfeed`; `rc/templates/feed.html`.

**FR-013 — Change episode position.** A listener may release the next episode,
rewind to a displayed earlier episode, or skip to a displayed later episode. A
requested index greater than the source's maximum index shall not be applied.
Changing position resets the release baseline to the current time.

Evidence: `rc.views.editfeed`; `rc/templates/feed.html`.

**FR-014 — Purge configured cache state.** After a settings update, an installation
with a Cloudflare token shall request a cache purge for the subscription settings
URL before saving the subscription.

Evidence: `rc.views.editfeed`.

### Producing the personalized RSS feed

**FR-015 — Advance on polling.** When an incomplete feed is polled, Recast shall
advance `last_sent` once for every complete release interval elapsed since
`last_sent_date`, stopping at the source's current maximum index. Slow polling may
therefore expose multiple newly due episodes at once.

Evidence: `rc.views.feed`.

**FR-016 — Mark completion.** When `last_sent` reaches the source's current maximum
index, Recast shall mark the subscription complete. Completion is terminal even if
the source later gains posts.

Evidence: `rc.views.feed`; confirmed backfill decision.

**FR-017 — Limit the RSS window.** The RSS response shall contain posts from the
subscription's source whose indices are no greater than `last_sent` and no less
than `last_sent - 25`, ordered by index.

Evidence: `rc.views.feed`.

**FR-018 — Give each item subscription-specific metadata.** RSS item GUIDs shall
combine the subscription key and post identifier. When a post first appears in a
subscription, Recast shall create a SubscriptionPost record; its creation time
shall be reused as that item's publication time in subsequent responses.

Evidence: `rc/templates/rss.xml`; `rc.templatetags.rc_tags.subscription_created`.

**FR-019 — Rewrite outbound links.** RSS item links and enclosure URLs shall point
through Recast endpoints that redirect to the imported original post or enclosure
URL. Each item description shall include the original release date and the
subscription settings link.

Evidence: `rc/templates/rss.xml`; `rc.views.post_redirect`;
`rc.views.enclosure_redirect`.

**FR-020 — Support conditional requests.** The personalized feed shall use an ETag
derived from the subscription database identifier and the effective final index.
A matching `If-None-Match` value shall produce HTTP 304.

Evidence: `rc.views.feed`.

**FR-021 — Record feed access.** A feed request shall update the subscription's
last-accessed time, user agent, and last returned status code. User-agent storage
is limited to 512 characters.

Evidence: `rc.views.feed`; `rc.models.Subscription`.

**FR-022 — Apply feed caching.** A successful RSS response shall advertise a
one-hour cache lifetime. A missing, deleted, or fully expired subscription shall
return HTTP 410 and advertise a one-week cache lifetime.

Evidence: `rc.views.feed`.

### Completion lifecycle

**FR-023 — Publish a completion item.** More than two days but less than seven days
after the completion baseline, a completed subscription shall append a synthetic
"Recast is complete" item containing explanatory text and the Recast completion
audio enclosure.

Evidence: `rc.views.feed`.

**FR-024 — Expire a completed feed.** Seven or more days after the completion
baseline, the personalized feed shall return HTTP 410 and record that status on
the subscription.

Evidence: `rc.views.feed`.

### Feed refresh and administration

**FR-025 — Refresh sources operationally.** Deployments may refresh due sources
using the `django-feed-reader` `refreshfeeds` management command. The current web
application also exposes `/refresh/`, which invokes feed updating and returns
plain text.

Evidence: `README.md`; `rc.views.reader`; `recast/urls.py`;
`feeds/management/commands/refreshfeeds.py`.

**FR-026 — Present feed health.** An authenticated user may open Feed Garden to
view sources ordered by next poll time, including subscription count, post count,
poll interval, recent results, and change times.

Evidence: `rc.views.feedgarden`; `rc/templates/feedgarden.html`; confirmed
backfill decision.

**FR-027 — Test and revive sources.** An authenticated user may fetch and inspect
a source's raw content. A POST to the revive endpoint shall mark a source live,
make it due for polling, clear conditional-request metadata, and reset its last
change time.

Evidence: `rc.views.testsource`; `rc.views.revivesource`; confirmed backfill
decision.

**FR-028 — Support Cloudflare-assisted reads.** A source marked as Cloudflare
protected shall be testable through the configured worker. Cloudflare-assisted
initial discovery remains an intended capability.

Evidence: `rc.views.testsource`; configuration in `recast/settings.py`; confirmed
backfill decision.

### Supporting HTTP behavior

**FR-029 — Supply preview metadata.** Middleware shall provide default site title,
description, image, and page URL metadata. Source and settings views shall replace
the title, description, and image when source metadata is available.

Evidence: `rc.middleware.PreviewMiddleware`; `rc/templates/base.html`;
`rc.views.source`; `rc.views.editfeed`.

**FR-030 — Publish crawler and favicon responses.** `/robots.txt` shall disallow
the admin, personalized feeds, and static paths. `/favicon.ico` shall permanently
redirect to the configured static Recast icon.

Evidence: `rc.views.robots`; `rc.views.favicon`.

## Data rules and invariants

### Subscription

- `key` is unique and limited to 64 characters.
- `source` is required; deleting a source cascades to its subscriptions.
- `last_sent` defaults to 1.
- `frequency` is stored as an integer number of days and defaults to 5.
- `last_sent_date` is required and determines the next scheduled release.
- `complete` defaults to false.
- `created` and `last_accessed` are initialized when the record is created.
- `last_return_code` defaults to 0.
- `user_agent` is optional and limited to 512 characters.
- Default ordering is most recently accessed first.

Evidence: `rc.models.Subscription`; `rc/migrations/`.

### SubscriptionPost

- Each record associates one imported Post with one Subscription and records its
  creation time.
- Deleting either related record cascades to the association.
- The current schema does not declare a uniqueness constraint on the post and
  subscription pair.

Evidence: `rc.models.SubscriptionPost`; `rc/migrations/`.

### Source, Post, and Enclosure

Source metadata, polling state, post indices, imported content, and enclosures are
owned by `django-feed-reader`. Recast relies particularly on:

- Source feed/site URLs, display metadata, poll state, `max_index`, `num_subs`,
  Cloudflare status, and the related posts collection;
- Post source, index, title, body, original link, image, author, creation date, and
  enclosures;
- Enclosure original URL, media type, size, and Recast redirect link.

Evidence: `django-feed-reader/feeds/models.py` and
`django-feed-reader/feeds/utils.py` in the adjacent checkout.

## Permissions and security boundaries

- Public users may discover sources, browse source metadata, create subscriptions,
  access key-addressed feeds and settings, and follow redirects.
- Subscription keys function as bearer secrets and appear in URLs.
- Feed Garden, source testing, and source revival require Django authentication.
- Django admin uses Django's normal administration authentication and permissions.
- `/refresh/` is public in the current implementation.
- `addfeed` and `editfeed` are CSRF-exempt in the current implementation; the
  source subscribe and revive forms use Django CSRF protection.
- Feed discovery, testing, and refresh cause server-side outbound HTTP requests to
  source-controlled URLs.

Evidence: decorators and request handling in `rc/views.py`; `recast/urls.py`.

## Integrations and compatibility constraints

- Django provides routing, rendering, persistence, authentication, messages, and
  administration.
- `django-feed-reader` provides source polling and feed-item persistence.
- `feedparser` parses XML feed content.
- Beautiful Soup discovers RSS and Atom links in HTML.
- `requests` performs initial discovery and source tests.
- The Cloudflare SDK optionally purges cache entries.
- A configured Cloudflare worker may proxy protected feed reads.
- Generated absolute public links are HTTPS URLs based on the request host.
- Runtime configuration is imported from `recast.server_settings` and must supply
  the database, secret key, allowed hosts, feed server URL, Cloudflare settings,
  and debug setting described by `README.md` and `recast/settings.py`.

## Meaningful non-functional behavior

- Initial URL discovery uses a 30-second outbound request timeout; source testing
  uses 10 seconds.
- Successful personalized feeds are cacheable for one hour; terminal responses are
  cacheable for one week.
- RSS output uses RSS 2.0 with the iTunes podcast namespace.
- Recast preserves previously observed source posts through `django-feed-reader`,
  allowing later subscriptions to access episodes that have disappeared from the
  current upstream feed.

## Suspected defects and dead behavior

The following observations are not requirements. They should be resolved through
separate defect or enhancement decisions.

**D-001 — Undefined Cloudflare discovery state.** `addfeed` references `cloudflare`
and `proxy` without defining them on relevant paths and does not read the UI's
submitted `cloudflare` value. This appears to break the intended retry workflow.

**D-002 — Missing user-agent handling.** Personalized feed access indexes
`HTTP_USER_AGENT` directly, so clients omitting the header may receive a server
error rather than RSS.

**D-003 — Naive datetimes with time-zone support.** Several writes use
`datetime.datetime.utcnow()` while `USE_TZ` is enabled, risking warnings or
inconsistent comparisons.

**D-004 — Completion does not reopen.** This is confirmed current product intent,
but it means source growth after completion is deliberately ignored by an existing
subscription.

**D-005 — Legacy route likely malformed.** The route labeled `legacy` contains
literal parentheses in a modern Django `path()` expression and may not match the
historical URL it intends to support.

**D-006 — Refresh interface mismatch risk.** Recast calls `update_feeds(response)`,
while the adjacent dependency currently defines its first positional parameter as
`max_feeds` and its output as the second parameter. The deployed dependency version
may differ, but the unpinned requirement makes this uncertain.

**D-007 — Weak local verification.** The only Recast-local test asserts arithmetic
and does not exercise product behavior. No project check command is configured in
`.agent/config.yaml`.

**D-008 — SubscriptionPost duplication is possible.** Application code looks up
an existing association before creating one, but the database does not enforce
uniqueness and concurrent first reads may create duplicates.

**D-009 — Broad exception handling obscures failures.** Feed discovery and several
lookups catch broad exceptions, potentially presenting operational or programming
errors as ordinary discovery failures.

**D-010 — Public refresh endpoint has operational impact.** `/refresh/` can trigger
outbound polling without authentication. This is confirmed as a current
operational endpoint, but its exposure is a security and resource-use boundary.

## Error and edge-case behavior

- Unknown subscription keys return HTTP 410 rather than HTTP 404.
- Unknown source, post, enclosure, or settings records use Django's HTTP 404
  behavior where `get_object_or_404` is used.
- GET requests to `/addfeed/` are denied with HTTP 403.
- A non-POST subscribe or revive request has no explicit response in the view and
  may result in a server error; this is not treated as intended behavior.
- An empty or malformed upstream response may be handled by the general discovery
  exception response.
- A release request beyond the known maximum index is ignored.
- Slow podcast-client polling catches the subscription up to its time-derived
  schedule rather than releasing at most one episode per request.
- Rewinding or skipping changes the release baseline but does not clear the
  subscription's `complete` flag in the current implementation.

## Documentation and verification gaps

- There are no meaningful Recast acceptance, integration, or regression tests.
- The repository does not contain `server_settings.py`, so it cannot run with only
  checked-in configuration.
- The `django-feed-reader` requirement is not constrained in `requirements.in`;
  `requirements.txt` is the only repository evidence of the installed resolution.
- No checked-in deployment definition confirms how `/refresh/` or the management
  command is scheduled in production.
- No accessibility, browser-support, performance target, retention policy, or
  privacy policy is specified.
- The application records subscription access metadata, but no cleanup mechanism
  is present in this repository.

## Evidence inventory

Primary Recast evidence:

- `README.md`
- `recast/settings.py`
- `recast/urls.py`
- `rc/models.py`
- `rc/views.py`
- `rc/middleware.py`
- `rc/templatetags/rc_tags.py`
- `rc/templates/`
- `rc/migrations/`
- `rc/tests.py`
- `requirements.in` and `requirements.txt`

Dependency evidence:

- adjacent `django-feed-reader/feeds/models.py`
- adjacent `django-feed-reader/feeds/utils.py`
- adjacent `django-feed-reader/feeds/management/commands/refreshfeeds.py`

No executable checks were run during backfill because the application requires an
untracked `recast.server_settings` module and the sole local test provides no
product-behavior evidence.

## Clarification record

The following assumptions were explicitly confirmed during specification
backfill and are incorporated above:

- A-001: subscription-key possession grants control;
- A-002: completed subscriptions remain closed;
- A-003: `/refresh/` is an operational endpoint;
- A-004: Cloudflare-assisted discovery is intended;
- A-005: authenticated-user access is sufficient for feed administration tools;
- A-006: the adjacent `django-feed-reader` checkout is the relevant dependency
  reference.

No material assumptions remain unresolved.
