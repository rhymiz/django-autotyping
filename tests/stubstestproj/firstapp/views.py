from django.views.generic import DeleteView

from .models import ModelOne


class ModelOneDeleteView(DeleteView):
    model = ModelOne
