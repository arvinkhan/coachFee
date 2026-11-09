import csv
from datetime import date
from django.shortcuts import render, get_object_or_404, redirect
from django.http import HttpResponse, HttpResponseForbidden
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Q
from django.core.paginator import Paginator

from ledger.models import Student, Centre, Batch, Instalment, Payment, PaymentAllocation, Discount
from ledger.services import compute_student_ledger, compute_ageing_buckets, compute_instalment_status
from payments.services import get_or_create_payment_link


@login_required
def home(request):
    """Route user according to their role."""
    if hasattr(request.user, 'guardian_profile'):
        return redirect('ledger:parent_dashboard')
    elif hasattr(request.user, 'student_profile'):
        return redirect('ledger:student_portal')
    elif hasattr(request.user, 'staff_profile') or request.user.is_staff:
        return redirect('ledger:dashboard')
    return redirect('accounts:login')


@login_required
def student_portal(request):
    """
    Dedicated Student Dashboard:
    - Academic profile: attendance percentage, recent log, and test scores
    - Fee schedule: Total course fee, paid amount, balance, upcoming instalments
    - Direct access to GST receipts & payment links
    """
    if not hasattr(request.user, 'student_profile'):
        if hasattr(request.user, 'guardian_profile'):
            return redirect('ledger:parent_dashboard')
        return redirect('ledger:dashboard')

    student = request.user.student_profile.student
    
    # 1. Academics: Attendance & Test Scores
    from risk.models import Attendance, TestScore
    attendance_records = Attendance.objects.filter(student=student).order_by('-date')
    total_days = attendance_records.count()
    present_days = attendance_records.filter(present=True).count()
    attendance_pct = round((present_days / total_days * 100), 1) if total_days > 0 else 0

    test_scores = TestScore.objects.filter(student=student).order_by('-date')
    enriched_scores = []
    for t in test_scores:
        pct = round((t.score / t.max_score * 100), 1) if t.max_score > 0 else 0
        enriched_scores.append({
            'test_name': t.test_name,
            'date': t.date,
            'score': t.score,
            'max_score': t.max_score,
            'percentage': pct,
        })

    # 2. Fee Schedule
    instalments = list(student.instalments.all().order_by('due_date', 'sequence'))
    inst_data = []
    for inst in instalments:
        alloc_sum = PaymentAllocation.objects.filter(instalment=inst).aggregate(t=Sum('amount'))['t'] or 0
        status, balance, days_overdue = compute_instalment_status(inst.amount, alloc_sum, inst.due_date)
        inst_data.append({
            'id': inst.id,
            'sequence': inst.sequence,
            'due_date': inst.due_date,
            'amount': inst.amount / 100,
            'paid': alloc_sum / 100,
            'balance': balance / 100,
            'status': status,
            'days_overdue': days_overdue,
        })

    total_fee = student.fee_plan.total_amount
    total_paid = student.payments.aggregate(t=Sum('amount'))['t'] or 0
    total_disc = student.discounts.aggregate(t=Sum('amount'))['t'] or 0
    total_balance = max(total_fee - total_paid - total_disc, 0)

    # 3. Receipts
    payments = student.payments.select_related('receipt').prefetch_related('allocations__instalment').order_by('-received_at')

    return render(request, 'student/dashboard.html', {
        'student': student,
        'attendance_records': attendance_records[:15],
        'total_days': total_days,
        'present_days': present_days,
        'attendance_pct': attendance_pct,
        'test_scores': enriched_scores,
        'instalments': inst_data,
        'total_fee': total_fee / 100,
        'total_paid': total_paid / 100,
        'total_discount': total_disc / 100,
        'total_balance': total_balance / 100,
        'payments': payments,
    })


