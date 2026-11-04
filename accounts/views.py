from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from accounts.models import Guardian
from accounts.services import request_parent_otp, verify_parent_otp


def login_landing(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        return redirect('ledger:dashboard')
    return render(request, 'accounts/login.html')


def parent_login(request):
    if request.user.is_authenticated and hasattr(request.user, 'guardian_profile'):
        return redirect('ledger:parent_dashboard')

    step = 'request'
    phone = ''
    demo_otp = None
    error = None

    if request.method == 'POST':
        action = request.POST.get('action')
        phone = request.POST.get('phone', '').strip()

        if action == 'request_otp':
            success, msg, code = request_parent_otp(phone)
            if success:
                step = 'verify'
                demo_otp = code
                messages.info(request, f"Demo OTP: {code}")
            else:
                error = msg
        elif action == 'verify_otp':
            otp = request.POST.get('otp', '').strip()
            success, msg, user = verify_parent_otp(phone, otp)
            if success and user:
                login(request, user)
                return redirect('ledger:parent_dashboard')
            else:
                step = 'verify'
                error = msg

    return render(request, 'accounts/parent_login.html', {
        'step': step,
        'phone': phone,
        'demo_otp': demo_otp,
        'error': error,
    })


def staff_login(request):
    if request.user.is_authenticated and hasattr(request.user, 'staff_profile'):
        return redirect('ledger:dashboard')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '').strip()
        user = authenticate(request, username=username, password=password)
        if user is not None:
            if hasattr(user, 'staff_profile') or user.is_staff:
                login(request, user)
                return redirect('ledger:dashboard')
            else:
                error = "Account is not authorised as staff."
        else:
            error = "Invalid username or password."

    return render(request, 'accounts/staff_login.html', {'error': error})


def user_logout(request):
    logout(request)
    return redirect('accounts:login')


def toggle_language(request):
    if request.user.is_authenticated and hasattr(request.user, 'guardian_profile'):
        guardian = request.user.guardian_profile
        guardian.language = 'hi' if guardian.language == 'en' else 'en'
        guardian.save(update_fields=['language'])
    return redirect(request.META.get('HTTP_REFERER', 'ledger:parent_dashboard'))
