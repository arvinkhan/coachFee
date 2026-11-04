from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.core.paginator import Paginator

from reminders.models import MessageLog, Reminder
from reminders.services import process_daily_reminders


@login_required
def reminder_log(request):
    """Staff view to inspect sent messages and reminder logs."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    logs = MessageLog.objects.select_related('reminder__instalment__student').order_by('-sent_at')

    phone = request.GET.get('phone', '').strip()
    if phone:
        logs = logs.filter(phone__icontains=phone)

    paginator = Paginator(logs, 20)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    return render(request, 'reminders/log.html', {
        'page_obj': page_obj,
        'phone': phone,
    })


@login_required
def trigger_reminders(request):
    """Manual trigger for daily reminder dispatch."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    if request.method == 'POST':
        stats = process_daily_reminders()
        messages.success(
            request,
            f"Daily reminder check completed: {stats['sent']} sent, "
            f"{stats['skipped_paid']} skipped (already paid), {stats['skipped_duplicate']} skipped (already sent)."
        )

    return redirect('reminders:log')
