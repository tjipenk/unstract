# Generated by Django 4.2.1 on 2024-09-25 09:55

import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("workflow_v2", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("account_v2", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="Pipeline",
            fields=[
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("modified_at", models.DateTimeField(auto_now=True)),
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                (
                    "pipeline_name",
                    models.CharField(default="", max_length=32, unique=True),
                ),
                ("app_id", models.TextField(blank=True, max_length=32, null=True)),
                (
                    "active",
                    models.BooleanField(
                        db_comment="Indicates whether the pipeline is active",
                        default=False,
                    ),
                ),
                (
                    "scheduled",
                    models.BooleanField(
                        db_comment="Indicates whether the pipeline is scheduled",
                        default=False,
                    ),
                ),
                (
                    "cron_string",
                    models.TextField(
                        blank=True,
                        db_comment="UNIX cron string",
                        max_length=256,
                        null=True,
                    ),
                ),
                (
                    "pipeline_type",
                    models.CharField(
                        choices=[
                            ("ETL", "ETL"),
                            ("TASK", "TASK"),
                            ("DEFAULT", "Default"),
                            ("APP", "App"),
                        ],
                        default="DEFAULT",
                    ),
                ),
                ("run_count", models.IntegerField(default=0)),
                ("last_run_time", models.DateTimeField(blank=True, null=True)),
                (
                    "last_run_status",
                    models.CharField(
                        choices=[
                            ("SUCCESS", "Success"),
                            ("FAILURE", "Failure"),
                            ("INPROGRESS", "Inprogress"),
                            ("YET_TO_START", "Yet to start"),
                            ("RESTARTING", "Restarting"),
                            ("PAUSED", "Paused"),
                        ],
                        default="YET_TO_START",
                    ),
                ),
                (
                    "app_icon",
                    models.URLField(
                        blank=True,
                        db_comment="Field to store icon url for Apps",
                        null=True,
                    ),
                ),
                (
                    "app_url",
                    models.URLField(
                        blank=True, db_comment="Stores deployed URL for App", null=True
                    ),
                ),
                ("access_control_bundle_id", models.TextField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="created_pipeline",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "modified_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="modified_pipeline",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "organization",
                    models.ForeignKey(
                        blank=True,
                        db_comment="Foreign key reference to the Organization model.",
                        default=None,
                        null=True,
                        on_delete=django.db.models.deletion.CASCADE,
                        to="account_v2.organization",
                    ),
                ),
                (
                    "workflow",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="pipeline_workflows",
                        to="workflow_v2.workflow",
                    ),
                ),
            ],
            options={
                "verbose_name": "Pipeline",
                "verbose_name_plural": "Pipelines",
                "db_table": "pipeline",
            },
        ),
        migrations.AddConstraint(
            model_name="pipeline",
            constraint=models.UniqueConstraint(
                fields=("id", "pipeline_type"), name="unique_pipeline"
            ),
        ),
    ]
