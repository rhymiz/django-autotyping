from django.urls import reverse

reverse("item-list")
reverse("item-list", kwargs={})
reverse("item-list", kwargs={"format": "json"})

reverse("item-detail")  # type: ignore
reverse("item-detail", kwargs={"pk": 1})
reverse("item-detail", kwargs={"pk": 1, "format": "json"})
