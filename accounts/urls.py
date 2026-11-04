from django.urls import path
from accounts import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.login_landing, name='login'),
    path('parent-login/', views.parent_login, name='parent_login'),
    path('staff-login/', views.staff_login, name='staff_login'),
    path('logout/', views.user_logout, name='logout'),
    path('toggle-language/', views.toggle_language, name='toggle_language'),
]
