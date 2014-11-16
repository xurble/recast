# Create your views here.

from django.shortcuts import render_to_response,get_object_or_404
from django.contrib.auth import authenticate, login,get_user
from django.http import HttpResponseRedirect,HttpResponse,HttpResponseNotModified
from django.db.models import Q
from django.db.models import F
from django.contrib.auth.decorators import login_required
from django.template import RequestContext
from django.utils.timezone import utc
from django.views.decorators.csrf import csrf_exempt

import datetime
import hashlib
import logging
import sys
import traceback
import uuid

import os

import feedparser

from xml.dom import minidom

from models import *

import time
import datetime

from BeautifulSoup import BeautifulSoup
from urlparse import urljoin
import requests



def index(request):

    vals = {}
    
    if "feed" in request.GET:
        vals["feed"] = request.GET["feed"]

    vals["popular"] = Source.objects.all().order_by("-num_subs")[:10]

    return render_to_response("index.html",vals,context_instance=RequestContext(request))


def help(request):
    return render_to_response("help.html",{},context_instance=RequestContext(request))


def feed(request,key):

    """ This is the actual RSS feed """

    al = AccessLog(raw_id = key,return_code = 404,ip_address = request.META["REMOTE_ADDR"],user_agent=request.META["HTTP_USER_AGENT"])
    al.save()
    sub = get_object_or_404(Subscription,key=key)
    
    al.subscription = sub
    al.return_code = 500
    al.save()
    
    browser_etag = ""
    if "HTTP_IF_NONE_MATCH" in request.META:
        browser_etag = request.META["HTTP_IF_NONE_MATCH"]


    # Check that we shouldn't be adding the next episode

    roll_date = sub.last_sent_date + datetime.timedelta(days=sub.frequency)
    while roll_date < datetime.datetime.utcnow():
        sub.last_sent_date = roll_date
        sub.last_sent = sub.last_sent + 1
        sub.save()
        roll_date = roll_date + datetime.timedelta(days=sub.frequency)

    return_etag = "%d-%d" % (sub.id,sub.last_sent)
    
    if return_etag == browser_etag:
        al.return_code = 304 
        al.save()       
        return HttpResponseNotModified()         
    
    vals = {}
    vals["subscription"] = sub
    vals["source"]  = sub.source
    vals["posts"] = Post.objects.filter(Q(source = sub.source) & Q(index__lte=sub.last_sent)).order_by("index")
    vals["url"] = "http://" + request.META["HTTP_HOST"] + request.path
    vals["base_href"] = "http://" + request.META["HTTP_HOST"]
    
    r = render_to_response("rss.xml",vals,context_instance=RequestContext(request))
    
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
    vals["days"] = range(1,15)
    
    #dd = sub.next_send_date
    #vals["dropdate_year"] = dd.year
    #vals["dropdate_month"] = dd.month - 1
    #vals["dropdate_day"] = dd.day
    #vals["dropdate_hour"] = dd.hour
    #vals["dropdate_minute"] = dd.minute
    #vals["dropdate_second"] = dd.second
    
    if request.method == "POST":
        
        if "release" in request.POST:
            sub.last_sent = sub.last_sent + 1
            sub.last_sent_date = datetime.datetime.utcnow()
        else:
            sub.frequency = int(request.POST["frequency"])
        
        sub.save()
        
    vals["episodes"] = list(sub.source.post_set.filter(index__gt=(sub.last_sent-5)).filter(index__lt=(sub.last_sent+5)))
    

    return render_to_response("feed.html",vals,context_instance=RequestContext(request))
        


def post_redirect(request,pid):

    post = get_object_or_404(Post,id=int(pid))
    
    return HttpResponseRedirect(post.link)


def enclosure_redirect(request,eid):

    enc = get_object_or_404(Enclosure,id=int(eid))
    
    return HttpResponseRedirect(enc.href)
    


