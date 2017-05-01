from django.conf.urls import include, url

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
    url(r'^admin/', include(admin.site.urls)),


    url(r'^$', index),
    url(r'^refresh/$', reader),
    url(r'^help/$', help),

    url(r'^feed/(?P<key>.*)/edit/$',editfeed),


    url(r'^source/(?P<sid>.*)/revive/$',revivesource),
    url(r'^source/(?P<sid>.*)/$',source),
    
    url(r'^feed/(?P<key>.*)/$',feed),


    url(r'^post/(?P<pid>.*)/$',post_redirect),
    url(r'^enclosure/(?P<eid>.*)/$',enclosure_redirect),


    url(r'^addfeed/$', addfeed),

    url(r'^feedgarden/$', feedgarden),

    

    url('^robots.txt$', robots),

    
]

"""
    (r'^allfeeds/$', allfeeds'),
    (r'^importopml/$', importopml'),
    (r'^accounts/login',loginpage'),
    (r'^read/(?P<fid>.*)/(?P<qty>.*)/',readfeed'),


    
    (r'^subscription/(?P<sid>.*)/unsubscribe/$',unsubscribefeed'),
    (r'^subscription/(?P<sid>.*)/details/$',subscriptiondetails'),
    (r'^subscription/(?P<sid>.*)/promote/$',promote'),
    (r'^subscription/(?P<sid>.*)/addto/(?P<tid>.*)/$',addto'),


    (r'^feed/(?P<fid>.*)/kill/$',killfeed'),
"""