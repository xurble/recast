from django.urls import path, include
from django.conf.urls import url

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

from rc.views import *

urlpatterns = [
    # Examples:
    # url(r'^$', 'feedthing.views.home', name='home'),
    # url(r'^feedthing/', include('feedthing.foo.urls')),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    path('admin/', admin.site.urls),


    url(r'^$', index),
    url(r'^refresh/$', reader),
    url(r'^help/$', help),

    url(r'^feed/(?P<key>.*)/edit/$', editfeed), # legacy
    url(r'^feed/edit/(?P<key>.*)/$', editfeed, name='editfeed'),
    url(r'^feed/(?P<key>.*)/$', feed, name='feed'),

    url(r'^source/(?P<sid>.*)/revive/$', revivesource),
    url(r'^source/(?P<sid>.*)/subscribe/$', subscribe, name='subscribe'),
    url(r'^source/(?P<sid>.*)/$', source, name='source'),

    


    url(r'^post/(?P<pid>.*)/$', post_redirect),
    url(r'^enclosure/(?P<eid>.*)/$', enclosure_redirect),


    url(r'^addfeed/$', addfeed),
    

    url(r'^feedgarden/$', feedgarden),

    

    url('^robots.txt$', robots),
    url('^favicon.ico$', favicon),

    
]

