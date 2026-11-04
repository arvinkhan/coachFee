from django.conf import settings
from django.db import models


class RiskFlag(models.Model):
    """Dropout-risk flag for a student. Score 0–100."""

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('actioned', 'Actioned'),
        ('false_flag', 'False Positive'),
    ]

    student = models.ForeignKey(
        'ledger.Student', on_delete=models.PROTECT, related_name='risk_flags'
    )
    score = models.PositiveSmallIntegerField(help_text='Risk score 0–100')
    reasons = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Risk {self.score} — {self.student.student_id} ({self.status})"


class CounsellorTask(models.Model):
    """Task created from a risk flag. Assigned to a counsellor."""

    STATUS_CHOICES = [
        ('open', 'Open'),
        ('completed', 'Completed'),
        ('dismissed', 'Dismissed'),
    ]

    risk_flag = models.OneToOneField(
        RiskFlag, on_delete=models.CASCADE, related_name='task'
    )
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='counsellor_tasks',
    )
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Task for {self.risk_flag.student.student_id}"


class Attendance(models.Model):
    """Daily attendance record for a student."""

    student = models.ForeignKey(
        'ledger.Student', on_delete=models.PROTECT, related_name='attendance_records'
    )
    date = models.DateField()
    present = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'date'],
                name='unique_student_attendance',
            )
        ]

    def __str__(self):
        status = 'Present' if self.present else 'Absent'
        return f"{self.student.student_id} — {self.date} — {status}"


class TestScore(models.Model):
    """Test score record for a student."""

    student = models.ForeignKey(
        'ledger.Student', on_delete=models.PROTECT, related_name='test_scores'
    )
    test_name = models.CharField(max_length=100)
    date = models.DateField()
    score = models.PositiveIntegerField()
    max_score = models.PositiveIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"{self.student.student_id} — {self.test_name} — {self.score}/{self.max_score}"
