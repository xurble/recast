# Create your views here.

from django.shortcuts import get_object_or_404, render
from django.http import HttpResponseRedirect, HttpResponse, HttpResponseNotModified, JsonResponse, HttpResponsePermanentRedirect
from django.db.models import Q, F
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from feeds.utils import update_feeds, import_feed, get_proxy
from django.urls import reverse
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils.cache import patch_response_headers

import CloudFlare

import datetime 
import hashlib
import logging
import sys
import traceback
import uuid
import email

import os

import feedparser

#from xml.dom import minidom

from .models import *

import time
import datetime

from bs4 import BeautifulSoup
from urllib.parse import urljoin
import requests


 
def index(request):

    vals = {}
    
    if "feed" in request.GET:
        vals["feed"] = request.GET["feed"]

    vals["popular"] = Source.objects.exclude(image_url=None).order_by("?")[:6]
    
    return render(request, "index.html",vals)

    

def help(request):

    return render(request, "help.html",{} )

    
def robots(request):
    
    r = HttpResponse("""    
User-agent: *
Disallow: /admin/
Disallow: /feed/
Disallow: /static/
    """)
    
    r["Content-Type"] = "text/plain"
    
    return r
    
def favicon(request):
    return HttpResponsePermanentRedirect('/static/images/recast-small.png')



def feed(request,key):

    """ This is the actual RSS feed """

    
    right_now = timezone.now()
    
    try:
        sub = Subscription.objects.get(key=key)
    except:

        # give cloudflare something to work with
        patch_response_headers(r, cache_timeout=(60 * 60 * 24 * 7))  # A week


        r = HttpResponse("And like that, he's gone.", status=410)  # let's assume that a feed that doesn't exist has been deleted
        return r                               # I mean it could be mistype, but most likely not.
          
    sub.last_return_code = 500
    sub.last_accessed = right_now
    sub.user_agent = request.META["HTTP_USER_AGENT"][:512]
    sub.save()

    
    browser_etag = ""
    if "HTTP_IF_NONE_MATCH" in request.META:
        browser_etag = request.META["HTTP_IF_NONE_MATCH"]
        
    final_post = []


    if not sub.complete:
    
        # Check that we shouldn't be adding the next episode

    
        # hmm this will catch us up to the original schedule even for very slow pollers
        # would it be better to just send one episode new max ? 
        # doesn't affect me personally as Overcast has a hyper-agressive server side poller :)
        roll_date = sub.last_sent_date + datetime.timedelta(days=sub.frequency)
        while sub.last_sent < sub.source.max_index and roll_date < right_now:
            sub.last_sent_date = roll_date
            sub.last_sent = sub.last_sent + 1 
            roll_date = roll_date + datetime.timedelta(days=sub.frequency)


        if sub.last_sent == sub.source.max_index:
            sub.complete = True

        last_sent = sub.last_sent
    else: 
      
        # sub has finished
        # wait two days then send feed closed message for 5 days.
        # then send GONE
        last_sent = sub.last_sent
        if (right_now - sub.last_sent_date).days > 2:
            if (right_now - sub.last_sent_date).days < 7:
                last_sent += 1
                final_post = [
                    {
                        "title": "Recast is complete",
                        "recast_link":  "/",
                        "author": "Recast",
                        "created_for_subscription": email.Utils.formatdate(float(sub.last_sent_date.strftime('%s')))  , 
                        "body":  "This Recast has come to an end.  If you have not already done so, you can get a link to the original source podcast feed from the settings link above.  You should subscribe to the original to continue listening to further episodes.  We hope you enjoyed using Recast.",
                        "id": "fin!",
                        "enclosures" : {"all": [ {"recast_link":  "/static/audio/end.mp3",
                                                    "length": 94875,
                                                    "type": "audio/mpeg"  } ] },
                        "image_url": "http://" + request.META["HTTP_HOST"] + "/static/images/recast-large.png" ,
                        "sub" : sub                       
                    }
                ]
            else:
                # this sub is dead and gone and waiting for deletion
                sub.last_return_code = 410    
                sub.save()


                r = HttpResponse("And like that, he's gone.", status=410)  

                # give cloudflare something to work with
                patch_response_headers(r, cache_timeout=(60 * 60 * 24 * 7))  # A week

                return r                               

            
        
    return_etag = '"%d-%d"' % (sub.id, last_sent)
    
    if return_etag == browser_etag:
        sub.last_return_code = 304 
        sub.save()       
        return HttpResponseNotModified()         

    
    vals = {}
    vals["subscription"] = sub
    vals["source"]  = sub.source
    vals["posts"] = list(Post.objects.filter(Q(source = sub.source) & Q(index__lte=sub.last_sent)).order_by("index")) 
    
    for p in vals["posts"]:            #so that PostSubscription works
        p.current_subscription = sub
    
    
    vals["posts"] += final_post
    
    vals["url"] = "https://" + request.META["HTTP_HOST"] + request.path
    vals["base_href"] = "https://" + request.META["HTTP_HOST"]
    
    r = render(request, "rss.xml", vals)
    
    #r["ETag"] = 'W/' + return_etag
    r["Content-Type"] = "application/rss+xml"

    sub.last_return_code = 200 
    sub.save()
    
    # give cloudflare something to work with
    patch_response_headers(r, cache_timeout=(60 * 60))

    return r
    
    
