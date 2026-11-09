"""
Payment services — gateway simulation, webhook processing, allocation.
"""
import hashlib
import hmac
import uuid
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.models import AuditLog
from ledger.models import Payment, PaymentAllocation, Receipt, Instalment
from ledger.services import allocate_payment, compute_gst_breakdown, generate_receipt_number
from payments.models import PaymentLink, GatewayEvent, UnmatchedPayment


def get_or_create_payment_link(instalment):
    """Get an active payment link or create a new one."""
    link = PaymentLink.objects.filter(
        instalment=instalment,
        status='pending',
    ).first()

    if link and link.expires_at and link.expires_at < timezone.now():
        link.status = 'expired'
        link.save(update_fields=['status'])
        link = None

    if not link:
        link = PaymentLink.objects.create(
            instalment=instalment,
            expires_at=timezone.now() + timedelta(hours=24),
        )

    return link


def generate_hmac_signature(data_string, secret=None):
    """Generate HMAC-SHA256 signature for webhook verification."""
    secret = secret or getattr(settings, 'GATEWAY_HMAC_SECRET', 'mock-secret')
    return hmac.new(
        secret.encode('utf-8'),
        data_string.encode('utf-8'),
        hashlib.sha256,
    ).hexdigest()


def verify_hmac_signature(data_string, signature, secret=None):
    """Verify HMAC signature."""
    expected = generate_hmac_signature(data_string, secret)
    return hmac.compare_digest(expected, signature)


def simulate_payment(payment_link_token, success=True):
    """
    Simulate a payment gateway transaction.

    Returns (gateway_ref, signature, amount_paise, success).
    """
    try:
        link = PaymentLink.objects.select_related('instalment__student').get(
            token=payment_link_token, status='pending'
        )
    except PaymentLink.DoesNotExist:
        return None, None, None, False

    # Compute balance for this instalment
    allocated = PaymentAllocation.objects.filter(
        instalment=link.instalment
    ).aggregate(total=Sum('amount'))['total'] or 0
    balance = link.instalment.amount - allocated

    if balance <= 0:
        link.status = 'paid'
        link.save(update_fields=['status'])
        return None, None, 0, False

    gateway_ref = f"GW-{uuid.uuid4().hex[:12].upper()}"
    data_string = f"{gateway_ref}|{balance}|{link.token}"
    signature = generate_hmac_signature(data_string)

    if not success:
        return gateway_ref, signature, balance, False

    return gateway_ref, signature, balance, True


def process_webhook(gateway_ref, amount_paise, signature, payment_link_token, actor=None):
    """
    Process a payment webhook. Idempotent on gateway_ref.

    Returns (success, message, payment_or_none).
    """
    # Check for duplicate
    if GatewayEvent.objects.filter(gateway_ref=gateway_ref).exists():
        event = GatewayEvent.objects.get(gateway_ref=gateway_ref)
        if event.status == 'processed':
            return True, 'Already processed', None
        return False, 'Duplicate event', None

    # Verify signature
    data_string = f"{gateway_ref}|{amount_paise}|{payment_link_token}"
    sig_valid = verify_hmac_signature(data_string, signature)

    # Find payment link
    try:
        link = PaymentLink.objects.select_related(
            'instalment__student__fee_plan',
            'instalment__student__batch',
        ).get(token=payment_link_token)
    except PaymentLink.DoesNotExist:
        # Unmatched payment
        event = GatewayEvent.objects.create(
            gateway_ref=gateway_ref,
            amount=amount_paise,
            signature_valid=sig_valid,
            status='rejected',
        )
        UnmatchedPayment.objects.create(
            gateway_ref=gateway_ref,
            amount=amount_paise,
        )
        return False, 'Payment link not found — sent to unmatched queue', None

    # Create gateway event
    event = GatewayEvent.objects.create(
        gateway_ref=gateway_ref,
        payment_link=link,
        amount=amount_paise,
        signature_valid=sig_valid,
        status='received',
    )

    if not sig_valid:
        event.status = 'rejected'
        event.save(update_fields=['status'])
        UnmatchedPayment.objects.create(
            gateway_ref=gateway_ref,
            amount=amount_paise,
        )
        return False, 'Invalid signature — sent to unmatched queue', None

    # Validate amount matches instalment balance
    student = link.instalment.student
    allocated = PaymentAllocation.objects.filter(
        instalment=link.instalment
    ).aggregate(total=Sum('amount'))['total'] or 0
    expected_balance = link.instalment.amount - allocated

    if amount_paise > expected_balance and expected_balance > 0:
        # Overpayment — still process but allocate across instalments
        pass
    elif expected_balance <= 0:
        event.status = 'rejected'
        event.save(update_fields=['status'])
        UnmatchedPayment.objects.create(
            gateway_ref=gateway_ref,
            amount=amount_paise,
        )
        return False, 'Instalment already paid — sent to unmatched queue', None

    # Process payment in a transaction
    with transaction.atomic():
        # Create payment
        payment = Payment.objects.create(
            student=student,
            amount=amount_paise,
            mode='gateway',
            gateway_ref=gateway_ref,
        )

        # Allocate to instalments (oldest first)
        all_instalments = Instalment.objects.filter(
            student=student
        ).order_by('due_date', 'sequence')

        inst_balances = []
        for inst in all_instalments:
            alloc_sum = PaymentAllocation.objects.filter(
                instalment=inst
            ).aggregate(total=Sum('amount'))['total'] or 0
            balance = inst.amount - alloc_sum
            if balance > 0:
                inst_balances.append((inst.id, balance))

        allocations, remaining = allocate_payment(amount_paise, inst_balances)

        for inst_id, alloc_amount in allocations:
            PaymentAllocation.objects.create(
                payment=payment,
                instalment_id=inst_id,
                amount=alloc_amount,
            )

        if remaining > 0:
            # Overpayment — record in unmatched
            UnmatchedPayment.objects.create(
                gateway_ref=f"{gateway_ref}-OVER",
                amount=remaining,
                status='pending',
            )

        # Generate receipt
        gst_rate = student.fee_plan.gst_rate
        base, gst, total = compute_gst_breakdown(amount_paise, float(gst_rate))
        receipt = Receipt.objects.create(
            payment=payment,
            receipt_number=generate_receipt_number(payment.id),
            base_amount=base,
            gst_amount=gst,
            total_amount=total,
        )

        # Update payment link status
        link.status = 'paid'
        link.save(update_fields=['status'])

        # Mark event processed
        event.status = 'processed'
        event.save(update_fields=['status'])

        # Audit log
        AuditLog.log(
            actor=actor,
            action='payment_processed',
            target=payment,
            detail={
                'gateway_ref': gateway_ref,
                'amount_paise': amount_paise,
                'allocations': [(i, a) for i, a in allocations],
            },
        )

        return True, 'Payment processed successfully', payment
