from django.shortcuts import render, redirect
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.models import User
from django.contrib import messages
from django.views.decorators.http import require_http_methods
from accounts.models import Guardian, StudentProfile
from accounts.services import request_parent_otp, verify_parent_otp
from ledger.models import Student


def login_landing(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        elif hasattr(request.user, 'student_profile'):
            return redirect('ledger:student_portal')
        return redirect('ledger:dashboard')
    return render(request, 'accounts/login.html')


def parent_login(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        elif hasattr(request.user, 'student_profile'):
            return redirect('ledger:student_portal')
        return redirect('ledger:dashboard')

    step = 'request'
    email = ''
    demo_otp = None
    error = None

    if request.method == 'POST':
        action = request.POST.get('action')
        email = (request.POST.get('email') or request.POST.get('phone') or '').strip().lower()

        if action == 'request_otp':
            success, msg, code = request_parent_otp(email)
            if success:
                step = 'verify'
                demo_otp = code
            else:
                error = msg
        elif action == 'verify_otp':
            otp = request.POST.get('otp', '').strip()
            success, msg, user = verify_parent_otp(email, otp)
            if success and user:
                login(request, user)
                return redirect('ledger:parent_dashboard')
            else:
                step = 'verify'
                error = msg

    return render(request, 'accounts/parent_login.html', {
        'step': step,
        'email': email,
        'demo_otp': demo_otp,
        'error': error,
    })


def student_login(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'student_profile'):
            return redirect('ledger:student_portal')
        elif hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        return redirect('ledger:dashboard')

    error = None
    student_id = ''
    if request.method == 'POST':
        student_id = request.POST.get('student_id', '').strip().upper()
        password = request.POST.get('password', '').strip()

        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            error = f"No student found with ID '{student_id}'. Please check your ID card."
        else:
            profile = StudentProfile.objects.filter(student=student).first()
            if not profile:
                # Ensure a linked auth User exists for this student
                username = f"stu_{student_id.lower().replace('-', '_')}"
                user = User.objects.filter(username=username).first()
                if not user:
                    user = User.objects.create_user(username=username, password='student123')
                profile = StudentProfile.objects.create(user=user, student=student)

            user = authenticate(request, username=profile.user.username, password=password)
            if user is not None:
                login(request, user)
                return redirect('ledger:student_portal')
            else:
                error = "Incorrect password. (Default demo password: student123)"

    return render(request, 'accounts/student_login.html', {
        'error': error,
        'student_id': student_id
    })


def staff_login(request):
    if request.user.is_authenticated:
        if hasattr(request.user, 'staff_profile') or request.user.is_staff:
            return redirect('ledger:dashboard')
        elif hasattr(request.user, 'student_profile'):
            return redirect('ledger:student_portal')
        return redirect('ledger:parent_dashboard')

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
