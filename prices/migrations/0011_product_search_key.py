from django.db import migrations, models


def backfill_search_key(apps, schema_editor):
    from prices.textnorm import normalize_text

    Product = apps.get_model("prices", "Product")
    for product in Product.objects.all():
        product.search_key = normalize_text(product.name)
        product.save(update_fields=["search_key"])


class Migration(migrations.Migration):

    dependencies = [
        ('prices', '0010_confirmations_and_alerts'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='search_key',
            field=models.CharField(blank=True, default='', editable=False, max_length=300),
        ),
        migrations.RunPython(backfill_search_key, migrations.RunPython.noop),
    ]
