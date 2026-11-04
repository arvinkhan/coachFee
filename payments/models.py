import uuid

from django.db import models


class PaymentLink(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('expired', 'Expired'),
    ]

    instalment = models.ForeignKey(
        'ledger.Instalment',
        on_delete=models.PROTECT,
        related_name='payment_links'
    )

    token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    created_at = models.DateTimeField(auto_now_add=True)

    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Payment link - {self.instalment}"

class GatewayEvent(models.Model):

    STATUS_CHOICES = [
        ('received', 'Received'),
        ('processed', 'Processed'),
        ('rejected', 'Rejected'),
    ]

    gateway_ref = models.CharField(
        max_length=100,
        unique=True
    )

    payment_link = models.ForeignKey(
        PaymentLink,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='gateway_events'
    )

    amount = models.PositiveBigIntegerField()

    signature_valid = models.BooleanField(default=False)

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='received'
    )

    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.gateway_ref

class UnmatchedPayment(models.Model):

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('matched', 'Matched'),
        ('rejected', 'Rejected'),
    ]

    gateway_ref = models.CharField(
        max_length=100,
        unique=True
    )

    amount = models.PositiveBigIntegerField()

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )

    resolved_payment = models.ForeignKey(
        'ledger.Payment',
        on_delete=models.PROTECT,
        null=True,
        blank=True
    )

    received_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Unmatched - {self.gateway_ref}"