@login_required
def parent_dashboard(request):
    """
    Main Parent Screen: 5-Second Comprehension.
    Displays outstanding amount, next due date, and payment button prominently.
    Parents can ONLY access their own children.
    """
    if not hasattr(request.user, 'guardian_profile'):
        return redirect('ledger:dashboard')

    guardian = request.user.guardian_profile
    students = Student.objects.filter(guardian=guardian).select_related('batch', 'fee_plan')

    children_data = []
    for student in students:
        # Load instalments
        instalments = list(student.instalments.all().order_by('due_date', 'sequence'))
        inst_list = []
        for inst in instalments:
            alloc_sum = PaymentAllocation.objects.filter(instalment=inst).aggregate(
                total=Sum('amount')
            )['total'] or 0
            status, balance, days_overdue = compute_instalment_status(
                inst.amount, alloc_sum, inst.due_date
            )
            inst_list.append({
                'id': inst.id,
                'sequence': inst.sequence,
                'amount': inst.amount / 100,
                'amount_paise': inst.amount,
                'due_date': inst.due_date,
                'paid': alloc_sum / 100,
                'balance': balance / 100,
                'balance_paise': balance,
                'status': status,
                'days_overdue': days_overdue,
            })

        total_fee = student.fee_plan.total_amount
        total_paid = student.payments.aggregate(total=Sum('amount'))['total'] or 0
        total_disc = student.discounts.aggregate(total=Sum('amount'))['total'] or 0
        total_balance = max(total_fee - total_paid - total_disc, 0)

        children_data.append({
            'student': student,
            'instalments': inst_list,
            'total_fee': total_fee / 100,
            'total_paid': total_paid / 100,
            'total_balance': total_balance / 100,
            'total_balance_paise': total_balance,
            'total_discount': total_disc / 100,
        })

    return render(request, 'parent/dashboard.html', {
        'guardian': guardian,
        'children': children_data,
    })


@login_required
def parent_receipts(request, student_id=None):
    """Parent view: GST payment receipts and history."""
    if not hasattr(request.user, 'guardian_profile'):
        return redirect('ledger:dashboard')

    guardian = request.user.guardian_profile
    students = Student.objects.filter(guardian=guardian)
    if not students.exists():
        return render(request, 'parent/receipts.html', {'payments': [], 'student': None})

    if student_id:
        student = get_object_or_404(students, student_id=student_id)
    else:
        student = students.first()

    payments = Payment.objects.filter(student=student).select_related('receipt').prefetch_related('allocations__instalment')

    payment_list = []
    for p in payments:
        receipt = getattr(p, 'receipt', None)
        allocations_desc = [f"Inst #{a.instalment.sequence} (₹{a.amount / 100:,.0f})" for a in p.allocations.all()]
        payment_list.append({
            'id': p.id,
            'amount': p.amount / 100,
            'mode': p.get_mode_display(),
            'received_at': p.received_at,
            'gateway_ref': p.gateway_ref or 'Direct/Cash',
            'receipt_number': receipt.receipt_number if receipt else 'Pending',
            'receipt_base': (receipt.base_amount / 100) if receipt else 0,
            'receipt_gst': (receipt.gst_amount / 100) if receipt else 0,
            'receipt_total': (receipt.total_amount / 100) if receipt else (p.amount / 100),
            'allocations': allocations_desc,
        })

    return render(request, 'parent/receipts.html', {
        'guardian': guardian,
        'students': students,
        'student': student,
        'payments': payment_list,
    })


