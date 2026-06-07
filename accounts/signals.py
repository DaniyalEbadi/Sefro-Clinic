from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate
from django.dispatch import receiver


@receiver(post_migrate)
def ensure_system_admin(sender, **kwargs):
    if sender.name != 'accounts':
        return

    user_model = get_user_model()
    admin_config = settings.CLINIC_ADMIN
    username = admin_config['username']
    user = user_model.objects.filter(username=username).first()
    if user is None:
        user = user_model(
            username=username,
            first_name=admin_config.get('first_name', ''),
            last_name=admin_config.get('last_name', ''),
            role=user_model.Role.ADMIN,
            is_staff=True,
            is_superuser=True,
            is_active=True,
        )

    if not user.password or not user.check_password(admin_config['password']):
        user.set_password(admin_config['password'])

    user.role = user_model.Role.ADMIN
    user.is_staff = True
    user.is_superuser = True
    user.is_active = True
    user.first_name = admin_config.get('first_name', user.first_name)
    user.last_name = admin_config.get('last_name', user.last_name)
    user.save()
