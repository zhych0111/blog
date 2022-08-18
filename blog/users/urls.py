from django.urls import path

import users.views
from users.views import RegisterView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
]