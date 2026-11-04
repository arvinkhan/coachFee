import json
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponseBadRequest, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum

from ledger.models import Instalment, PaymentAllocation, Student
from payments.models import PaymentLink, UnmatchedPayment
from payments.services import get_or_create_payment_link, simulate_payment, process_webhook


def pay_instalment(request, instalment_id):
    """
    Parent payment landing page for a specific instalment.
    Presents outstanding amount, student details, and payment options.
    """
    instalment = get_object_or_404(Instalment.objects.select_related('student__guardian', 'student__batch'), id=instalment_id)
    student = instalment.student

    # Check permission if user is logged in as parent
    if request.user.is_authenticated and hasattr(request.user, 'guardian_profile'):
        if student.guardian != request.user.guardian_profile:
            return HttpResponseForbidden("Not authorized to pay for another student.")

    alloc_sum = PaymentAllocation.objects.filter(instalment=instalment).aggregate(t=Sum('amount'))['t'] or 0
    balance_paise = instalment.amount - alloc_sum

    if balance_paise <= 0:
        messages.info(request, "This instalment is already fully paid.")
        if request.user.is_authenticated and hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        return redirect('ledger:student_detail', student_id=student.student_id)

    payment_link = get_or_create_payment_link(instalment)

    return render(request, 'payments/pay.html', {
        'instalment': instalment,
        'student': student,
        'balance': balance_paise / 100,
        'payment_link': payment_link,
    })


def process_payment_simulation(request, token):
    """
    Simulates gateway transaction submission (mock gateway).
    Supports simulating success or deliberate failure.
    """
    simulate_fail = request.GET.get('fail') == '1'

    ref, sig, amount, can_proceed = simulate_payment(token, success=not simulate_fail)
    if not can_proceed and not simulate_fail:
        messages.error(request, "Payment link is invalid or already paid.")
        return redirect('ledger:home')

    if simulate_fail:
        messages.error(request, "Gateway simulation: Payment was declined or cancelled by user.")
        link = get_object_or_404(PaymentLink, token=token)
        return redirect('payments:pay', instalment_id=link.instalment.id)

    # Trigger webhook with HMAC signature
    actor = request.user if request.user.is_authenticated else None
    success, msg, payment = process_webhook(
        gateway_ref=ref,
        amount_paise=amount,
        signature=sig,
        payment_link_token=token,
        actor=actor
    )

    if success and payment:
        return redirect('payments:success', payment_id=payment.id)
    else:
        messages.error(request, f"Payment processing error: {msg}")
        return redirect('ledger:home')


@csrf_exempt
def webhook_endpoint(request):
    """
    Standard HTTP webhook endpoint for payment gateways.
    Validates HMAC signature and guarantees idempotency.
    """
    if request.method != 'POST':
        return HttpResponseBadRequest("POST required")

    try:
        data = json.loads(request.body.decode('utf-8'))
        gateway_ref = data.get('gateway_ref')
        amount_paise = int(data.get('amount_paise', 0))
        signature = data.get('signature', '')
        payment_link_token = data.get('payment_link_token')

        if not all([gateway_ref, amount_paise, signature, payment_link_token]):
            return JsonResponse({'error': 'Missing required fields'}, status=400)

        success, msg, payment = process_webhook(
            gateway_ref=gateway_ref,
            amount_paise=amount_paise,
            signature=signature,
            payment_link_token=payment_link_token,
        )

        return JsonResponse({
            'success': success,
            'message': msg,
            'payment_id': payment.id if payment else None
        }, status=200 if success else 400)

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


def payment_success(request, payment_id):
    """Displays payment confirmation and generated GST receipt."""
    from ledger.models import Payment
    payment = get_object_or_404(Payment.objects.select_related('student', 'receipt'), id=payment_id)
    receipt = getattr(payment, 'receipt', None)

    return render(request, 'payments/success.html', {
        'payment': payment,
        'student': payment.student,
        'receipt': receipt,
        'amount_display': payment.amount / 100,
        'base_display': (receipt.base_amount / 100) if receipt else 0,
        'gst_display': (receipt.gst_amount / 100) if receipt else 0,
    })


@login_required
def unmatched_queue(request):
    """Staff view of unmatched / unverified payments queue."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    unmatched = UnmatchedPayment.objects.order_by('-received_at')
    return render(request, 'payments/unmatched.html', {
        'unmatched_payments': unmatched,
    })


@login_required
def resolve_unmatched(request, unmatched_id):
    """Staff action to match an unmatched payment to a student ledger."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    unmatched = get_object_or_404(UnmatchedPayment, id=unmatched_id)
    if request.method == 'POST':
        student_id = request.POST.get('student_id', '').strip()
        student = Student.objects.filter(student_id=student_id).first()
        if not student:
            messages.error(request, f"Student {student_id} not found.")
            return redirect('payments:unmatched')

        # Allocate payment to student
        from ledger.models import Payment, PaymentAllocation, Receipt, Instalment
        from ledger.services import allocate_payment, compute_gst_breakdown, generate_receipt_number

        all_inst = Instalment.objects.filter(student=student).order_by('due_date', 'sequence')
        inst_balances = []
        for inst in all_inst:
            alloc_sum = PaymentAllocation.objects.filter(instalment=inst).aggregate(t=Sum('amount'))['t'] or 0
            b = inst.amount - alloc_sum
            if b > 0:
                inst_balances.append((inst.id, b))

        allocations, remaining = allocate_payment(unmatched.amount, inst_balances)

        payment = Payment.objects.create(
            student=student,
            amount=unmatched.amount,
            mode='bank',
            gateway_ref=unmatched.gateway_ref,
        )

        for inst_id, a_amt in allocations:
            PaymentAllocation.objects.create(
                payment=payment,
                instalment_id=inst_id,
                amount=a_amt
            )

        base, gst, total = compute_gst_breakdown(unmatched.amount, float(student.fee_plan.gst_rate))
        Receipt.objects.create(
            payment=payment,
            receipt_number=generate_receipt_number(payment.id),
            base_amount=base,
            gst_amount=gst,
            total_amount=total,
        )

        unmatched.status = 'matched'
        unmatched.resolved_payment = payment
        unmatched.save(update_fields=['status', 'resolved_payment'])

        messages.success(request, f"Payment of ₹{unmatched.amount / 100:,.0f} matched to {student.name}.")

    return redirect('payments:unmatched')
