"""
Media file cleanup on deletion.

Verifies that profile pictures and group background images are removed from
disk when the owning model instance is deleted, including via CASCADE.
All assertions are done against the Docker container's filesystem via _shell.
"""
import pytest

from bhelpers import _shell
from helpers import setup_user, cleanup_user


def _file_exists(path_expr: str) -> bool:
    """Return True if a path (given as a Python expression) exists in the container."""
    return _shell(
        f"import pathlib; print(pathlib.Path({path_expr}).exists())"
    ).strip() == "True"


def _make_file(path_expr: str) -> None:
    """Create a file (and its parent dirs) inside the container."""
    _shell(
        f"import pathlib; p = pathlib.Path({path_expr}); "
        f"p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x')"
    )


# ---------------------------------------------------------------------------
# DummyUser (offline buddy) picture - explicit delete
# ---------------------------------------------------------------------------

class TestDummyPictureCleanupOnDelete:
    """Deleting a DummyUser must remove its profile picture from disk."""

    @pytest.fixture(scope="class")
    def ctx(self, driver, w):
        user = setup_user(driver, w, first_name="Dpic", last_name="Owner")
        dummy_pk = _shell(
            f"from feusers.models import FeUser; from buddies.models import DummyUser; "
            f"u = FeUser.objects.get(email='{user['email']}'); "
            f"d = DummyUser.objects.create(owning_feuser=u, display_name='PicDummy'); "
            f"print(d.pk)"
        )
        yield {"user": user, "dummy_pk": dummy_pk.strip()}
        cleanup_user(user["email"])

    def test_dummy_picture_cleaned_up_on_delete(self, driver, w, ctx):
        pk = ctx["dummy_pk"]
        path_expr = f"__import__('django.conf', fromlist=['settings']).settings.MEDIA_ROOT / 'offline-buddy-ppic' / '{pk}.jpg'"
        _shell(
            f"from django.conf import settings; from buddies.models import DummyUser; "
            f"import pathlib; "
            f"p = settings.MEDIA_ROOT / 'offline-buddy-ppic' / '{pk}.jpg'; "
            f"p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            f"d = DummyUser.objects.get(pk={pk}); "
            f"d.profile_picture = True; d.save(update_fields=['profile_picture']); "
            f"d.delete()"
        )
        exists = _shell(
            f"from django.conf import settings; import pathlib; "
            f"print((settings.MEDIA_ROOT / 'offline-buddy-ppic' / '{pk}.jpg').exists())"
        ).strip()
        assert exists == "False", "DummyUser picture must be deleted when dummy is deleted"


# ---------------------------------------------------------------------------
# DummyUser picture - CASCADE from owning FeUser deletion
# ---------------------------------------------------------------------------

class TestDummyPictureCleanupOnUserCascade:
    """Deleting a FeUser must also remove pictures of all their personal dummies."""

    def test_dummy_picture_cleaned_up_on_user_delete(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; from buddies.models import DummyUser; "
            "from django.conf import settings; import pathlib; "
            "u = FeUser.objects.create(email='cascade-dummy-ppic@example.test', "
            "  password='!', is_active=True, is_confirmed=True); "
            "d = DummyUser.objects.create(owning_feuser=u, display_name='CascDummy', profile_picture=True); "
            "p = settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{d.pk}.jpg'; "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            "pk = d.pk; "
            "u.delete(); "
            "print((settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{pk}.jpg').exists())"
        ).strip()
        assert result == "False", "Dummy picture must be deleted when owning user is deleted (CASCADE)"


# ---------------------------------------------------------------------------
# DummyUser picture - CASCADE from owning BuddyGroup deletion
# ---------------------------------------------------------------------------

class TestDummyPictureCleanupOnGroupCascade:
    """Deleting a BuddyGroup must also remove pictures of its group dummies."""

    def test_dummy_picture_cleaned_up_on_group_delete(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; from buddies.models import DummyUser, BuddyGroup; "
            "from django.conf import settings; import pathlib; "
            "u = FeUser.objects.create(email='cascade-group-ppic@example.test', "
            "  password='!', is_active=True, is_confirmed=True); "
            "g = BuddyGroup.objects.create(name='CascGroup', admin_feuser=u); "
            "d = DummyUser.objects.create(owning_group=g, display_name='CascGroupDummy', profile_picture=True); "
            "p = settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{d.pk}.jpg'; "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            "pk = d.pk; "
            "g.delete(); "
            "u.delete(); "
            "print((settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{pk}.jpg').exists())"
        ).strip()
        assert result == "False", "Dummy picture must be deleted when owning group is deleted (CASCADE)"


# ---------------------------------------------------------------------------
# BuddyGroup background picture - explicit delete
# ---------------------------------------------------------------------------

