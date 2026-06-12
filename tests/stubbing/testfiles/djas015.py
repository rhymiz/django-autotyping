from django.urls import reverse

reverse("item-list")
reverse("item-list", kwargs={})
reverse("item-list", kwargs={"format": "json"})

for route_name in ["item-list"]:
    reverse(route_name)

reverse("item-detail", kwargs={"pk": 1})
reverse("item-detail", kwargs={"pk": 1, "format": "json"})
