from django.conf import settings


class PreviewMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        # One-time configuration and initialization.

    def __call__(self, request):
        # Code to be executed for each request before
        # the view (and later middleware) are called.

        request.vals = {
            "page_url": settings.FEEDS_SERVER + request.META["PATH_INFO"],
            "site_name": "Recast",
            "page_image": settings.FEEDS_SERVER
            + "/static/images/recast-preview-image.png",
            "page_title": "The Simple Podcast Catch-Up Service",
            "page_description": "Recast is a simple service that will replay all the episodes of a podcast from the start.",
        }

        response = self.get_response(request)

        # Code to be executed for each request/response after
        # the view is called.

        return response
