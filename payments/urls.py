from django.urls import path
from payments import views

app_name = 'payments'

urlpatterns = [
    path('pay/<int:instalment_id>/', views.pay_instalment, name='pay'),
    path('process/<uuid:token>/', views.process_payment_simulation, name='process'),
    path('webhook/', views.webhook_endpoint, name='webhook'),
    path('success/<int:payment_id>/', views.payment_success, name='success'),
    path('unmatched/', views.unmatched_queue, name='unmatched'),
    path('unmatched/<int:unmatched_id>/resolve/', views.resolve_unmatched, name='resolve_unmatched'),
]
