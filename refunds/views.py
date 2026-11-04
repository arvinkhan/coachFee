from datetime import date, datetime
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages

from ledger.models import Student
from refunds.models import RefundRequest
from refunds.services import calculate_refund


@login_required
def calculate_view(request, student_id):
    """
    Pro-rata refund calculator interface.
    Allows calculation and creation of an MoE 2024 compliant refund request.
    """
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    student = get_object_or_404(Student.objects.select_related('batch', 'fee_plan'), student_id=student_id)
    result = None
    leave_date_str = request.POST.get('leave_date') or request.GET.get('leave_date') or date.today().isoformat()

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            leave_date = datetime.strptime(leave_date_str, '%Y-%m-%d').date()
        except ValueError:
            leave_date = date.today()

        result = calculate_refund(student.student_id, leave_date)

        if action == 'submit_request':
            notes = request.POST.get('notes', '')
            req = RefundRequest.objects.create(
                student=student,
                leave_date=leave_date,
                total_paid=result['total_paid_paise'],
                registration_deduction=result['registration_fee_paise'],
                pro_rata_usage=result['pro_rata_usage_paise'],
                refund_amount=result['refund_amount_paise'],
                breakdown=result,
                due_by=datetime.strptime(result['due_by'], '%Y-%m-%d').date(),
                notes=notes,
                status='pending'
            )
            messages.success(request, f"Refund request #{req.id} created for ₹{req.refund_amount / 100:,.0f}. Due by {req.due_by}.")
            return redirect('refunds:list')

    elif request.method == 'GET' and 'leave_date' in request.GET:
        try:
            leave_date = datetime.strptime(leave_date_str, '%Y-%m-%d').date()
            result = calculate_refund(student.student_id, leave_date)
        except Exception:
            pass

    return render(request, 'refunds/calculate.html', {
        'student': student,
        'leave_date': leave_date_str,
        'result': result,
    })


@login_required
def refund_list(request):
    """Staff dashboard for tracking refund requests and 10-day deadlines."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    refunds = RefundRequest.objects.select_related('student__batch__centre').order_by('-created_at')
    today = date.today()

    refunds_enriched = []
    for r in refunds:
        days_left = (r.due_by - today).days
        refunds_enriched.append({
            'request': r,
            'amount_display': r.refund_amount / 100,
            'days_left': days_left,
            'is_overdue': days_left < 0 and r.status == 'pending',
        })

    return render(request, 'refunds/list.html', {
        'refunds': refunds_enriched,
    })


@login_required
def approve_refund(request, request_id):
    """Staff action to approve refund."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    req = get_object_or_404(RefundRequest, id=request_id)
    if request.method == 'POST':
        req.status = 'approved'
        req.processed_by = request.user
        req.save(update_fields=['status', 'processed_by', 'updated_at'])
        messages.success(request, f"Refund request #{req.id} approved.")

    return redirect('refunds:list')


@login_required
def reject_refund(request, request_id):
    """Staff action to reject refund."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    req = get_object_or_404(RefundRequest, id=request_id)
    if request.method == 'POST':
        req.status = 'rejected'
        req.processed_by = request.user
        req.save(update_fields=['status', 'processed_by', 'updated_at'])
        messages.info(request, f"Refund request #{req.id} marked as rejected.")

    return redirect('refunds:list')