def addfeed(request):


    try:
        if request.method == "POST":
    
            feed = request.POST["feed"]
        
            headers = { "User-Agent": "Recast/1.0", "Cache-Control":"no-cache,max-age=0", "Pragma":"no-cache" } #identify ourselves and also stop our requests getting picked up by google's cache

            ret = requests.get(feed, headers=headers)
            #can I be bothered to check return codes here?  I think not on balance
            
            ff = feedparser.parse(ret.content) # are we a feed?
            
            isFeed = (len(ff.entries) > 0)            

            if not isFeed:
            
                soup = BeautifulSoup(ret.content)
                feedcount = 0
                rethtml = ""
                for l in soup.findAll(name='link'):
                    if l.has_key("rel") and l.has_key("type"):
                        if l['rel'] == "alternate" and (l['type'] == 'application/atom+xml' or l['type'] == 'application/rss+xml'):
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
                    
                    sub = Subscription(source=s,key=uuid.uuid4(),name=s.displayName())
                    sub.last_sent_date = datetime.datetime.utcnow()
                    sub.save()                        

                    s.num_subs = s.subscription_set.count()
                    s.save()
                
                    feedLink = "http://%s/feed/%s/" % (request.META["HTTP_HOST"],sub.key)

                    return HttpResponse("""
                        <h2>Success!</h2>
                        
                        <p>Created recast of %s at <a href='%s'>%s</a></p>
                        
                        <p>You can subscribe to this link now in your podcast app, or <a href="%sedit/">or edit the settings here</a>.</p>

                        <p>A link to the recast settings will be added to every episode in case you want to change them in the future.</p>
                        
                        <p>Happy listening!</p>
                        
                        """ % (sub.name,feedLink,feedLink, feedLink))


                # need to start checking feed parser errors here
                ns = Source()
                ns.due_poll = datetime.datetime.utcnow()            
            
                    
                ns.name = feed
                try:
                    ns.htmlUrl = ff.feed.link
                    ns.name = ff.feed.title
                except Exception as ex:
                    pass
                ns.feed_url = feed
                ns.num_subs = 1
                ns.save()

                # import the entries now -  this is currently reparsing the feed which is dumb
                (ok,changed) = importFeed(ns,ret.content)
                
                ns.save()

            
                sub = Subscription(source=ns,key=uuid.uuid4(),name=ns.displayName())
                sub.last_sent_date = datetime.datetime.utcnow()
                
                sub.save()
                
                feedLink = "http://%s/feed/%s/" % (request.META["HTTP_HOST"],sub.key)

                # TODO: this is duplicate code
                return HttpResponse("""
                        <h2>Success!</h2>
                        
                        <p>Created recast of %s at <a href='%s'>%s</a></p>
                        
                        <p>You can subscribe to this link now in your podcast app, or <a href="%sedit/">or edit the settings here</a>.</p>

                        <p>A link to the recast settings will be added to every episode in case you want to change them in the future.</p>
                        
                        <p>Happy listening!</p>
                        
                        """ % (sub.name,feedLink,feedLink, feedLink))
                        
                        
    except Exception as xx:
        return HttpResponse("<div>Error %s: %s</div>" % (xx.__class__.__name__,str(xx)))


