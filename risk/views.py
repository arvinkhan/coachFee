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


@login_required
def bulk_upload_academics(request):
    """
    Staff bulk upload interface for batch attendance and periodic test scores via CSV.
    """
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    import csv
    import io
    from datetime import datetime
    from ledger.models import Batch, Student

    batches = Batch.objects.select_related('centre').all()
    active_tab = request.GET.get('tab', 'attendance')

    if request.method == 'POST':
        upload_type = request.POST.get('upload_type')
        batch_id = request.POST.get('batch_id')
        batch = get_object_or_404(Batch, id=batch_id)
        csv_file = request.FILES.get('csv_file')

        if not csv_file:
            messages.error(request, "Please select a valid CSV file to upload.")
            return redirect(f"{request.path}?tab={upload_type}")

        if not csv_file.name.lower().endswith('.csv'):
            messages.error(request, "Uploaded file must be in .csv format.")
            return redirect(f"{request.path}?tab={upload_type}")

        try:
            decoded_file = csv_file.read().decode('utf-8-sig')
            reader = csv.DictReader(io.StringIO(decoded_file))
        except Exception as e:
            messages.error(request, f"Error parsing CSV file: {e}")
            return redirect(f"{request.path}?tab={upload_type}")

        if upload_type == 'attendance':
            date_str = request.POST.get('date')
            try:
                att_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except Exception:
                messages.error(request, "Please provide a valid attendance date.")
                return redirect(f"{request.path}?tab=attendance")

            success_count = 0
            errors = []
            for row_idx, row in enumerate(reader, start=2):
                sid = row.get('student_id', '').strip()
                status_val = row.get('status', '').strip().lower()
                if not sid:
                    continue
                student = Student.objects.filter(student_id=sid, batch=batch).first()
                if not student:
                    errors.append(f"Row {row_idx}: Student '{sid}' not in {batch.name}")
                    continue

                is_present = status_val in ('present', 'p', '1', 'true', 'yes')
                Attendance.objects.update_or_create(
                    student=student,
                    date=att_date,
                    defaults={'present': is_present}
                )
                success_count += 1

            if errors:
                messages.warning(request, f"Attendance saved for {success_count} students. Note: {', '.join(errors[:3])}")
            else:
                messages.success(request, f"Successfully uploaded attendance for {success_count} students in {batch.name} on {att_date}.")
            return redirect(f"{request.path}?tab=attendance")

        elif upload_type == 'test_scores':
            test_name = request.POST.get('test_name', '').strip()
            date_str = request.POST.get('test_date')
            max_score_val = request.POST.get('max_score')

            if not test_name:
                messages.error(request, "Please specify a test name.")
                return redirect(f"{request.path}?tab=test_scores")

            try:
                test_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                max_score = int(max_score_val)
                if max_score <= 0:
                    raise ValueError
            except Exception:
                messages.error(request, "Please provide a valid test date and maximum marks (>0).")
                return redirect(f"{request.path}?tab=test_scores")

            success_count = 0
            errors = []
            for row_idx, row in enumerate(reader, start=2):
                sid = row.get('student_id', '').strip()
                score_str = row.get('score', '').strip()
                if not sid or not score_str:
                    continue
                student = Student.objects.filter(student_id=sid, batch=batch).first()
                if not student:
                    errors.append(f"Row {row_idx}: Student '{sid}' not in {batch.name}")
                    continue

                try:
                    score = int(float(score_str))
                    if score < 0 or score > max_score:
                        errors.append(f"Row {row_idx}: Score {score} for {sid} out of bounds (0–{max_score})")
                        continue
                except ValueError:
                    errors.append(f"Row {row_idx}: Invalid score '{score_str}' for {sid}")
                    continue

                TestScore.objects.update_or_create(
                    student=student,
                    test_name=test_name,
                    date=test_date,
                    defaults={'score': score, 'max_score': max_score}
                )
                success_count += 1

            if errors:
                messages.warning(request, f"Recorded scores for {success_count} students. Issues: {', '.join(errors[:3])}")
            else:
                messages.success(request, f"Successfully uploaded '{test_name}' scores for {success_count} students in {batch.name}.")
            return redirect(f"{request.path}?tab=test_scores")

    return render(request, 'risk/bulk_upload.html', {
        'batches': batches,
        'active_tab': active_tab,
        'today': timezone.now().date().isoformat(),
    })


@login_required
def download_sample_csv(request, upload_type, batch_id):
    """
    Generates a pre-filled sample CSV containing all enrolled students in the batch.
    """
    if hasattr(request.user, 'guardian_profile'):
        return HttpResponseForbidden("Not authorized.")

    import csv
    from django.http import HttpResponse
    from ledger.models import Batch, Student

    batch = get_object_or_404(Batch, id=batch_id)
    students = Student.objects.filter(batch=batch, is_active=True).order_by('student_id')

    response = HttpResponse(content_type='text/csv')
    clean_batch_name = batch.name.replace(" ", "_")

    if upload_type == 'attendance':
        response['Content-Disposition'] = f'attachment; filename="attendance_{clean_batch_name}.csv"'
        writer = csv.writer(response)
        writer.writerow(['student_id', 'student_name', 'status'])
        for s in students:
            writer.writerow([s.student_id, s.name, 'Present'])
    else:
        response['Content-Disposition'] = f'attachment; filename="test_scores_{clean_batch_name}.csv"'
        writer = csv.writer(response)
        writer.writerow(['student_id', 'student_name', 'score'])
        for s in students:
            writer.writerow([s.student_id, s.name, ''])

    return response