@login_required
def staff_dashboard(request):
    """
    Accounts Executive & Admin Dues Dashboard.
    Shows total billed, collected, outstanding, centre-wise breakdown,
    batch-wise dues, and ageing buckets (0-30, 31-60, 60+).
    Scoped to assigned centre if accounts executive.
    """
    user = request.user
    staff_profile = getattr(user, 'staff_profile', None)

    # Scoping
    assigned_centre = None
    if staff_profile and not staff_profile.is_admin and staff_profile.centre:
        assigned_centre = staff_profile.centre

    # Filter query
    centre_id = request.GET.get('centre')
    if centre_id:
        selected_centre = Centre.objects.filter(id=centre_id).first()
    elif staff_profile and not staff_profile.is_admin and staff_profile.centre:
        selected_centre = staff_profile.centre
    else:
        selected_centre = None

    student_qs = Student.objects.filter(is_active=True).select_related('batch__centre', 'fee_plan')
    if selected_centre:
        student_qs = student_qs.filter(batch__centre=selected_centre)

    # Aggregations across active students
    total_billed = 0
    total_collected = 0
    total_discounts = 0
    overdue_instalments = []
    today = date.today()

    for s in student_qs:
        total_billed += s.fee_plan.total_amount
        p_sum = s.payments.aggregate(t=Sum('amount'))['t'] or 0
        total_collected += p_sum
        d_sum = s.discounts.aggregate(t=Sum('amount'))['t'] or 0
        total_discounts += d_sum

    total_outstanding = max(total_billed - total_collected - total_discounts, 0)

    # Ageing calculations
    instalment_qs = Instalment.objects.filter(student__in=student_qs, due_date__lt=today)
    for inst in instalment_qs:
        alloc = PaymentAllocation.objects.filter(instalment=inst).aggregate(t=Sum('amount'))['t'] or 0
        bal = inst.amount - alloc
        if bal > 0:
            overdue_instalments.append((inst.due_date, bal))

    ageing_paise = compute_ageing_buckets(overdue_instalments, today)
    ageing = {
        'bucket_0_30': ageing_paise['bucket_0_30'] / 100,
        'bucket_31_60': ageing_paise['bucket_31_60'] / 100,
        'bucket_over_60': ageing_paise['bucket_over_60'] / 100,
    }

    # Centre breakdown
    all_centres = Centre.objects.all()
    centre_breakdown = []
    for c in all_centres:
        c_students = Student.objects.filter(batch__centre=c, is_active=True)
        c_billed = sum(st.fee_plan.total_amount for st in c_students)
        c_paid = Payment.objects.filter(student__in=c_students).aggregate(t=Sum('amount'))['t'] or 0
        c_disc = Discount.objects.filter(student__in=c_students).aggregate(t=Sum('amount'))['t'] or 0
        c_out = max(c_billed - c_paid - c_disc, 0)
        centre_breakdown.append({
            'centre_id': c.id,
            'centre_name': c.name,
            'billed': c_billed / 100,
            'collected': c_paid / 100,
            'outstanding': c_out / 100,
            'student_count': c_students.count(),
        })

    recent_payments = Payment.objects.filter(student__in=student_qs).select_related('student', 'receipt').order_by('-received_at')[:8]

    summary = {
        'total_billed': total_billed / 100,
        'total_collected': total_collected / 100,
        'total_outstanding': total_outstanding / 100,
        'total_students': student_qs.count(),
    }

    return render(request, 'dashboard/home.html', {
        'summary': summary,
        'centre_breakdown': centre_breakdown,
        'ageing': ageing,
        'recent_payments': recent_payments,
        'centres': all_centres,
        'selected_centre': selected_centre,
        'staff_profile': staff_profile,
    })


