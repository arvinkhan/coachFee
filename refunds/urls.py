from django.urls import path
from refunds import views

app_name = 'refunds'

urlpatterns = [
    path('', views.refund_list, name='list'),
    path('calculate/<str:student_id>/', views.calculate_view, name='calculate'),
    path('<int:request_id>/approve/', views.approve_refund, name='approve'),
    path('<int:request_id>/reject/', views.reject_refund, name='reject'),
]
