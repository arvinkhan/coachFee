"""
Risk engine: Transparent, rule-based dropout risk scoring.
Scoring model (0 - 100):
1. Missed instalments / overdue balance (0 - 40 pts)
2. Attendance decline (0 - 30 pts)
3. Declining test score trend (0 - 30 pts)

SAFETY CONSTRAINTS:
- A risk flag NEVER automatically triggers fee penalties, changes, or parent notifications.
- It only creates a CounsellorTask for human review.
- Counsellors can mark false positives, which suppresses repeated flagging for 30 days.
"""
from datetime import date, timedelta
from django.conf import settings
from django.utils import timezone
from ledger.models import Student, Instalment, PaymentAllocation
from risk.models import RiskFlag, CounsellorTask, Attendance, TestScore
from django.db.models import Sum, Avg


def evaluate_student_risk(student, as_of_date=None):
    """
    Evaluates dropout risk for a student.
    Returns:
        score: int (0 to 100)
        reasons: dict with detailed breakdown and data status
    """
    as_of_date = as_of_date or date.today()
    reasons = {}
    score = 0

    # 1. Overdue instalments component (Max 40 points)
    overdue_instalments = []
    total_overdue_paise = 0
    instalments = Instalment.objects.filter(student=student, due_date__lt=as_of_date)
    for inst in instalments:
        alloc_sum = PaymentAllocation.objects.filter(instalment=inst).aggregate(total=Sum('amount'))['total'] or 0
        balance = inst.amount - alloc_sum
        if balance > 0:
            days_overdue = (as_of_date - inst.due_date).days
            overdue_instalments.append({
                'sequence': inst.sequence,
                'due_date': inst.due_date.isoformat(),
                'balance_paise': balance,
                'days_overdue': days_overdue
            })
            total_overdue_paise += balance

    if overdue_instalments:
        max_days = max(item['days_overdue'] for item in overdue_instalments)
        if max_days > 45:
            inst_score = 40
        elif max_days > 20:
            inst_score = 30
        elif max_days > 7:
            inst_score = 20
        else:
            inst_score = 10
        score += inst_score
        reasons['instalments'] = {
            'score': inst_score,
            'overdue_count': len(overdue_instalments),
            'max_days_overdue': max_days,
            'total_overdue_display': total_overdue_paise / 100,
            'details': f"{len(overdue_instalments)} instalment(s) overdue, max {max_days} days"
        }
    else:
        reasons['instalments'] = {'score': 0, 'details': 'No overdue instalments'}

    # 2. Attendance decline component (Max 30 points)
    # Compare recent 14 days vs prior 14 days
    cutoff_recent = as_of_date - timedelta(days=14)
    cutoff_prior = as_of_date - timedelta(days=28)

    recent_att = Attendance.objects.filter(student=student, date__gte=cutoff_recent, date__lte=as_of_date)
    prior_att = Attendance.objects.filter(student=student, date__gte=cutoff_prior, date__lt=cutoff_recent)

    recent_total = recent_att.count()
    prior_total = prior_att.count()

    if recent_total >= 3 and prior_total >= 3:
        recent_pct = (recent_att.filter(present=True).count() / recent_total) * 100
        prior_pct = (prior_att.filter(present=True).count() / prior_total) * 100
        drop = prior_pct - recent_pct

        if recent_pct < 50:
            att_score = 30
        elif drop >= 25:
            att_score = 25
        elif drop >= 15:
            att_score = 15
        elif recent_pct < 70:
            att_score = 10
        else:
            att_score = 0
        score += att_score
        reasons['attendance'] = {
            'score': att_score,
            'recent_pct': round(recent_pct, 1),
            'prior_pct': round(prior_pct, 1),
            'drop_pct': round(drop, 1),
            'details': f"Recent attendance {recent_pct:.0f}% vs prior {prior_pct:.0f}%"
        }
    else:
        reasons['attendance'] = {
            'score': 0,
            'insufficient_data': True,
            'details': 'Insufficient attendance records (<3 days in recent/prior period)'
        }

    # 3. Test scores decline component (Max 30 points)
    tests = list(TestScore.objects.filter(student=student, date__lte=as_of_date).order_by('-date')[:4])
    if len(tests) >= 2:
        # tests are newest first: tests[0] is latest, tests[-1] is oldest of the window
        latest_pct = (tests[0].score / tests[0].max_score) * 100
        prev_pct = (tests[1].score / tests[1].max_score) * 100
        score_diff = prev_pct - latest_pct

        if latest_pct < 40 and score_diff > 10:
            test_score = 30
        elif score_diff >= 20:
            test_score = 25
        elif score_diff >= 10:
            test_score = 15
        elif latest_pct < 50:
            test_score = 10
        else:
            test_score = 0
        score += test_score
        reasons['academics'] = {
            'score': test_score,
            'latest_pct': round(latest_pct, 1),
            'prev_pct': round(prev_pct, 1),
            'drop_pct': round(score_diff, 1),
            'details': f"Latest test {latest_pct:.0f}% (prior {prev_pct:.0f}%)"
        }
    else:
        reasons['academics'] = {
            'score': 0,
            'insufficient_data': True,
            'details': 'Insufficient test score history (<2 tests recorded)'
        }

    reasons['total_score'] = score
    return min(score, 100), reasons


def scan_student_and_create_task(student, threshold=None, as_of_date=None):
    """
    Evaluates student risk and, if threshold exceeded and not suppressed, creates a CounsellorTask.
    Returns (created_flag, created_task)
    """
    threshold = threshold or getattr(settings, 'RISK_THRESHOLD', 60)
    suppress_days = getattr(settings, 'RISK_FALSE_FLAG_SUPPRESS_DAYS', 30)

    # Check for active false_flag suppression
    suppress_cutoff = timezone.now() - timedelta(days=suppress_days)
    has_recent_false_flag = RiskFlag.objects.filter(
        student=student,
        status='false_flag',
        updated_at__gte=suppress_cutoff
    ).exists()

    if has_recent_false_flag:
        return None, None

    score, reasons = evaluate_student_risk(student, as_of_date)

    if score >= threshold:
        # Check if an open flag already exists
        existing_flag = RiskFlag.objects.filter(student=student, status='open').first()
        if existing_flag:
            existing_flag.score = score
            existing_flag.reasons = reasons
            existing_flag.save(update_fields=['score', 'reasons', 'updated_at'])
            return existing_flag, getattr(existing_flag, 'task', None)

        flag = RiskFlag.objects.create(
            student=student,
            score=score,
            reasons=reasons,
            status='open'
        )
        task = CounsellorTask.objects.create(
            risk_flag=flag,
            status='open'
        )
        return flag, task

    return None, None
