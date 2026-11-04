from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.contrib import messages
from django.utils import timezone

from ledger.models import Student
from risk.models import CounsellorTask, RiskFlag, Attendance, TestScore
from risk.services import scan_student_and_create_task, evaluate_student_risk


@login_required
def risk_tasks(request):
    """
    Staff / Counsellor Task Management Interface.
    Displays open tasks triggered by the transparent risk rule engine.
    """
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    status_filter = request.GET.get('status', 'open')
    tasks = CounsellorTask.objects.select_related('risk_flag__student__batch__centre').order_by('-created_at')

    if status_filter in ('open', 'completed', 'dismissed'):
        tasks = tasks.filter(status=status_filter)

    return render(request, 'risk/tasks.html', {
        'tasks': tasks,
        'status_filter': status_filter,
    })


@login_required
def update_task(request, task_id):
    """Action or dismiss a counsellor risk task."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    task = get_object_or_404(CounsellorTask.objects.select_related('risk_flag__student'), id=task_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        notes = request.POST.get('notes', '').strip()

        if action == 'action':
            task.status = 'completed'
            task.notes = notes
            task.assignee = request.user
            task.save(update_fields=['status', 'notes', 'assignee', 'updated_at'])

            task.risk_flag.status = 'actioned'
            task.risk_flag.save(update_fields=['status', 'updated_at'])
            messages.success(request, f"Task for {task.risk_flag.student.name} marked as completed.")

        elif action == 'false_flag':
            task.status = 'dismissed'
            task.notes = f"[False Positive] {notes}"
            task.assignee = request.user
            task.save(update_fields=['status', 'notes', 'assignee', 'updated_at'])

            task.risk_flag.status = 'false_flag'
            task.risk_flag.save(update_fields=['status', 'updated_at'])
            messages.info(request, f"Marked as false positive. Repeat flags suppressed for 30 days for {task.risk_flag.student.name}.")

    return redirect('risk:tasks')


@login_required
def student_academics(request, student_id):
    """
    View attendance and test scores for a student.
    Accessible to parents for their own children, and staff.
    """
    if hasattr(request.user, 'guardian_profile'):
        student = get_object_or_404(Student, student_id=student_id, guardian=request.user.guardian_profile)
    else:
        student = get_object_or_404(Student, student_id=student_id)

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

    return render(request, 'risk/academics.html', {
        'student': student,
        'attendance_records': attendance_records[:20],
        'total_days': total_days,
        'present_days': present_days,
        'attendance_pct': attendance_pct,
        'test_scores': enriched_scores,
    })


@login_required
def trigger_risk_scan(request):
    """Staff action to scan all students for risk flags."""
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    if request.method == 'POST':
        created_count = 0
        for student in Student.objects.filter(is_active=True):
            flag, task = scan_student_and_create_task(student)
            if task and task.status == 'open':
                created_count += 1
        messages.success(request, f"Risk scan completed. {created_count} open task(s) active.")

    return redirect('risk:tasks')