@login_required
def student_list(request):
    """Searchable, filterable student list for staff."""
    if hasattr(request.user, 'guardian_profile'):
        return redirect('ledger:parent_dashboard')

    staff_profile = getattr(request.user, 'staff_profile', None)
    qs = Student.objects.select_related('batch__centre', 'fee_plan', 'guardian').all()

    # Centre filter
    centre_filter = request.GET.get('centre', '')
    if centre_filter:
        if centre_filter != 'all':
            qs = qs.filter(batch__centre_id=centre_filter)
    elif staff_profile and not staff_profile.is_admin and staff_profile.centre:
        qs = qs.filter(batch__centre=staff_profile.centre)
        centre_filter = str(staff_profile.centre.id)

    # Search
    search = request.GET.get('search', '').strip()
    if search:
        qs = qs.filter(Q(name__icontains=search) | Q(student_id__icontains=search) | Q(guardian__phone__icontains=search))

    # Batch filter
    batch_filter = request.GET.get('batch', '')
    if batch_filter:
        qs = qs.filter(batch_id=batch_filter)

    paginator = Paginator(qs, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    # Enrich students with current balance & status
    today = date.today()
    students_enriched = []
    for s in page_obj:
        fee = s.fee_plan.total_amount
        paid = s.payments.aggregate(t=Sum('amount'))['t'] or 0
        disc = s.discounts.aggregate(t=Sum('amount'))['t'] or 0
        bal = max(fee - paid - disc, 0)

        # Overdue check
        has_overdue = s.instalments.filter(due_date__lt=today).exists()
        if bal == 0:
            status = 'paid'
        elif has_overdue:
            status = 'overdue'
        elif paid > 0:
            status = 'partial'
        else:
            status = 'due'

        students_enriched.append({
            'student': s,
            'total_fee': fee / 100,
            'paid': paid / 100,
            'balance': bal / 100,
            'status': status,
        })

    centres = Centre.objects.all()
    batches = Batch.objects.all()

    return render(request, 'ledger/student_list.html', {
        'students': students_enriched,
        'page_obj': page_obj,
        'centres': centres,
        'batches': batches,
        'search': search,
        'centre_filter': centre_filter,
        'batch_filter': batch_filter,
    })


@login_required
def student_detail(request, student_id):
    """Full fee ledger for a specific student."""
    # Parent restriction check
    if hasattr(request.user, 'guardian_profile'):
        guardian = request.user.guardian_profile
        student = get_object_or_404(Student, student_id=student_id, guardian=guardian)
    else:
        student = get_object_or_404(Student, student_id=student_id)
        # Check staff centre scope
        staff_profile = getattr(request.user, 'staff_profile', None)
        if staff_profile and not staff_profile.is_admin and staff_profile.centre:
            if student.batch.centre != staff_profile.centre:
                return HttpResponseForbidden("Not authorised to view students of other centres.")

    instalments = list(student.instalments.all().order_by('due_date', 'sequence'))
    inst_data = []
    for inst in instalments:
        alloc_sum = PaymentAllocation.objects.filter(instalment=inst).aggregate(t=Sum('amount'))['t'] or 0
        status, balance, days_overdue = compute_instalment_status(inst.amount, alloc_sum, inst.due_date)
        inst_data.append({
            'id': inst.id,
            'sequence': inst.sequence,
            'due_date': inst.due_date,
            'amount': inst.amount / 100,
            'paid': alloc_sum / 100,
            'balance': balance / 100,
            'status': status,
            'days_overdue': days_overdue,
        })

    payments = student.payments.select_related('receipt').prefetch_related('allocations__instalment').order_by('-received_at')
    discounts = student.discounts.all()

    total_fee = student.fee_plan.total_amount
    total_paid = student.payments.aggregate(t=Sum('amount'))['t'] or 0
    total_disc = student.discounts.aggregate(t=Sum('amount'))['t'] or 0
    total_balance = max(total_fee - total_paid - total_disc, 0)

    return render(request, 'ledger/student_detail.html', {
        'student': student,
        'instalments': inst_data,
        'payments': payments,
        'discounts': discounts,
        'total_fee': total_fee / 100,
        'total_paid': total_paid / 100,
        'total_discount': total_disc / 100,
        'total_balance': total_balance / 100,
    })


@login_required
def export_csv(request):
    """Tally-compatible CSV export of student fee ledgers."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="coachfee_tally_export.csv"'

    writer = csv.writer(response)
    writer.writerow([
        'Student ID', 'Student Name', 'Centre', 'Batch', 'Total Billed (INR)',
        'Total Paid (INR)', 'Discounts (INR)', 'Balance (INR)', 'Status'
    ])

    students = Student.objects.select_related('batch__centre', 'fee_plan').all()
    today = date.today()

    for s in students:
        fee = s.fee_plan.total_amount
        paid = s.payments.aggregate(t=Sum('amount'))['t'] or 0
        disc = s.discounts.aggregate(t=Sum('amount'))['t'] or 0
        bal = max(fee - paid - disc, 0)
        status = 'Paid' if bal == 0 else ('Overdue' if s.instalments.filter(due_date__lt=today).exists() else 'Pending')

        writer.writerow([
            s.student_id,
            s.name,
            s.batch.centre.name,
            s.batch.name,
            f"{fee / 100:.2f}",
            f"{paid / 100:.2f}",
            f"{disc / 100:.2f}",
            f"{bal / 100:.2f}",
            status,
        ])

    return response
