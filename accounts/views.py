from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .forms import RegisterForm


@login_required
def home(request):
    return render(request, 'accounts/home.html')


def register(request):
    if request.user.is_authenticated:
        return redirect('accounts:home')

    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Your AirSpace account has been created.')
        return redirect('accounts:home')

    return render(request, 'accounts/registration/register.html', {'form': form})
