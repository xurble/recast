# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models 


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding field 'Subscription.complete'
        db.add_column('rc_subscription', 'complete',
                      self.gf('django.db.models.fields.BooleanField')(default=False),
                      keep_default=False)

        # Adding field 'Subscription.created'
        db.add_column('rc_subscription', 'created',
                      self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, null=True, blank=True),
                      keep_default=False)

        # Adding field 'Subscription.last_accessed'
        db.add_column('rc_subscription', 'last_accessed',
                      self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, null=True, blank=True),
                      keep_default=False)


    def backwards(self, orm):
        # Deleting field 'Subscription.complete'
        db.delete_column('rc_subscription', 'complete')

        # Deleting field 'Subscription.created'
        db.delete_column('rc_subscription', 'created')

        # Deleting field 'Subscription.last_accessed'
        db.delete_column('rc_subscription', 'last_accessed')


    models = {
        'rc.accesslog': {
            'Meta': {'ordering': "['-id']", 'object_name': 'AccessLog'},
            'access_time': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'ip_address': ('django.db.models.fields.CharField', [], {'max_length': '16'}),
            'raw_id': ('django.db.models.fields.CharField', [], {'max_length': '128'}),
            'return_code': ('django.db.models.fields.IntegerField', [], {}),
            'subscription': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Subscription']", 'null': 'True', 'blank': 'True'}),
            'user_agent': ('django.db.models.fields.CharField', [], {'max_length': '512'})
        },
        'rc.enclosure': {
            'Meta': {'object_name': 'Enclosure'},
            'href': ('django.db.models.fields.CharField', [], {'max_length': '512'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'length': ('django.db.models.fields.IntegerField', [], {}),
            'post': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Post']"}),
            'type': ('django.db.models.fields.CharField', [], {'max_length': '256'})
        },
        'rc.post': {
            'Meta': {'ordering': "['index']", 'object_name': 'Post'},
            'author': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'body': ('django.db.models.fields.TextField', [], {}),
            'created': ('django.db.models.fields.DateTimeField', [], {'db_index': 'True'}),
            'found': ('django.db.models.fields.DateTimeField', [], {}),
            'guid': ('django.db.models.fields.CharField', [], {'db_index': 'True', 'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'image_url': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'index': ('django.db.models.fields.IntegerField', [], {'db_index': 'True'}),
            'link': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'source': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Source']"}),
            'title': ('django.db.models.fields.TextField', [], {})
        },
        'rc.source': {
            'Meta': {'object_name': 'Source'},
            'due_poll': ('django.db.models.fields.DateTimeField', [], {}),
            'etag': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'feed_url': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'image_url': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'interval': ('django.db.models.fields.PositiveIntegerField', [], {'default': '400'}),
            'last_302_start': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'last_302_url': ('django.db.models.fields.CharField', [], {'default': "' '", 'max_length': '255'}),
            'last_change': ('django.db.models.fields.DateTimeField', [], {'null': 'True'}),
            'last_modified': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'last_polled': ('django.db.models.fields.DateTimeField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'last_result': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'last_success': ('django.db.models.fields.DateTimeField', [], {'null': 'True'}),
            'live': ('django.db.models.fields.BooleanField', [], {'default': 'True'}),
            'max_index': ('django.db.models.fields.IntegerField', [], {'default': '0'}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'num_subs': ('django.db.models.fields.IntegerField', [], {'default': '1'}),
            'site_url': ('django.db.models.fields.CharField', [], {'max_length': '255', 'null': 'True', 'blank': 'True'}),
            'status_code': ('django.db.models.fields.PositiveIntegerField', [], {'default': '0'})
        },
        'rc.subscription': {
            'Meta': {'ordering': "['-id']", 'object_name': 'Subscription'},
            'complete': ('django.db.models.fields.BooleanField', [], {'default': 'False'}),
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'null': 'True', 'blank': 'True'}),
            'frequency': ('django.db.models.fields.IntegerField', [], {'default': '5'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'key': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '64'}),
            'last_accessed': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'null': 'True', 'blank': 'True'}),
            'last_sent': ('django.db.models.fields.IntegerField', [], {'default': '1'}),
            'last_sent_date': ('django.db.models.fields.DateTimeField', [], {}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'source': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Source']"})
        },
        'rc.subscriptionpost': {
            'Meta': {'object_name': 'SubscriptionPost'},
            'created': ('django.db.models.fields.DateTimeField', [], {'auto_now_add': 'True', 'blank': 'True'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'post': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Post']"}),
            'subscription': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Subscription']"})
        }
    }

    complete_apps = ['rc']