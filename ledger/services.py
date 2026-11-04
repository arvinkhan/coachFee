"""
Ledger services — pure financial logic, no Django ORM side effects.
All monetary values in integer paise (₹1 = 100 paise).
"""
from datetime import date


def compute_instalment_status(instalment_amount_paise, allocated_paise, due_date, today=None):
    """Return (status, balance_paise, days_overdue) for an instalment."""
    today = today or date.today()
    balance = instalment_amount_paise - allocated_paise

    if balance <= 0:
        return 'paid', 0, 0
    elif allocated_paise > 0 and due_date < today:
        days_overdue = (today - due_date).days
        return 'partial', balance, days_overdue
    elif allocated_paise > 0:
        return 'partial', balance, 0
    elif due_date < today:
        days_overdue = (today - due_date).days
        return 'overdue', balance, days_overdue
    elif due_date == today:
        return 'due', balance, 0
    else:
        return 'upcoming', balance, 0


def allocate_payment(payment_amount_paise, instalments_with_balances):
    """
    Allocate a payment to the oldest outstanding instalments first.

    Args:
        payment_amount_paise: int, total payment in paise
        instalments_with_balances: list of (instalment_id, balance_paise)
            sorted by due_date ASC (oldest first)

    Returns:
        list of (instalment_id, amount_to_allocate_paise)
        remaining_paise: int, leftover after all instalments filled
    """
    allocations = []
    remaining = payment_amount_paise

    for inst_id, balance in instalments_with_balances:
        if remaining <= 0:
            break
        if balance <= 0:
            continue
        alloc = min(remaining, balance)
        allocations.append((inst_id, alloc))
        remaining -= alloc

    return allocations, remaining


def compute_student_ledger(instalments_data, payments_data, discounts_paise):
    """
    Compute full student ledger.

    Args:
        instalments_data: list of dicts with keys: id, sequence, amount, due_date, allocated
        payments_data: list of dicts with keys: id, amount, mode, received_at, gateway_ref, allocations
        discounts_paise: total discount in paise

    Returns dict with:
        total_fee, total_paid, total_balance, total_discount,
        instalments (enriched with status), payments
    """
    total_fee = sum(i['amount'] for i in instalments_data)
    total_paid = sum(p['amount'] for p in payments_data)
    total_discount = discounts_paise
    total_balance = total_fee - total_paid - total_discount
    if total_balance < 0:
        total_balance = 0

    enriched_instalments = []
    for inst in instalments_data:
        status, balance, days_overdue = compute_instalment_status(
            inst['amount'], inst['allocated'], inst['due_date']
        )
        enriched_instalments.append({
            **inst,
            'status': status,
            'balance': balance,
            'days_overdue': days_overdue,
            'paid': inst['allocated'],
            'amount_display': inst['amount'] / 100,
            'balance_display': balance / 100,
            'paid_display': inst['allocated'] / 100,
        })

    return {
        'total_fee': total_fee,
        'total_paid': total_paid,
        'total_balance': total_balance,
        'total_discount': total_discount,
        'total_fee_display': total_fee / 100,
        'total_paid_display': total_paid / 100,
        'total_balance_display': total_balance / 100,
        'total_discount_display': total_discount / 100,
        'instalments': enriched_instalments,
        'payments': payments_data,
    }


def compute_ageing_buckets(overdue_instalments, today=None):
    """
    Compute ageing buckets from overdue instalments.

    Args:
        overdue_instalments: list of (due_date, balance_paise)

    Returns dict: bucket_0_30, bucket_31_60, bucket_over_60 (all paise)
    """
    today = today or date.today()
    buckets = {'bucket_0_30': 0, 'bucket_31_60': 0, 'bucket_over_60': 0}

    for due_date, balance in overdue_instalments:
        days = (today - due_date).days
        if days <= 0:
            continue
        elif days <= 30:
            buckets['bucket_0_30'] += balance
        elif days <= 60:
            buckets['bucket_31_60'] += balance
        else:
            buckets['bucket_over_60'] += balance

    return buckets


def generate_receipt_number(payment_id):
    """Generate receipt number: RCP-YYYYMMDD-NNNNN."""
    from datetime import datetime
    now = datetime.now()
    return f"RCP-{now.strftime('%Y%m%d')}-{payment_id:05d}"


def compute_gst_breakdown(amount_paise, gst_rate_percent):
    """
    Compute GST breakdown from inclusive amount.

    Returns (base_paise, gst_paise, total_paise).
    """
    # amount is inclusive of GST
    base = int(amount_paise * 100 / (100 + gst_rate_percent))
    gst = amount_paise - base
    return base, gst, amount_paise
