from django.urls import path

from farm_agent_api.views import ack, poll, result

urlpatterns = [
    path('poll', poll),
    path('commands/<uuid:command_id>/ack', ack),
    path('commands/<uuid:command_id>/result', result),
]
