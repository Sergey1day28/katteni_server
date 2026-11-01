from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({'ok': True, 'data': {'service': 'katteni_server'}})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health),
    path('agent/v1/', include('farm_agent_api.urls')),
    path('api/v1/', include('farm_api.urls')),
    path('farm/', include('farm_console.urls')),
]