class TestGroupPictureCleanupOnDelete:
    """Deleting a BuddyGroup must remove its background picture from disk."""

    def test_group_picture_cleaned_up_on_delete(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            "from django.conf import settings; import pathlib; "
            "u = FeUser.objects.create(email='group-pic-cleanup@example.test', "
            "  password='!', is_active=True, is_confirmed=True); "
            "g = BuddyGroup.objects.create(name='PicGroup', admin_feuser=u, group_picture=True); "
            "p = settings.MEDIA_ROOT / 'bgpics' / f'{g.pk}.webp'; "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            "pk = g.pk; "
            "g.delete(); "
            "u.delete(); "
            "print((settings.MEDIA_ROOT / 'bgpics' / f'{pk}.webp').exists())"
        ).strip()
        assert result == "False", "Group picture must be deleted when group is deleted"


# ---------------------------------------------------------------------------
# BuddyGroup picture - CASCADE from admin FeUser deletion
# ---------------------------------------------------------------------------

class TestGroupPictureCleanupOnUserCascade:
    """Deleting a FeUser who is the sole admin must also remove the group's picture."""

    def test_group_picture_cleaned_up_on_admin_user_delete(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; from buddies.models import BuddyGroup; "
            "from django.conf import settings; import pathlib; "
            "u = FeUser.objects.create(email='user-group-pic-casc@example.test', "
            "  password='!', is_active=True, is_confirmed=True); "
            "g = BuddyGroup.objects.create(name='AdminPicGroup', admin_feuser=u, group_picture=True); "
            "p = settings.MEDIA_ROOT / 'bgpics' / f'{g.pk}.webp'; "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            "gpk = g.pk; "
            "u.delete(); "
            "print((settings.MEDIA_ROOT / 'bgpics' / f'{gpk}.webp').exists())"
        ).strip()
        assert result == "False", "Group picture must be deleted when sole admin user is deleted (CASCADE)"


# ---------------------------------------------------------------------------
# dissolve_group: archive dummy picture cleaned, non-archive pictures survive
# ---------------------------------------------------------------------------

class TestDissolvePictureCleanup:
    """
    dissolve_group must:
    - clean up the archive dummy's picture (it is explicitly deleted)
    - NOT delete non-archive dummies' pictures (they are transferred to admin)
    """

    def test_dissolve_group_cleans_archive_picture_and_preserves_non_archive(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; "
            "from buddies.models import BuddyGroup, DummyUser, BuddyGroupMember; "
            "from buddies.services.group import BuddyGroupService; "
            "from django.conf import settings; import pathlib; "

            # admin user
            "admin = FeUser.objects.create(email='dissolve-pic@example.test', "
            "  password='!', is_active=True, is_confirmed=True); "

            # group
            "g = BuddyGroup.objects.create(name='DissolvePicGroup', admin_feuser=admin); "

            # archive dummy with a picture
            "arch = DummyUser.objects.create(owning_group=g, display_name='Achim Archive', "
            "  is_archive=True, profile_picture=True); "
            "BuddyGroupMember.objects.create(group=g, dummy=arch); "
            "arch_p = settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{arch.pk}.jpg'; "
            "arch_p.parent.mkdir(parents=True, exist_ok=True); arch_p.write_bytes(b'x'); "

            # regular group dummy with a picture
            "reg = DummyUser.objects.create(owning_group=g, display_name='RegDummy', profile_picture=True); "
            "BuddyGroupMember.objects.create(group=g, dummy=reg); "
            "reg_p = settings.MEDIA_ROOT / 'offline-buddy-ppic' / f'{reg.pk}.jpg'; "
            "reg_p.parent.mkdir(parents=True, exist_ok=True); reg_p.write_bytes(b'x'); "

            "arch_pk = arch.pk; reg_pk = reg.pk; "

            # dissolve the group
            "BuddyGroupService.dissolve_group(g, admin); "

            # results: archive picture gone, regular picture still there (dummy transferred, not deleted)
            "arch_gone = not arch_p.exists(); "
            "reg_alive = reg_p.exists(); "
            "reg_still_exists = DummyUser.objects.filter(pk=reg_pk).exists(); "

            # clean up
            "admin.delete(); "

            "print(arch_gone, reg_alive, reg_still_exists)"
        ).strip()

        parts = result.split()
        assert parts[0] == "True", "Archive dummy picture must be deleted after dissolve_group"
        assert parts[1] == "True", "Non-archive dummy picture must survive dissolve_group (dummy is transferred, not deleted)"
        assert parts[2] == "True", "Non-archive dummy itself must still exist after dissolve_group"


# ---------------------------------------------------------------------------
# FeUser profile picture - explicit delete
# ---------------------------------------------------------------------------

class TestUserPictureCleanupOnDelete:
    """Deleting a FeUser must remove their profile picture from disk."""

    def test_user_picture_cleaned_up_on_delete(self, driver, w):
        result = _shell(
            "from feusers.models import FeUser; "
            "from django.conf import settings; import pathlib; "
            "u = FeUser.objects.create(email='user-ppic-cleanup@example.test', "
            "  password='!', is_active=True, is_confirmed=True, profile_picture=True); "
            "p = settings.MEDIA_ROOT / 'ppics' / f'{u.pk}.jpg'; "
            "p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(b'x'); "
            "pk = u.pk; "
            "u.delete(); "
            "print((settings.MEDIA_ROOT / 'ppics' / f'{pk}.jpg').exists())"
        ).strip()
        assert result == "False", "User profile picture must be deleted when user is deleted"
