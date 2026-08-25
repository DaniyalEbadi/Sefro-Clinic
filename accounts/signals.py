from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_system_admin(sender, **kwargs):
    """Create the configured system admin once. Never touches an existing
    account, so passwords changed later are not reverted on redeploy."""
    if sender.name != 'accounts':
        return

    user_model = get_user_model()
    admin_config = settings.CLINIC_ADMIN
    username = admin_config['username']
    if user_model.objects.filter(username=username).exists():
        return

    user_model.objects.create_user(
        username=username,
        password=admin_config['password'],
        first_name=admin_config.get('first_name', ''),
        last_name=admin_config.get('last_name', ''),
        role=user_model.Role.ADMIN,
        is_staff=True,
        is_superuser=True,
        is_active=True,
    )
