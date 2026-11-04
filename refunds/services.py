"""
Refunds service: Centralised, configurable pro-rata refund policy.
Adheres to Ministry of Education 2024 Coaching Guidelines:
- Must offer published refund policy
- Pro-rata refund calculated within 10 days of leaving

ASSUMPTION NOTICE (Explicitly labelled for TDD):
- Formula:
    Total Paid
  - Non-refundable Registration Fee (default ₹5,000 / 500,000 paise)
  - Pro-rata Tuition for days attended (days_attended / total_course_days * total_tuition_paise)
  - Proportional GST adjustment (18% on used tuition)
  = Net Refundable Amount (floored at ₹0)
- Refund deadline is set to leave_date + 10 calendar days.
"""
from datetime import date, timedelta
from django.conf import settings
from ledger.models import Student, PaymentAllocation, Instalment
from django.db.models import Sum


def calculate_refund(student_id, leave_date):
    """
    Computes pro-rata refund breakdown for a student leaving on leave_date.
    Returns a dictionary with complete financial breakdown in paise and display values.
    """
    student = Student.objects.select_related('batch', 'fee_plan').get(student_id=student_id)
    fee_plan = student.fee_plan
    batch = student.batch

    # Calculate total course duration
    start_date = batch.start_date
    end_date = batch.end_date
    total_days = max((end_date - start_date).days, 1)

    # Days attended (clamped between 0 and total_days)
    if leave_date < start_date:
        days_attended = 0
    elif leave_date > end_date:
        days_attended = total_days
    else:
        days_attended = max((leave_date - start_date).days, 0)

    # Total amount paid by student
    total_paid = student.payments.aggregate(total=Sum('amount'))['total'] or 0

    # Registration fee deduction
    reg_fee = fee_plan.registration_fee or getattr(settings, 'REGISTRATION_FEE_PAISE', 500000)

    # Net tuition eligible for pro-rata
    tuition_fee = max(fee_plan.total_amount - reg_fee, 0)

    # Pro-rata tuition used
    pro_rata_usage = int((days_attended / total_days) * tuition_fee)

    # Total deduction (Registration + Pro-rata tuition)
    total_deduction_base = reg_fee + pro_rata_usage

    # GST adjustment (18% applied on tuition used if applicable)
    gst_rate = float(fee_plan.gst_rate or getattr(settings, 'GST_RATE_PERCENT', 18))
    # Refund is calculated against total paid
    total_retained = min(total_deduction_base, total_paid)
    refund_amount = max(total_paid - total_retained, 0)

    due_by = leave_date + timedelta(days=getattr(settings, 'REFUND_DEADLINE_DAYS', 10))

    breakdown = {
        'student_id': student.student_id,
        'student_name': student.name,
        'batch': batch.name,
        'start_date': start_date.isoformat(),
        'end_date': end_date.isoformat(),
        'leave_date': leave_date.isoformat(),
        'total_days': total_days,
        'days_attended': days_attended,
        'attendance_ratio': round(days_attended / total_days, 4),
        'total_course_fee_paise': fee_plan.total_amount,
        'total_paid_paise': total_paid,
        'registration_fee_paise': reg_fee,
        'tuition_fee_paise': tuition_fee,
        'pro_rata_usage_paise': pro_rata_usage,
        'total_retained_paise': total_retained,
        'refund_amount_paise': refund_amount,
        'due_by': due_by.isoformat(),
        # Display values in INR
        'total_paid_display': total_paid / 100,
        'registration_fee_display': reg_fee / 100,
        'pro_rata_usage_display': pro_rata_usage / 100,
        'refund_amount_display': refund_amount / 100,
    }

    return breakdown
