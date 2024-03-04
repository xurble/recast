
from django.urls import path
from rc.views import (
    index,
    reader,
    help,
    editfeed,
    feed,
    revivesource,
    testsource,
    subscribe,
    source,
    post_redirect,
    enclosure_redirect,
    addfeed,
    feedgarden,
    robots,
    favicon
)
# Uncomment the next two lines to enable the admin:
from django.contrib import admin
admin.autodiscover()


urlpatterns = [
    # Examples:
    # url(r'^$', 'feedthing.views.home', name='home'),
    # url(r'^feedthing/', include('feedthing.foo.urls')),

    # Uncomment the admin/doc line below to enable admin documentation:
    # url(r'^admin/doc/', include('django.contrib.admindocs.urls')),

    # Uncomment the next line to enable the admin:
    path('admin/', admin.site.urls),


    path(r'', index),
    path(r'refresh/', reader),
    path(r'help/', help),

    path('feed/(<str:key>)/edit/', editfeed),  # legacy
    path('feed/edit/<str:key>/', editfeed, name='editfeed'),
    path('feed/<str:key>/', feed, name='feed'),

    path('source/<int:sid>/revive/', revivesource),
    path('source/<int:sid>/test/', testsource),
    path('source/<int:sid>/subscribe/', subscribe, name='subscribe'),
    path('source/<int:sid>/', source, name='source'),

    path('post/<int:pid>/', post_redirect),
    path('enclosure/<int:eid>/', enclosure_redirect),


    path('addfeed/', addfeed),


    path('feedgarden/', feedgarden),



    path('robots.txt', robots),
    path('favicon.ico', favicon),


]
