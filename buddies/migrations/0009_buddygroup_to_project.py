import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("buddies", "0008_buddygroup_description"),
        ("budget", "0016_expense_buddy_group"),
    ]

    operations = [
        # Rename models (keeps data, renames tables)
        migrations.RenameModel("BuddyGroup", "Project"),
        migrations.RenameModel("BuddyGroupMember", "ProjectMember"),
        migrations.RenameModel("BuddyGroupInvite", "ProjectInvite"),

        # New fields on Project
        migrations.AddField(
            model_name="project",
            name="archived",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="project",
            name="last_mod",
            field=models.DateTimeField(default=django.utils.timezone.now),
            preserve_default=False,
        ),

        # New field on ProjectMember
        migrations.AddField(
            model_name="projectmember",
            name="sorting",
            field=models.IntegerField(default=1),
        ),
    ]