def reader(request):

    
    response = HttpResponse()

    response["Content-Type"] = "text/plain"

    sources = Source.objects.filter(Q(due_poll__lt = datetime.datetime.utcnow()) & Q(live = True))[:3]

    response.write("Update Q: %d\n\n" % sources.count())
    for s in sources:
        
        was302 = False
        
        response.write("\n\n------------------------------\n\n")
        
        s.last_polled = datetime.datetime.utcnow()
        #newCount = s.unreadCount
    
        interval = s.interval
    
        headers = { "User-Agent": "Recast/1.0 at %s (%d subscribers)" % (request.META["HTTP_HOST"],s.num_subs), "Cache-Control":"no-cache,max-age=0", "Pragma":"no-cache" } #identify ourselves and also stop our requests getting picked up by google's cache
        if s.etag:
            headers["If-None-Match"] = str(s.etag)
        if s.last_modified:
            headers["If-Modified-Since"] = str(s.last_modified)
        response.write(headers)
        ret = None
        response.write("\nFetching %s" % s.feed_url)
        try:
            ret = requests.get(s.feed_url,headers=headers,allow_redirects=False)
            s.status_code = ret.status_code
            s.last_result = "Unhandled Case"
        except Exception as ex:
            print ex
            s.last_result = "Fetch error:" + str(ex)
            s.status_code = 0
            response.write("\nFetch error: " + str(ex))
        
        if ret:
            response.write("\nResult: %d" % ret.status_code)
                    
        if ret == None or s.status_code == 0:
            interval += 120
        elif ret.status_code < 200 or ret.status_code >= 500:
            #errors, impossible return codes
            interval += 120
            s.last_result = "Server error fetching feed (%d)" % ret.status_code
        elif ret.status_code == 404:
            #not found
            interval += 120
            s.last_result = "The feed could not be found"
        elif ret.status_code == 403 or ret.status_code == 410: #Forbidden or gone
            s.live = False
            s.last_result = "Feed is no longer accessible (%d)" % ret.status_code
        elif ret.status_code >= 400 and ret.status_code < 500:
            #treat as bad request
            s.live = False
            s.last_result = "Bad request (%d)" % ret.status_code
        elif ret.status_code == 304:
            #not modified
            interval += 5
            s.last_result = "Not modified"
            #s.last_success = datetime.datetime.utcnow() #in case we start auto unsubscribing long dead feeds
            
            if (datetime.datetime.utcnow() - s.last_success).days > 7:
                s.last_result = "Clearing etag/last modified due to lack of changes"
                s.etag = None
                s.last_modified = None
        
        elif ret.status_code == 301: #permenant redirect
            try:

                newURL = ret.headers["Location"]
                
                if newURL[0] == "/":
                    #find the domain from the feed
                    start = s.feed_url[:8]
                    end = s.feed_url[8:]
                    if end.find("/") >= 0:
                        end = end[:end.find("/")]
                    
                    newURL = start + end + newURL


                s.feed_url = newURL
                
                s.last_result = "Moved"
            except exception as Ex:
                response.write("error redirecting")
                s.last_result = "Error redirecting feed"
                interval += 60
                pass
        elif ret.status_code == 302 or ret.status_code == 303 or ret.status_code == 307: #Temporary redirect
            newURL = ""
            was302 = True
            try:
                newURL = ret.headers["Location"]
                
                if newURL[0] == "/":
                    #find the domain from the feed
                    start = s.feed_url[:8]
                    end = s.feed_url[8:]
                    if end.find("/") >= 0:
                        end = end[:end.find("/")]
                    
                    newURL = start + end + newURL
                    
                
                ret = requests.get(newURL,headers=headers,allow_redirects=True)
                s.status_code = ret.status_code
                s.last_result = "Temporary Redirect to " + newURL

                
                if s.last_302_url == newURL:
                    #this is where we 302'd to last time
                    td = datetime.datetime.utcnow() - s.last_302_start
                    if td > datetime.timedelta(days=60):
                        s.feed_url = newURL
                        s.last_302_url = " "

                else:
                    s.last_302_url = newURL
                    s.last_302_start = datetime.datetime.utcnow()

                s.last_result = "Temporary Redirect to " + newURL + " since " + s.last_302_start.strftime("%d %B")


            except Exception as ex:     
                s.last_result = "Failed Redirection to " + newURL
                interval += 60
        
        #NOT ELIF, WE HAVE TO START THE IF AGAIN TO COPE WTIH 302
        if ret and ret.status_code >= 200 and ret.status_code < 300: #now we are not following redirects 302,303 and so forth are going to fail here, but what the hell :)

            # great!
            
            ok = True
            changed = False 
            
            if was302:
                s.etag = None
                s.last_modified = None
            else:
                try:
                    s.etag = ret.headers["ETag"]
                except Exception as ex:
                    s.etag = None                                   
                try:
                    s.last_modified = ret.headers["Last-Modified"]
                except Exception as ex:
                    s.last_modified = None                                   
            
            response.write("\nEtag:%s\nLast Mod:%s\n\n" % (s.etag,s.last_modified))
            
            
            (ok,changed) = importFeed(source=s,feedBody=ret.content,response=response)
            
            
            if ok and changed:
                interval /= 2
                s.last_result = " OK (updated)" #and temporary redirects
                s.last_change = datetime.datetime.utcnow()
                
            elif ok:
                s.last_result = "OK"
                interval += 10 # we slow down feeds a little more that don't send headers we can use
            else: #not OK
                interval += 120
                
            #s.unreadCount = newCount
        

        #else:
        #   #should not be able to get here
        #   oops = "Gareth can't program! %d" % ret.status_code
        #   logging.error(oops)
        #   s.last_result = oops
            
        
        if interval < 60:
            interval = 60 #no less than 1 hour
        if interval > (60 * 60 * 24 * 3):
            interval = (60 * 60 * 24 * 3) #no more than 3 days
        
        response.write("\nUpdating interval from %d to %d\n" % (s.interval,interval))
        s.interval = interval
        td = datetime.timedelta(minutes=interval)
        s.due_poll = datetime.datetime.utcnow() + td
        s.save()
        
        response.write("Done")
    return response
    

