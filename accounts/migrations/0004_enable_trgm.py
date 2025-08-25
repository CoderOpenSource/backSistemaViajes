from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0003_remove_auditlog_accounts_au_entity_08ba2d_idx_and_more'),
        ]
    operations = [
        TrigramExtension(),
    ]
