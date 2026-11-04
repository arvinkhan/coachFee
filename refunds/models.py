from django.db import models


class RefundRequest(models.Model):
    """Pro-rata refund request. All amounts in paise."""

    STATUS_CHOICES = [
        ('pending', 'Pending Review'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('processed', 'Processed'),
    ]

    student = models.ForeignKey(
        'ledger.Student', on_delete=models.PROTECT, related_name='refund_requests'
    )
    leave_date = models.DateField()
    total_paid = models.PositiveBigIntegerField(help_text='Total paid in paise')
    registration_deduction = models.PositiveBigIntegerField(default=0)
    pro_rata_usage = models.PositiveBigIntegerField(default=0, help_text='Pro-rata used fee in paise')
    gst_adjustment = models.PositiveBigIntegerField(default=0)
    refund_amount = models.PositiveBigIntegerField(default=0, help_text='Final refund in paise')
    breakdown = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    due_by = models.DateField(help_text='Refund must be processed by this date')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    processed_by = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Refund {self.student.student_id} — ₹{self.refund_amount / 100:.0f}"
