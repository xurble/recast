# Create your views here.

from django.shortcuts import get_object_or_404, render
from django.contrib.auth import authenticate, login,get_user
from django.http import HttpResponseRedirect,HttpResponse,HttpResponseNotModified,HttpResponseForbidden
from django.db.models import Q
from django.db.models import F
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from feeds.utils import update_feeds, import_feed

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



def feed(request,key):

    """ This is the actual RSS feed """

    
    right_now = timezone.now()

    al = AccessLog(raw_id = key,return_code = 410,ip_address = request.META["REMOTE_ADDR"],user_agent=request.META["HTTP_USER_AGENT"])
    al.save()
    try:
        sub =Subscription.objects.get(key=key)
    except:
        return HttpResponse(status=410)  # let's assume that a feed that doesn't exist has been deleted
                                         # I mean it could be mistype, but most likely not.
          
    al.subscription = sub
    al.return_code = 500
    al.save()
    
    sub.last_accessed = right_now

    
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
                        "enclosure_set" : {"all": [ {"recast_link":  "/static/audio/end.mp3",
                                                    "length": 94875,
                                                    "type": "audio/mpeg"  } ] },
                        "image_url": "http://" + request.META["HTTP_HOST"] + "/static/images/recast-large.png" ,
                        "sub" : sub                       
                    }
                ]
            else:
                # this sub is dead and gone and waiting for deletion
                sub.save()
                al.return_code = 410    
                al.save()

                return HttpResponse(status=410)
            
        

    sub.save()

    return_etag = "%d-%d" % (sub.id,last_sent)
    
    if return_etag == browser_etag:
        al.return_code = 304 
        al.save()       
        return HttpResponseNotModified()         
    
    vals = {}
    vals["subscription"] = sub
    vals["source"]  = sub.source
    vals["posts"] = list(Post.objects.filter(Q(source = sub.source) & Q(index__lte=sub.last_sent)).order_by("index")) 
    
    for p in vals["posts"]:            #so that PostSubscription works
        p.current_subscription = sub
    
    
    vals["posts"] += final_post
    
    vals["url"] = "http://" + request.META["HTTP_HOST"] + request.path
    vals["base_href"] = "http://" + request.META["HTTP_HOST"]
    
    r = render(request, "rss.xml",vals)
    
    r["ETag"] = return_etag
    #r["Content-Type"] = "text/plain"
    r["Content-Type"] = "application/rss+xml"

    al.return_code = 200 
    al.save()      
    
     


    return r
    
@csrf_exempt
def editfeed(request,key):
    
    sub = get_object_or_404(Subscription,key=key)
    vals = {}
    
    vals["subscription"] = sub
    vals["days"] = list(range(1,15))
    
    
    if request.method == "POST":
        
        if "release" in request.POST:
            if sub.last_sent < sub.source.max_index:
                sub.last_sent = sub.last_sent + 1
                sub.last_sent_date = datetime.datetime.utcnow()
        else:
            sub.frequency = int(request.POST["frequency"])
        
        sub.save()
        
    vals["episodes"] = list(sub.source.post_set.filter(index__gt=(sub.last_sent-5)))
    

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


def addfeed(request):

    try:
        if request.method == "GET":
            return HttpResponseForbidden("No!")  # TODO: PermissionDenied
        elif request.method == "POST":
    
            feed = request.POST["feed"]
            
            if request.META["HTTP_HOST"] in feed:
                return HttpResponse("<h2>Subscription Error</h2>You cannot recast a Recast feed!")
                
        
            headers = { "User-Agent": "{} (+{}; Initial Feed Crawler)".format(settings.FEEDS_USER_AGENT, settings.FEEDS_SERVER), "Cache-Control":"no-cache,max-age=0", "Pragma":"no-cache" } #identify ourselves and also stop our requests getting picked up by google's cache

            ret = requests.get(feed, headers=headers, timeout=30)
            #can I be bothered to check return codes here?  I think not on balance
            
            isFeed = False  

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
                            rethtml += '<li><form method="post" onsubmit="return false;"> <input type="hidden" name="feed" id="feed-%d" value="%s"><a href="#" onclick="addFeed(%d)" class="btn btn-success">Subscribe</a> - %s</form></li>' % (feedcount,urljoin(feed,l['href']),feedcount,name)
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
                
            if isFeed:

                s = Source.objects.filter(feed_url = feed)
                if s.count() > 0:
                    #feed already exists  # create a subscription to it
                    s = s[0]
                    
                    sub = Subscription(source=s,key=uuid.uuid4(),name=s.display_name)
                    sub.last_sent_date = datetime.datetime.utcnow()
                    sub.save()                        

                    s.num_subs = s.subscription_set.count()
                    s.save()
                
                    feedLink = "http://%s/feed/%s/" % (request.META["HTTP_HOST"],sub.key)

                    return HttpResponse("""
                        <h2>Success!</h2>
                        
                        <p>Here is your Recast of %s: <a href='%s'>%s</a></p>
                        
                        <p>You can subscribe to this link now in any podcast app.</p>

                        <p>A link to the Recast settings will be added to every episode in case you want to change them in the future.</p>
                        
                        <p><a href="%sedit/">Or you can change them right now.</a></p>
                        
                        <p>Happy listening!</p>
                        
                        """ % (sub.name,feedLink,feedLink, feedLink))


                # need to start checking feed parser errors here
                ns = Source()
                ns.due_poll = datetime.datetime.utcnow()            
            
                    
                ns.name = feed
                try:
                    ns.html_url = ff.feed.link
                    ns.name = ff.feed.title
                except Exception as ex:
                    pass
                ns.feed_url = feed
                ns.num_subs = 1
                ns.save()
                

                # import the entries now -  this is currently reparsing the feed which is dumb
                (ok,changed) = import_feed(ns,ret.content, content_type)
                
                # TODO: Check the OK return val?  Surely that's a good idea
                
                ns.last_change = datetime.datetime.utcnow()
                
                ns.save()

            
                sub = Subscription(source=ns,key=uuid.uuid4(),name=ns.display_name)
                sub.last_sent_date = datetime.datetime.utcnow()
                
                sub.save()
                
                feedLink = "http://%s/feed/%s/" % (request.META["HTTP_HOST"],sub.key)

                # TODO: this is duplicate code
                return HttpResponse("""
                        <h2>Success!</h2>
                        
                        <p>Here is your Recast of %s: <a href='%s'>%s</a></p>
                        
                        <p>You can subscribe to this link now in any podcast app.</p>

                        <p>A link to the Recast settings will be added to every episode in case you want to change them in the future.</p>
                        
                        <p><a href="%sedit/">Or you can change them right now.</a></p>
                        
                        <p>Happy listening!</p>
                        
                        """ % (sub.name,feedLink,feedLink, feedLink))
                        
                        
    except Exception as xx:
        return HttpResponse("<div>Error %s: %s</div>" % (xx.__class__.__name__,str(xx)))


def reader(request):
    
    response = HttpResponse()

    response["Content-Type"] = "text/plain"

    update_feeds(response)

    return response
    

