# -*- coding: utf-8 -*-
# Generated by Django 1.11 on 2017-05-01 15:30
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='AccessLog',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('raw_id', models.CharField(max_length=128)),
                ('access_time', models.DateTimeField(auto_now_add=True)),
                ('ip_address', models.CharField(max_length=16)),
                ('user_agent', models.CharField(max_length=512)),
                ('return_code', models.IntegerField()),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='Enclosure',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('length', models.IntegerField()),
                ('href', models.CharField(max_length=512)),
                ('type', models.CharField(max_length=256)),
            ],
        ),
        migrations.CreateModel(
            name='Post',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.TextField()),
                ('body', models.TextField()),
                ('link', models.CharField(blank=True, max_length=255, null=True)),
                ('found', models.DateTimeField()),
                ('created', models.DateTimeField(db_index=True)),
                ('guid', models.CharField(blank=True, db_index=True, max_length=255, null=True)),
                ('author', models.CharField(blank=True, max_length=255, null=True)),
                ('index', models.IntegerField(db_index=True)),
                ('image_url', models.CharField(blank=True, max_length=255, null=True)),
            ],
            options={
                'ordering': ['index'],
            },
        ),
        migrations.CreateModel(
            name='Source',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(blank=True, max_length=255, null=True)),
                ('site_url', models.CharField(blank=True, max_length=255, null=True)),
                ('feed_url', models.CharField(max_length=255)),
                ('image_url', models.CharField(blank=True, max_length=255, null=True)),
                ('last_polled', models.DateTimeField(blank=True, max_length=255, null=True)),
                ('due_poll', models.DateTimeField()),
                ('etag', models.CharField(blank=True, max_length=255, null=True)),
                ('last_modified', models.CharField(blank=True, max_length=255, null=True)),
                ('last_result', models.CharField(blank=True, max_length=255, null=True)),
                ('interval', models.PositiveIntegerField(default=400)),
                ('last_success', models.DateTimeField(null=True)),
                ('last_change', models.DateTimeField(null=True)),
                ('live', models.BooleanField(default=True)),
                ('status_code', models.PositiveIntegerField(default=0)),
                ('last_302_url', models.CharField(default=b' ', max_length=255)),
                ('last_302_start', models.DateTimeField(auto_now_add=True)),
                ('max_index', models.IntegerField(default=0)),
                ('num_subs', models.IntegerField(default=1)),
            ],
        ),
        migrations.CreateModel(
            name='Subscription',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('key', models.CharField(max_length=64, unique=True)),
                ('last_sent', models.IntegerField(default=1)),
                ('last_sent_date', models.DateTimeField()),
                ('frequency', models.IntegerField(default=5)),
                ('name', models.CharField(max_length=255)),
                ('complete', models.BooleanField(default=False)),
                ('created', models.DateTimeField(auto_now_add=True, null=True)),
                ('last_accessed', models.DateTimeField(auto_now_add=True, null=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rc.Source')),
            ],
            options={
                'ordering': ['-id'],
            },
        ),
        migrations.CreateModel(
            name='SubscriptionPost',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', models.DateTimeField(auto_now_add=True)),
                ('post', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rc.Post')),
                ('subscription', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rc.Subscription')),
            ],
        ),
        migrations.AddField(
            model_name='post',
            name='source',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rc.Source'),
        ),
        migrations.AddField(
            model_name='enclosure',
            name='post',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='rc.Post'),
        ),
        migrations.AddField(
            model_name='accesslog',
            name='subscription',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='rc.Subscription'),
        ),
    ]
