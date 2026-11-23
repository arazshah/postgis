"""Request-scoped Live presentation for the existing account workflows."""
from urllib.parse import urlencode, urlsplit

from django.contrib.auth import logout
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache

from accounts import views as accounts

DIRECT_SESSION = 'live_direct_session'
STEPS = {
    'login': accounts.login_start, 'password': accounts.login_password,
    'verify': accounts.verify, 'resend': accounts.resend,
    'signup': accounts.signup_email, 'forgot': accounts.password_forgot,
}


def destination(value):
    if isinstance(value, str) and value.startswith("/live/") and "\\" not in value:
        parsed = urlsplit(value)
        if not parsed.scheme and not parsed.netloc and value.startswith('/live/') and not value.startswith('/live/auth/'):
            return value
    return reverse('live:index')


@never_cache
def flow(request, step='login', **kwargs):
    view = {'reset': accounts.password_reset, 'confirm': accounts.email_confirm}.get(step) or STEPS.get(step)
    if view is None:
        from django.http import Http404
        raise Http404
    request.live_auth_flow = step
    if request.user.is_authenticated and (request.user.is_staff or not request.user.is_active):
        logout(request)
    nxt = destination(request.POST.get('next') or request.GET.get('next'))
    # Never forward an arbitrary same-host endpoint through the Live return path.
    request.GET = request.GET.copy()
    request.GET['next'] = nxt
    if request.method == 'POST':
        request.POST = request.POST.copy()
        request.POST['next'] = nxt
    previously_authenticated = request.user.is_authenticated
    response = view(request, **kwargs)
    if request.user.is_authenticated and request.user.is_active and not request.user.is_staff:
        if not previously_authenticated:
            request.session[DIRECT_SESSION] = True
        if response.status_code in (301, 302, 303):
            return redirect(nxt)
    if response.status_code in (301, 302, 303):
        path = urlsplit(response['Location']).path
        routes = {reverse('accounts:login'): 'login', reverse('accounts:login_password'): 'password',
                  reverse('accounts:verify'): 'verify', reverse('accounts:signup_email'): 'signup',
                  reverse('accounts:password_forgot'): 'forgot'}
        response['Location'] = reverse('live:auth', args=[routes.get(path, 'login')]) + '?' + urlencode({'next': nxt})
    return response


def required(request):
    url = reverse('live:auth', args=['login']) + '?' + urlencode({'next': destination(request.get_full_path())})
    if 'application/json' in request.headers.get('Accept', '') or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'error': {'code': 'auth_required', 'message': 'برای ادامه دوباره وارد شوید.'}, 'login_url': url}, status=401)
    return redirect(url)
