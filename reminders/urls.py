from django.urls import path
from reminders import views

app_name = 'reminders'

urlpatterns = [
    path('log/', views.reminder_log, name='log'),
    path('trigger/', views.trigger_reminders, name='trigger'),
]
