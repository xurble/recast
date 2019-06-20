from django.db import models

# Create your models here.

import time
import datetime
from urllib.parse import urlencode
import logging
import sys
from django.utils.timezone import utc
import email


from feeds.models import Source, Post, Enclosure
from django.contrib.auth.models import User


            

# A user subscription
class Subscription(models.Model):

    key            = models.CharField(unique=True,max_length=64)
    source         = models.ForeignKey(Source, on_delete=models.CASCADE) 
    last_sent      = models.IntegerField(default=1)
    last_sent_date = models.DateTimeField()
    frequency      = models.IntegerField(default=5) # in days.  A little faster than a week so most podcasts catch up
    name           = models.CharField(max_length=255)
    complete       = models.BooleanField(default=False)
    created        = models.DateTimeField(auto_now_add=True,null=True)
    last_accessed  = models.DateTimeField(auto_now_add=True,null=True)
    
    def __str__(self):
        return "'%s' on id %s" % (self.name,self.key)
    
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
        ordering = ["-id"]
    
                
        
        
class SubscriptionPost(models.Model):
    post         = models.ForeignKey(Post, on_delete=models.CASCADE)
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE)
    created      = models.DateTimeField(auto_now_add=True)

        

    
class AccessLog(models.Model):
    subscription = models.ForeignKey(Subscription,blank=True,null=True, on_delete=models.CASCADE)
    raw_id       = models.CharField(max_length=128)
    access_time  = models.DateTimeField(auto_now_add=True)
    ip_address   = models.CharField(max_length=16)
    user_agent   = models.CharField(max_length=512)
    return_code  = models.IntegerField()
    
    def __str__(self):
    
        if self.subscription:
            return "%d @ %s - %s from %s -- %s" % (self.return_code, self.access_time,self.subscription.name,self.ip_address,self.user_agent)
        else:
            return "%d @ %s from %s -- %s" % (self.return_code, self.access_time,self.ip_address,self.user_agent)
            
    class Meta:
        ordering = ["-id"]
