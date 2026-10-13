import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0018_project_ai_preprompt"),
    ]

    operations = [
        migrations.AlterModelTable(name="buddylink", table="buddies_buddylink"),
        migrations.AlterModelTable(name="buddyinvite", table="buddies_buddyinvite"),
        migrations.RenameModel(old_name="BuddyLink", new_name="ContactLink"),
        migrations.RenameModel(old_name="BuddyInvite", new_name="ContactInvite"),
        migrations.AlterField(
            model_name="contactlink",
            name="user_a",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_links_a", to="feusers.feuser"),
        ),
        migrations.AlterField(
            model_name="contactlink",
            name="user_b",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_links_b", to="feusers.feuser"),
        ),
        migrations.AlterField(
            model_name="contactinvite",
            name="inviter",
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="contact_invites_sent", to="feusers.feuser"),
        ),
        migrations.AlterField(
            model_name="dummyuser",
            name="owning_feuser",
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name="offline_contacts", to="feusers.feuser"),
        ),
    ]
