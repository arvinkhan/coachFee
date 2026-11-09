from django.db import models
from django.utils import timezone


class Centre(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=10, unique=True)
    address = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Batch(models.Model):
    centre = models.ForeignKey(Centre, on_delete=models.PROTECT, related_name='batches')
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'batches'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.centre.code})"

    @property
    def total_days(self):
        return (self.end_date - self.start_date).days


class FeePlan(models.Model):
    """Fee plan template. Amounts stored in paise (integer)."""
    name = models.CharField(max_length=100)
    total_amount = models.PositiveBigIntegerField(help_text='Total fee in paise')
    registration_fee = models.PositiveBigIntegerField(default=500000, help_text='Registration fee in paise (default ₹5,000)')
    gst_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18, help_text='GST percentage')
    number_of_instalments = models.PositiveSmallIntegerField(default=4)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    @property
    def tuition_amount(self):
        """Fee minus registration fee."""
        return self.total_amount - self.registration_fee


class Student(models.Model):
    student_id = models.CharField(max_length=20, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name='students')
    guardian = models.ForeignKey(
        'accounts.Guardian',
        on_delete=models.PROTECT,
        related_name='students',
    )
    fee_plan = models.ForeignKey(FeePlan, on_delete=models.PROTECT, related_name='students')
    enrollment_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['student_id']

    def __str__(self):
        return f"{self.student_id} — {self.name}"


class Instalment(models.Model):
    """Individual instalment for a student. Amount in paise."""
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='instalments')
    sequence = models.PositiveSmallIntegerField()
    amount = models.PositiveBigIntegerField(help_text='Instalment amount in paise')
    due_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['due_date', 'sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'sequence'],
                name='unique_student_instalment',
            )
        ]

    def __str__(self):
        return f"{self.student.student_id} — Inst #{self.sequence}"

    @property
    def amount_display(self):
        return self.amount / 100


class Discount(models.Model):
    """Discount applied to a student's total fee. Amount in paise."""
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='discounts')
    amount = models.PositiveBigIntegerField(help_text='Discount in paise')
    reason = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Discount ₹{self.amount / 100:.0f} — {self.student.student_id}"


class Payment(models.Model):
    """Payment received from a student. Amount in paise."""
    PAYMENT_MODES = [
        ('gateway', 'Online Gateway'),
        ('cash', 'Cash'),
        ('bank', 'Bank Transfer'),
    ]

    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name='payments')
    amount = models.PositiveBigIntegerField(help_text='Payment amount in paise')
    mode = models.CharField(max_length=20, choices=PAYMENT_MODES)
    gateway_ref = models.CharField(max_length=100, unique=True, null=True, blank=True)
    received_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"Rs. {self.amount / 100:.0f} from {self.student.student_id}"

    @property
    def amount_display(self):
        return self.amount / 100


class PaymentAllocation(models.Model):
    """Maps a payment to one or more instalments. Amount in paise."""
    payment = models.ForeignKey(Payment, on_delete=models.PROTECT, related_name='allocations')
    instalment = models.ForeignKey(Instalment, on_delete=models.PROTECT, related_name='allocations')
    amount = models.PositiveBigIntegerField(help_text='Allocated amount in paise')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['payment', 'instalment'],
                name='unique_payment_allocation',
            )
        ]

    def __str__(self):
        return f"Rs. {self.amount / 100:.0f} -> Inst #{self.instalment.sequence}"

    @property
    def amount_display(self):
        return self.amount / 100


class Receipt(models.Model):
    """GST receipt for a payment. All amounts in paise."""
    payment = models.OneToOneField(Payment, on_delete=models.PROTECT, related_name='receipt')
    receipt_number = models.CharField(max_length=50, unique=True)
    base_amount = models.PositiveBigIntegerField()
    gst_amount = models.PositiveBigIntegerField()
    total_amount = models.PositiveBigIntegerField()
    issued_at = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return self.receipt_number

    @property
    def base_amount_display(self):
        return self.base_amount / 100

    @property
    def gst_amount_display(self):
        return self.gst_amount / 100

    @property
    def total_amount_display(self):
        return self.total_amount / 100
