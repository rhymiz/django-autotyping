from django.http import HttpResponse
from django.urls import path


def view(request, *args, **kwargs):
    return HttpResponse()


urlpatterns = [
    path("items/", view, name="item-list"),
    path("items.<str:format>/", view, name="item-list"),
    path("items/<int:pk>/", view, name="item-detail"),
    path("items/<int:pk>.<str:format>/", view, name="item-detail"),
]