@csrf_exempt
def editfeed(request, key):
    
    sub = get_object_or_404(Subscription, key=key)
    vals = {}
    
    vals["subscription"] = sub
    vals["days"] = list(range(1,15))
    
    
    if request.method == "POST":
        
        if "release" in request.POST:
            if sub.last_sent < sub.source.max_index:
                sub.last_sent = sub.last_sent + 1
                sub.last_sent_date = datetime.datetime.utcnow()

                if settings.CLOUDFLARE_TOKEN:
                    import pdb; pdb.set_trace()
                
                    domain = request.META["HTTP_HOST"]
                    
                    domain = "recastthis.com"
                    
                    url = 'https://{}{}'.format(domain, reverse("feed", args=[key]))
                    
                    
                    cf = CloudFlare.CloudFlare(token=settings.CLOUDFLARE_TOKEN)

                    r = cf.zones.purge_cache.post(
                                settings.CLOUDFLARE_ZONE, 
                                data={'files': [
                                    url,
                                ]                                
                            })




        else:
            sub.frequency = int(request.POST["frequency"])
        
        sub.save()
        
    vals["episodes"] = list(sub.source.posts.filter(index__gt=(sub.last_sent-5)))
    
    vals["host"] = request.META["HTTP_HOST"]
    

    return render(request,"feed.html",vals)
        


def post_redirect(request,pid):

    post = get_object_or_404(Post,id=int(pid))
    
    return HttpResponseRedirect(post.link)


def enclosure_redirect(request,eid):

    enc = get_object_or_404(Enclosure,id=int(eid))
    
    return HttpResponseRedirect(enc.href)


@login_required
def feedgarden(request):
    vals = {}
    vals["feeds"] = Source.objects.all().order_by("due_poll")
    return render(request,'feedgarden.html',vals)
    
    
@login_required
def revivesource(request,sid):

    if request.method == "POST":
        
        s = get_object_or_404(Source,id=int(sid))
        
        s.live          = True
        s.due_poll      = datetime.datetime.utcnow()
        s.etag          = None
        s.last_modified = None
        s.last_change   = datetime.datetime.utcnow()
        
        s.save()
        
        return HttpResponse("OK")
        

def source(request,sid):
    
    vals = {}
    vals["source"] = get_object_or_404(Source,id=int(sid))
    return render(request, 'source.html',vals)


