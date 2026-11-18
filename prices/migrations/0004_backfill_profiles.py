from django.conf import settings
from django.db import migrations


def create_missing_profiles(apps, schema_editor):
    app_label, model_name = settings.AUTH_USER_MODEL.split(".")
    User = apps.get_model(app_label, model_name)
    Profile = apps.get_model("prices", "Profile")
    existing = set(Profile.objects.values_list("user_id", flat=True))
    Profile.objects.bulk_create(
        [Profile(user_id=pk) for pk in User.objects.values_list("pk", flat=True) if pk not in existing]
    )


class Migration(migrations.Migration):

    dependencies = [
        ("prices", "0003_profile"),
    ]

    operations = [
        migrations.RunPython(create_missing_profiles, migrations.RunPython.noop),
    ]
