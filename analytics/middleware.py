from . import services


class AnalyticsMiddleware:
    """منبع ورود (UTM، Referer، صفحه فرود) را برای بازدیدکننده‌های ناشناس هم ثبت می‌کند."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        services.track_pageview(request, response)
        services.track_action(request, response)
        return response
