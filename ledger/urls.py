from django.urls import path
from ledger import views

app_name = 'ledger'

urlpatterns = [
    path('', views.home, name='home'),
    path('parent/', views.parent_dashboard, name='parent_dashboard'),
    path('parent/receipts/', views.parent_receipts, name='parent_receipts'),
    path('parent/receipts/<str:student_id>/', views.parent_receipts, name='parent_student_receipts'),
    path('dashboard/', views.staff_dashboard, name='dashboard'),
    path('students/', views.student_list, name='student_list'),
    path('students/<str:student_id>/', views.student_detail, name='student_detail'),
    path('export-tally/', views.export_csv, name='export_csv'),
]