@csrf_exempt
def addfeed(request):

    proxy = None

    if request.method == "GET":
        raise PermissionDenied()
    elif request.method == "POST":
        try:
            
            source = None
            proxies = None
    
            feed = request.POST["feed"]
            cloudflare = request.POST.get("cloudflare", "no")
            if cloudflare == "yes":
                try:
                    proxy = get_proxy()
    
                    if proxy.address != "X":
    
                        proxies = {
                          'http': "http://" + proxy.address,
                          'https': "https://" + proxy.address,
                        }
                except Exception as ex:
                    pass    

            
            if request.META["HTTP_HOST"] in feed:
                return HttpResponse("<h2>Subscription Error</h2>You cannot recast a Recast feed!")

            try:
                source = Source.objects.filter(feed_url__iexact = feed)[0]
            except Exception  as ex:
                try:
                    source = Source.objects.filter(site_url__iexact = feed)[0]
                except Exception  as ex2:
                    pass
                    
            isFeed = False
            if source is None:
                
                headers = { "User-Agent": "{} (+{}; Initial Feed Crawler)".format(settings.FEEDS_USER_AGENT, settings.FEEDS_SERVER), "Cache-Control":"no-cache,max-age=0", "Pragma":"no-cache" } #identify ourselves and also stop our requests getting picked up by google's cache

                ret = requests.get(feed, headers=headers, proxies=proxies, timeout=30)
                #can I be bothered to check return codes here?  I think not on balance
                
                if ret.status_code == 200:

                    content_type = "Not Set"
                    if "Content-Type" in ret.headers:
                        content_type = ret.headers["Content-Type"]
                
                    feed_title = feed
             
                    body = ret.text.strip()
                    if "xml" in content_type or body[0:1] == "<":
                        ff = feedparser.parse(body) # are we a feed?
                        isFeed = (len(ff.entries) > 0) 
                        if isFeed:
                            feed_title = ff.feed.title
                    if "json" in content_type or body[0:1] == "{":
                        data = json.loads(body)
                        isFeed = "items" in data and len(data["items"]) > 0
                        if isFeed:
                            feed_title = data["title"]

                    if not isFeed:
            
                        soup = BeautifulSoup(body)
                        feedcount = 0
                        rethtml = ""
                        for l in soup.findAll(name='link'):
                            if l.has_attr("rel") and l.has_attr("type"):
                                print(l)
                                if l['rel'][0] == "alternate" and (l['type'] == 'application/atom+xml' or l['type'] == 'application/rss+xml'):
                                    feedcount += 1
                                    try:
                                        name = l['title']
                                    except Exception as ex:
                                        name = "Feed %d" % feedcount
                                    rethtml += '<li><form method="post" action="/addfeed/"> <input type="hidden" name="cloudflare" value="%s"><input type="hidden" name="feed" value="%s"><input type="submit" class="btn btn-success btn-xs" value="Recast"> - %s</form></li>' % (cloudflare, urljoin(feed,l['href']) ,name)
                                    feed = urljoin(feed,l['href']) # store this in case there is only one feed and we wind up importing it
                                    #TODO: need to accout for relative URLs here
                        #if feedcount == 1:
                            #just 1 feed found, let's import it now
                
                        #   ret = fetch(f)
                        #   isFeed = True
                        if feedcount == 0:
                            return HttpResponse("<h2>No feeds found</h2>")
                        else:
                            return HttpResponse("<h2>Available Feeds</h2><ul id='addfeedlist' class='feedlist'>" + rethtml + "</ul>")
                elif ret.status_code == 403:
                    if cloudflare == "no":
                        if "Cloudflare" in ret.text or ("Server" in ret.headers and "cloudflare" in ret.headers["Server"]):
                            return JsonResponse({"ok": False, "reason": "cloudflare", "msg": "Attempt to get podcast blocked by Cloudflare. 😡  If you want to try again, we know some tricks that might work."})
                    
                    if proxy:
                        proxy.delete()
                    
                    
                    return JsonResponse({"ok": False, "reason": "403", "msg": "Recast was blocked from accessing the podcast."})
                else:
                    return JsonResponse({"ok": False, "reason": str(ret.status_code), "msg": "Recast could note access the podcast, please check the link and try again."})
                    
                
            if isFeed and source is None:

                # need to start checking feed parser errors here
                source = Source()
                source.due_poll = datetime.datetime.utcnow()            
    
            
                source.name = feed
                try:
                    source.site_url = ff.feed.link
                    source.name = ff.feed.title
                except Exception as ex:
                    pass
                source.feed_url = feed
                source.num_subs = 0
                source.save()
        

                # import the entries now
                (ok,changed) = import_feed(source, ret.content, content_type)
        
            # TODO: Check the OK return val?  Surely that's a good idea
        
                source.last_change = datetime.datetime.utcnow()
        
                source.save()

            if request.POST.get("ajax", "nope") == "yep":
                return JsonResponse({"ok": True, "feed": reverse("source", args=[source.id])})            
            else:
                return HttpResponseRedirect(reverse("source", args=[source.id]))          
                        
        except Exception as xx:
            if proxy:
                proxy.delete()
            return JsonResponse({"ok": False, "reason": str(xx), "msg": "Recast could not connect to the podcast server.  You can try again, it might work 🤷‍."})
        
        
def subscribe(request, sid):

    if request.method == "POST":
        s = get_object_or_404(Source,   id=int(sid))

        sub = Subscription(source=s,key=uuid.uuid4(),name=s.display_name)
        sub.last_sent_date = datetime.datetime.utcnow()
        sub.save()                        

        s.num_subs = s.subscription_set.count()
        s.save()
        
        messages.success(request, "Your new Recast feed has been created - subscribe to the link below in your Podcast App.")

        return HttpResponseRedirect(reverse("editfeed", args=[sub.key]))


def reader(request):
    
    response = HttpResponse()

    response["Content-Type"] = "text/plain"

    update_feeds(response)

    return response
    

