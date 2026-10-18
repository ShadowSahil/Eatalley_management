from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.static import serve

User = get_user_model()


def home(request):
    # Daily expenses are what the team opens the site for most.
    return redirect("expenses:entry")


def media(request, path):
    # Uploaded bills and sales files. Served by Django (behind the login
    # middleware) rather than by the web server, so they're never public.
    return serve(request, path, document_root=settings.MEDIA_ROOT)


class TeamMemberForm(forms.Form):
    first_name = forms.CharField(label="Name", max_length=150)
    username = forms.CharField(max_length=150, help_text="Used to log in, e.g. rahul")
    password = forms.CharField(widget=forms.PasswordInput, help_text="At least 8 characters")

    def clean_username(self):
        u = self.cleaned_data["username"].strip().lower()
        if User.objects.filter(username__iexact=u).exists():
            raise forms.ValidationError("That username is taken.")
        return u

    def clean_password(self):
        p = self.cleaned_data["password"]
        validate_password(p)
        return p


class ResetPasswordForm(forms.Form):
    password = forms.CharField(label="New password", widget=forms.PasswordInput)

    def clean_password(self):
        p = self.cleaned_data["password"]
        validate_password(p)
        return p


def team(request):
    form = TeamMemberForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        # Everyone on the team gets the same full access, including /admin.
        User.objects.create_user(
            username=form.cleaned_data["username"],
            password=form.cleaned_data["password"],
            first_name=form.cleaned_data["first_name"],
            is_staff=True,
            is_superuser=True,
        )
        messages.success(request, f"Added {form.cleaned_data['first_name']}. They can log in now.")
        return redirect("team")
    return render(request, "core/team.html", {"form": form, "members": User.objects.order_by("-is_active", "first_name")})


@require_POST
def team_toggle(request, pk):
    member = get_object_or_404(User, pk=pk)
    if member == request.user:
        messages.error(request, "You can't deactivate your own account.")
    else:
        member.is_active = not member.is_active
        member.save(update_fields=["is_active"])
        messages.success(request, f"{member.get_full_name() or member.username} is now {'active' if member.is_active else 'deactivated'}.")
    return redirect("team")


def team_password(request, pk):
    member = get_object_or_404(User, pk=pk)
    form = ResetPasswordForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        member.set_password(form.cleaned_data["password"])
        member.save()
        messages.success(request, f"Password changed for {member.get_full_name() or member.username}.")
        return redirect("team")
    return render(request, "core/form_page.html", {
        "form": form,
        "title": f"Set password for {member.get_full_name() or member.username}",
        "back": "team",
        "submit": "Set password",
    })
