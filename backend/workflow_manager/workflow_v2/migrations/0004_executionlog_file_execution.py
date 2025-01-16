# Generated by Django 4.2.1 on 2025-01-02 10:34

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("file_execution", "0001_initial"),
        ("workflow_v2", "0003_workflowexecution_result_acknowledged"),
    ]

    operations = [
        migrations.AddField(
            model_name="executionlog",
            name="file_execution",
            field=models.ForeignKey(
                blank=True,
                db_comment="Foreign key from WorkflowFileExecution model",
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="execution_logs",
                to="file_execution.workflowfileexecution",
            ),
        ),
    ]
