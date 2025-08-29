# migrations/0002_enable_trigram.py
from django.db import migrations
from django.contrib.postgres.operations import TrigramExtension

class Migration(migrations.Migration):
    dependencies = [("passenger", "0001_initial")]
    operations = [TrigramExtension()]
