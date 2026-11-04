from django.urls import path
from risk import views

app_name = 'risk'

urlpatterns = [
    path('tasks/', views.risk_tasks, name='tasks'),
    path('tasks/<int:task_id>/update/', views.update_task, name='update_task'),
    path('academics/<str:student_id>/', views.student_academics, name='academics'),
    path('scan/', views.trigger_risk_scan, name='scan'),
]
