Recast
======

Recast is a django based podcast feed rebroadcaster.  There is a running version at http://recastthis.com if you want to try it out.

Recast is designed to make it convenient to listen to all the old episodes of a podcast from the beginning.

Most podcast clients will only automatically present the latest episode of a podcast and leave you to manually download previous episodes one by one, eliminating the convenience of automatic delivery.

Instead of subscribing directly to the podcast, you give Recast the address of the website or feed of the podcast and it will return you a unique, personalized feed. Simply subscribe to the Recast feed instead.

By default Recast will feed you a new episode of the podcast every five days - enough to slowly catch up with most weekly podcasts. At any time, you can change the frequency new episodes are released, or just release the next episode.

Installation
============

Recast is a pretty simple django (2.2) application.  The only external dependencies are requests and python-mysql.

Once it is running, in order to keep it ticking over and reading feeds, something needs to keep hitting /refresh/

I have that set up as a cron job using curl that fires every five minutes.  This is a cheesy way to work around the severe lameness of my current hosting.

If you were to run it on something sensible, you'd probably want to use Celery or similar.

And that's it.

