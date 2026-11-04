from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    path('auth/', include('accounts.urls')),
    path('', include('ledger.urls')),
    path('payments/', include('payments.urls')),
    path('reminders/', include('reminders.urls')),
    path('refunds/', include('refunds.urls')),
    path('risk/', include('risk.urls')),
]
