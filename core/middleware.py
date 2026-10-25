from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

PUBLIC_PREFIXES = ("/login/", "/static/", "/admin/login/", "/healthz/")


class LoginRequiredMiddleware:
    """Every page is for the Eatalley team only, so require a login everywhere."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.path.startswith(PUBLIC_PREFIXES) and not request.user.is_authenticated:
            return redirect(f"{reverse(settings.LOGIN_URL)}?next={request.get_full_path()}")
        return self.get_response(request)