def importFeed(source,feedBody,response=None):

    changed = False

    #response.write(ret.content)           
    try:
        f = feedparser.parse(feedBody) #need to start checking feed parser errors here
        entries = f['entries']
        if len(entries):
            source.last_success = datetime.datetime.utcnow() #in case we start auto unsubscribing long dead feeds
        else:
            source.last_result = "Feed is empty"
            
            return (False,False)

    except Exception as ex:
        source.last_result = "Feed Parse Error"
        entries = []
        return (False,False)
        
    try:
        source.site_url = f.feed.link
        source.name = f.feed.title
    except Exception as ex:
        pass
        
    try:
        source.image_url = f.feed.image.href
    except:
        pass
    

    #response.write(entries)
    entries.reverse() # Entries are typically in reverse chronological order - put them in right order
    for e in entries:
        try:
            body = e.content[0].value
        except Exception as ex:
            try:
                body = e.description
            except Exception as ex:
                body = " "


        try:
            guid = e.guid
        except Exception as ex:
            try:
                guid = e.link
            except Exception as ex:
                m = hashlib.md5()
                m.update(body.encode("utf-8"))
                guid = m.hexdigest()
                    
        try:
            p  = Post.objects.filter(source=s).filter(guid=guid)[0]
            if response: response.write("EXISTING " + guid + "\n")

        except Exception as ex:
            if response: response.write("NEW " + guid + "\n")
            p = Post(index=0)
            p.found = datetime.datetime.utcnow()
            p.created = datetime.datetime.utcnow()
            changed = True
            p.source = source
            p.save()
    
        try:
            title = e.title
        except Exception as ex:
            title = "No title"
                        
        try:
            p.link = e.link
        except Exception as ex:
            p.link = ''
        p.title = title
        #tags = [t["term"] for t in e.tags]
        #link.tags = ",".join(tags)

        try:
            p.image_url = e.image.href
        except:
            pass


        try:
        
            p.created  = datetime.datetime.fromtimestamp(time.mktime(e.date_parsed))
            # p.created  = datetime.datetime.utcnow()
        except Exception as ex:
            if response: response.write("CREATED ERROR")     
            p.created  = datetime.datetime.utcnow()
        
        # response.write("CC %s \n" % str(p.created))
        
        p.guid = guid
        try:
            p.author = e.author
        except Exception as ex:
            p.author = ""
        
        for ee in list(p.enclosure_set.all()):
            # check existing enclosure is still there
            found_enclosure = False
            for pe in e["enclosures"]:
                if pe["href"] == ee.href:
                    found_enclosure = True
                    pe["href"] = "X" # don't re-add in hte second pass
                    ee.length = int(pe["length"])
                    ee.type = pe["type"]
                    ee.save()
                    break
            if not found_enclosure:
                ee.delete()

        for pe in e["enclosures"]:
            try:
                if pe["href"] != "X":
                    ee = Enclosure(post = p , href = pe["href"], length = int(pe["length"]), type = pe["type"])
                    ee.save()
            except Exception as ex:
                pass

        try:
            p.body = body                       
            p.save()
            # response.write(p.body)
        except Exception as ex:
            #response.write(str(sys.exc_info()[0]))
            if response: 
                response.write("\nSave error for post:" + str(sys.exc_info()[0]))
                traceback.print_tb(sys.exc_traceback,file=response)


    if changed:
        idx = source.max_index
        # give indices to posts based on created date
        posts = Post.objects.filter(Q(source=source) & Q(index=0)).order_by("created")
        for p in posts:
            idx += 1
            p.index = idx
            p.save()
        
        source.max_index = idx

            
    return (True,changed)
    


