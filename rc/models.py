from django.db import models

# Create your models here.

import time
import datetime
from urllib import urlencode
import logging
import sys
from django.utils.timezone import utc
import email



from django.contrib.auth.models import User


class Source(models.Model):
    # This is an actual feed that we poll
    name           = models.CharField(max_length=255,blank=True,null=True)
    site_url       = models.CharField(max_length=255,blank=True,null=True)
    feed_url       = models.CharField(max_length=255)
    image_url      = models.CharField(max_length=255,blank=True,null=True)
    last_polled    = models.DateTimeField(max_length=255,blank=True,null=True)
    due_poll       = models.DateTimeField()
    etag           = models.CharField(max_length=255,blank=True,null=True)
    last_modified  = models.CharField(max_length=255,blank=True,null=True) # just pass this back and forward between server and me , no need to parse
    
    last_result    = models.CharField(max_length=255,blank=True,null=True)
    interval       = models.PositiveIntegerField(default=400)
    last_success   = models.DateTimeField(null=True)
    last_change    = models.DateTimeField(null=True)
    live           = models.BooleanField(default=True)
    status_code    = models.PositiveIntegerField(default=0)
    last_302_url   = models.CharField(max_length=255,default = " ")
    last_302_start = models.DateTimeField(auto_now_add=True)
    
    max_index      = models.IntegerField(default=0)
    
    num_subs       = models.IntegerField(default=1)
    
    
    def __unicode__(self):
        return self.displayName()
    
    def bestLink(self):
        #the html link else hte feed link
        if self.site_url == None or self.site_url == '':
            return self.feed_url
        else:
            return self.site_url
            
    def displayName(self):
        if self.name == None or self.name == "":
            return self.bestLink()
        else:
            return self.name
            
    def gardenStyle(self):
        
        
        
        if not self.live:
            css="background-color:#ccc;"
        elif self.last_change == None or self.last_success == None:
            css="background-color:#D00;color:white"
        else:
            dd = datetime.datetime.utcnow() - self.last_change
            
            days = int (dd.days/2)
            
            col = 255 - days
            if col < 0: col = 0
            
            css = "background-color:#ff%02x%02x" % (col,col)
            if col < 128:
                css += ";color:white"
            
        return css
        
    def healthBox(self):
        
        if not self.live:
            css="#ccc;"
        elif self.last_change == None or self.last_success == None:
            css="#F00;"
        else:
            dd = datetime.datetime.utcnow() - self.last_change
            
            days = int (dd.days/2)
            
            red = days
            if red > 255:
                red = 255
            
            green = 255-days;
            if green < 0:
                green = 0
            
            css = "#%02x%02x00" % (red,green)
            
        return css
            

# A user subscription
class Subscription(models.Model):

    key            = models.CharField(unique=True,max_length=64)
    source         = models.ForeignKey(Source) 
    last_sent      = models.IntegerField(default=1)
    last_sent_date = models.DateTimeField()
    frequency      = models.IntegerField(default=5) # in days.  A little faster than a week so most podcasts catch up
    name           = models.CharField(max_length=255)
    
    
    def __unicode__(self):
        return u"'%s' on id %s" % (self.name,self.key)
    
    def unreadCount(self):
        if self.source:
            return self.source.max_index - self.last_sent
        else:
            try:
                return self._unreadCount 
            except:
                return -666
                
    @property
    def next_send_date(self):
        roll_date = self.last_sent_date + datetime.timedelta(days=self.frequency)
        return roll_date
                
                
    class Meta:
        ordering = ["-last_sent"]
    
                
class Post(models.Model):
    
    source        = models.ForeignKey(Source,db_index=True)
    title         = models.TextField()
    body          = models.TextField()
    link          = models.CharField(max_length=255,blank=True,null=True)
    found         = models.DateTimeField()
    created       = models.DateTimeField(db_index=True)
    guid          = models.CharField(max_length=255,blank=True,null=True,db_index=True)
    author        = models.CharField(max_length=255,blank=True,null=True)
    index         = models.IntegerField(db_index=True)
    image_url     = models.CharField(max_length=255,blank=True,null=True)

    def _titleURLEncoded(self):
        try:
            ret = urlencode({"X":self.title})
            if len(ret) > 2: ret = ret[2:]
        except:
            logging.info("Failed!")
            logging.info(sys.exc_info())
            ret = ""
        return ret
        
    titleURLEncoded = property(_titleURLEncoded)
    
    @property
    def createdFormatted(self):
        return email.Utils.formatdate(float(self.created.strftime('%s')))
        

    @property
    def recast_link(self):
    
        #if "?" in self.link:
        #    return self.link + ("&recast_id=%d" % self.id)
        #else:
        #    return self.link + ("?recast_id=%d" % self.id)
        
        return "/post/%d/" % self.id
        
    
    def __unicode__(self):
        return "%s: post %d, %s" % (self.source.displayName(),self.index,self.title)

    class Meta:
        ordering = ["index"]

        
class Enclosure(models.Model):
    post   = models.ForeignKey(Post)
    length = models.IntegerField()
    href   = models.CharField(max_length=512)
    type   = models.CharField(max_length=256) 

    @property
    def recast_link(self):
    
        #if "?" in self.href:
        #    return self.href + ("&recast_id=%d" % self.id)
        #else:
        #    return self.href + ("?recast_id=%d" % self.id)

        return "/enclosure/%d/" % self.id


    
class AccessLog(models.Model):
    subscription = models.ForeignKey(Subscription,blank=True,null=True)
    raw_id       = models.CharField(max_length=128)
    access_time  = models.DateTimeField(auto_now_add=True)
    ip_address   = models.CharField(max_length=16)
    user_agent   = models.CharField(max_length=512)
    return_code  = models.IntegerField()
    
    def __unicode__(self):
    
        if self.subscription:
            return "%d @ %s - %s from %s -- %s" % (self.return_code, self.access_time,self.subscription.name,self.ip_address,self.user_agent)
        else:
            return "%d @ %s from %s -- %s" % (self.return_code, self.access_time,self.ip_address,self.user_agent)
            
    class Meta:
        ordering = ["-id"]
