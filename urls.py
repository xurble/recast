from django.conf.urls.defaults import patterns, include, url

# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()

urlpatterns = patterns('',
    # Examples:
    # url(r'^$', 'feedthing.views.home', name='home'),
    # url(r'^feedthing/', include('feedthing.foo.urls')),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    url(r'^admin/', include(admin.site.urls)),


    (r'^$', 'rc.views.index'),
    (r'^refresh/$', 'rc.views.reader'),
    (r'^help/$', 'rc.views.help'),

    (r'^feed/(?P<key>.*)/edit/$','rc.views.editfeed'),
    
    (r'^feed/(?P<key>.*)/$','rc.views.feed'),


    (r'^post/(?P<pid>.*)/$','rc.views.post_redirect'),
    (r'^enclosure/(?P<eid>.*)/$','rc.views.enclosure_redirect'),


    (r'^addfeed/$', 'rc.views.addfeed'),

    
    
    
)

"""
    (r'^allfeeds/$', 'rc.views.allfeeds'),
    (r'^importopml/$', 'rc.views.importopml'),
    (r'^feedgarden/$', 'rc.views.feedgarden'),
    (r'^accounts/login','rc.views.loginpage'),
    (r'^read/(?P<fid>.*)/(?P<qty>.*)/','rc.views.readfeed'),


    
    (r'^subscription/(?P<sid>.*)/unsubscribe/$','rc.views.unsubscribefeed'),
    (r'^subscription/(?P<sid>.*)/details/$','rc.views.subscriptiondetails'),
    (r'^subscription/(?P<sid>.*)/promote/$','rc.views.promote'),
    (r'^subscription/(?P<sid>.*)/addto/(?P<tid>.*)/$','rc.views.addto'),


    (r'^feed/(?P<fid>.*)/revive/$','rc.views.revivefeed'),
    (r'^feed/(?P<fid>.*)/kill/$','rc.views.killfeed'),
"""