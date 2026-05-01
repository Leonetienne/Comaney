from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("budget", "0010_created_at"),
    ]

    operations = [
        migrations.AlterField(
            model_name="category",
            name="title",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="tag",
            name="title",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="expense",
            name="title",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="expense",
            name="payee",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name="expense",
            name="note",
            field=models.TextField(blank=True, max_length=1024),
        ),
        migrations.AlterField(
            model_name="scheduledexpense",
            name="title",
            field=models.CharField(max_length=128),
        ),
        migrations.AlterField(
            model_name="scheduledexpense",
            name="payee",
            field=models.CharField(blank=True, max_length=128),
        ),
        migrations.AlterField(
            model_name="scheduledexpense",
            name="note",
            field=models.TextField(blank=True, max_length=1024),
        ),
    ]
