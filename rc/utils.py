from django.db.models import Q
import requests
from rc.models import Source, Enclosure, Post
import datetime
import time
import hashlib 
from django.conf import settings
import feedparser


def update_feeds(response, max_feeds=3):

    todo = Source.objects.filter(Q(due_poll__lt = datetime.datetime.utcnow()) & Q(live = True))
    
    if response: response.write("Queue size is {}".format(todo.count()))

    sources = todo.order_by("due_poll")[:max_feeds]

    
    if response: response.write("\nProcessing %d\n\n" % sources.count())
    for s in sources:
        
        was302 = False
        
        if response: response.write("\n\n------------------------------\n\n")
        
        s.last_polled = datetime.datetime.utcnow()
        #newCount = s.unreadCount
    
        interval = s.interval
    
        headers = { "User-Agent": "Recast/1.1 (+http://%s; Updater; %d subscribers)" % (settings.ALLOWED_HOSTS[0], s.num_subs), "Cache-Control":"no-cache,max-age=0", "Pragma":"no-cache" } #identify ourselves and also stop our requests getting picked up by google's cache
        if s.etag:
            headers["If-None-Match"] = str(s.etag)
        if s.last_modified:
            headers["If-Modified-Since"] = str(s.last_modified)
        # if response: response.write(headers)
        ret = None
        if response: response.write("\nFetching %s" % s.feed_url)
        
        try:
            ret = requests.get(s.feed_url,headers=headers,allow_redirects=False,  timeout=30)
            s.status_code = ret.status_code
            s.last_result = "Unhandled Case"
            if response: response.write("\nFetched: " + str(ret))
        except Exception as ex:
            s.last_result = "Fetch error:" + str(ex)
            s.status_code = 0
            if response: response.write("\nFetch error: " + str(ex))
        
        if ret:
            if response: response.write("\nResult: %d" % ret.status_code)
                    
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

            if "Cloudflare" in ret.text or ("Server" in ret.headers and "cloudflare" in ret.headers["Server"]):
                s.is_cloudflare = True
                s.last_result = "Feed is protected by Cloudflare (%d)" % ret.status_code
            else:
                s.last_result = "Feed is no longer accessible (%d)" % ret.status_code

            s.live = False
            
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
                if response: response.write("error redirecting")
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
                    
                ret = requests.get(newURL,headers=headers,allow_redirects=True, timeout=30)
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
            
            if response: response.write("\nEtag:%s\nLast Mod:%s\n\n" % (s.etag,s.last_modified))
            
            (ok,changed) = importFeed(source=s, feedBody=ret.text, response=response)
            
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
            
        
        if interval < 160:
            interval = 120 # no less than 2 hours
        if interval > (60 * 24):
            interval = (60 * 24) # no more than a day
        
        if response: response.write("\nUpdating interval from %d to %d\n" % (s.interval,interval))
        s.interval = interval
        td = datetime.timedelta(minutes=interval)
        s.due_poll = datetime.datetime.utcnow() + td
        s.save()
        
    if response: response.write("Done")
        
        
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
        body  = ""
        try:
            body = e.description
        except Exception as ex:
            pass
        if body == "":
            try:
                body = e.summary
            except Exception as ex:
                pass
            if body == "":
                try:
                    body = e.content[0].value
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
            p  = Post.objects.filter(source=source).filter(guid=guid)[0]
            if response: response.write("EXISTING {}/{}\n".format(p.id,  guid))

        except Exception as ex:
            if response: response.write("NEW " + guid + "\n")
            p = Post(index=0)
            p.found = datetime.datetime.utcnow()
            p.created = datetime.datetime.utcnow()
            p.guid = guid
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
        
            p.created  = datetime.datetime.fromtimestamp(time.mktime(e.published_parsed)) 
            # p.created  = datetime.datetime.utcnow()
        except Exception as ex:
            if response: response.write("CREATED ERROR - ")     
            p.created  = datetime.datetime.utcnow()
        
        # response.write("CC %s \n" % str(p.created))
        
        try:
            p.author = e.author
        except Exception as ex:
            p.author = ""
        
        try:
            seen_files = []
            for ee in list(p.enclosure_set.all()):
                # check existing enclosure is still there
                found_enclosure = False
                for pe in e["enclosures"]:
                    
                    if pe["href"] == ee.href and ee.href not in seen_files:
                        found_enclosure = True
                        
                        try:
                            ee.length = int(pe["length"])
                        except:
                            ee.length = 0

                        try:
                            type = pe["type"]
                        except:
                            type = "audio/mpeg"

                        ee.type = type
                        ee.save()
                        break
                if not found_enclosure:
                    ee.delete()
                seen_files.append(ee.href)
    
            for pe in e["enclosures"]:
                try:
                    if pe["href"] not in seen_files:
                    
                        try:
                            length = int(pe["length"])
                        except:
                            length = 0
                            
                        try:
                            type = pe["type"]
                        except:
                            type = "audio/mpeg"
                    
                        ee = Enclosure(post = p , href = pe["href"], length = length, type = type)
                        ee.save()
                except Exception as ex:
                    pass
        except Exception as ex:
            if response:
                response.write("No enclosures - " + str(ex))

        try:
            p.body = body.encode("UTF-8")                   
            p.save()
            # response.write(p.body)
        except Exception as ex:
            #response.write(str(sys.exc_info()[0]))
            if response: 
                response.write("\nSave error for post:" + str(ex))


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
    


