# -*- coding: utf-8 -*-
from south.utils import datetime_utils as datetime
from south.db import db
from south.v2 import SchemaMigration
from django.db import models


class Migration(SchemaMigration):

    def forwards(self, orm):
        # Adding model 'Source'
        db.create_table('rc_source', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('site_url', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('feed_url', self.gf('django.db.models.fields.CharField')(max_length=255)),
            ('image_url', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('last_polled', self.gf('django.db.models.fields.DateTimeField')(max_length=255, null=True, blank=True)),
            ('due_poll', self.gf('django.db.models.fields.DateTimeField')()),
            ('etag', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('last_modified', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('last_result', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('interval', self.gf('django.db.models.fields.PositiveIntegerField')(default=400)),
            ('last_success', self.gf('django.db.models.fields.DateTimeField')(null=True)),
            ('last_change', self.gf('django.db.models.fields.DateTimeField')(null=True)),
            ('live', self.gf('django.db.models.fields.BooleanField')(default=True)),
            ('status_code', self.gf('django.db.models.fields.PositiveIntegerField')(default=0)),
            ('last_302_url', self.gf('django.db.models.fields.CharField')(default=' ', max_length=255)),
            ('last_302_start', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('max_index', self.gf('django.db.models.fields.IntegerField')(default=0)),
            ('num_subs', self.gf('django.db.models.fields.IntegerField')(default=1)),
        ))
        db.send_create_signal('rc', ['Source'])

        # Adding model 'Subscription'
        db.create_table('rc_subscription', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('key', self.gf('django.db.models.fields.CharField')(unique=True, max_length=64)),
            ('source', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['rc.Source'])),
            ('last_sent', self.gf('django.db.models.fields.IntegerField')(default=1)),
            ('last_sent_date', self.gf('django.db.models.fields.DateTimeField')()),
            ('frequency', self.gf('django.db.models.fields.IntegerField')(default=5)),
            ('name', self.gf('django.db.models.fields.CharField')(max_length=255)),
        ))
        db.send_create_signal('rc', ['Subscription'])

        # Adding model 'Post'
        db.create_table('rc_post', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('source', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['rc.Source'])),
            ('title', self.gf('django.db.models.fields.TextField')()),
            ('body', self.gf('django.db.models.fields.TextField')()),
            ('link', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('found', self.gf('django.db.models.fields.DateTimeField')()),
            ('created', self.gf('django.db.models.fields.DateTimeField')(db_index=True)),
            ('guid', self.gf('django.db.models.fields.CharField')(db_index=True, max_length=255, null=True, blank=True)),
            ('author', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
            ('index', self.gf('django.db.models.fields.IntegerField')(db_index=True)),
            ('image_url', self.gf('django.db.models.fields.CharField')(max_length=255, null=True, blank=True)),
        ))
        db.send_create_signal('rc', ['Post'])

        # Adding model 'Enclosure'
        db.create_table('rc_enclosure', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('post', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['rc.Post'])),
            ('length', self.gf('django.db.models.fields.IntegerField')()),
            ('href', self.gf('django.db.models.fields.CharField')(max_length=512)),
            ('type', self.gf('django.db.models.fields.CharField')(max_length=256)),
        ))
        db.send_create_signal('rc', ['Enclosure'])

        # Adding model 'AccessLog'
        db.create_table('rc_accesslog', (
            ('id', self.gf('django.db.models.fields.AutoField')(primary_key=True)),
            ('subscription', self.gf('django.db.models.fields.related.ForeignKey')(to=orm['rc.Subscription'], null=True, blank=True)),
            ('raw_id', self.gf('django.db.models.fields.CharField')(max_length=128)),
            ('access_time', self.gf('django.db.models.fields.DateTimeField')(auto_now_add=True, blank=True)),
            ('ip_address', self.gf('django.db.models.fields.CharField')(max_length=16)),
            ('user_agent', self.gf('django.db.models.fields.CharField')(max_length=512)),
            ('return_code', self.gf('django.db.models.fields.IntegerField')()),
        ))
        db.send_create_signal('rc', ['AccessLog'])


    def backwards(self, orm):
        # Deleting model 'Source'
        db.delete_table('rc_source')

        # Deleting model 'Subscription'
        db.delete_table('rc_subscription')

        # Deleting model 'Post'
        db.delete_table('rc_post')

        # Deleting model 'Enclosure'
        db.delete_table('rc_enclosure')

        # Deleting model 'AccessLog'
        db.delete_table('rc_accesslog')


    models = {
        'rc.accesslog': {
            'Meta': {'object_name': 'AccessLog'},
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
            'Meta': {'object_name': 'Post'},
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
            'Meta': {'object_name': 'Subscription'},
            'frequency': ('django.db.models.fields.IntegerField', [], {'default': '5'}),
            'id': ('django.db.models.fields.AutoField', [], {'primary_key': 'True'}),
            'key': ('django.db.models.fields.CharField', [], {'unique': 'True', 'max_length': '64'}),
            'last_sent': ('django.db.models.fields.IntegerField', [], {'default': '1'}),
            'last_sent_date': ('django.db.models.fields.DateTimeField', [], {}),
            'name': ('django.db.models.fields.CharField', [], {'max_length': '255'}),
            'source': ('django.db.models.fields.related.ForeignKey', [], {'to': "orm['rc.Source']"})
        }
    }

    complete_apps = ['rc']