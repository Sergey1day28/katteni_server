from django.urls import path

from farm_api.views import api_v1

urlpatterns = [
    path('<path:route>', api_v1),
]
