"""Verify old financial tip IDs cannot be mistaken for website service IDs."""

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class SiteServiceTipMigrationTests(TransactionTestCase):
    def setUp(self):
        self.executor = MigrationExecutor(connection)
        self.latest_targets = self.executor.loader.graph.leaf_nodes()
        self.old_targets = [
            ('face_analyzer', '0002_skincareplan_skincaretip'),
            ('website', '0005_website_usd_price_precision'),
        ]
        self.executor.migrate(self.old_targets)
        old_apps = self.executor.loader.project_state(self.old_targets).apps
        LegacyService = old_apps.get_model('customers', 'Service')
        SiteService = old_apps.get_model('website', 'SiteService')
        FaceAnalysis = old_apps.get_model('face_analyzer', 'FaceAnalysis')
        SkinCarePlan = old_apps.get_model('face_analyzer', 'SkinCarePlan')
        SkinCareTip = old_apps.get_model('face_analyzer', 'SkinCareTip')

        legacy = LegacyService.objects.create(name='Legacy Financial Service', price_usd=100, is_active=True)
        site = SiteService.objects.create(
            id=200, name='Website Skin Cleansing', slug='skin-cleansing', category='skin', price=1500000,
        )
        analysis = FaceAnalysis.objects.create(
            image='face_analyses/migration-test.png',
            overall_score=7, symmetry_score=7, skin_clarity_score=7,
            youthfulness_score=7, harmony_score=7,
            detected_attributes={'concerns': ['enlarged_pores']},
            suggestions=[], raw_model_output={}, provider='local', model_version='test',
        )
        plan = SkinCarePlan.objects.create(
            analysis=analysis, summary='Test', skin_type='normal',
            primary_concerns=['enlarged_pores'], recommended_frequency='Daily',
            provider='rule_based', model_used='test',
        )
        self.matched = SkinCareTip.objects.create(
            analysis=analysis, plan=plan, period='professional', sort_order=1,
            title='Matched', description='Test', priority='medium', category='in_clinic',
            related_service_slug='skin-cleansing', related_service_id=legacy.pk,
        ).pk
        self.unmatched = SkinCareTip.objects.create(
            analysis=analysis, plan=plan, period='professional', sort_order=2,
            title='Unmatched', description='Test', priority='medium', category='in_clinic',
            related_service_slug='unknown-service', related_service_id=legacy.pk,
        ).pk
        self.site_id = site.pk
        self.legacy_id = legacy.pk

    def tearDown(self):
        MigrationExecutor(connection).migrate(self.latest_targets)

    def test_relinks_exact_site_slug_and_clears_other_financial_ids(self):
        migrator = MigrationExecutor(connection)
        new_targets = [
            ('face_analyzer', '0003_site_service_links'),
            ('website', '0005_website_usd_price_precision'),
        ]
        migrator.migrate(new_targets)
        new_apps = migrator.loader.project_state(new_targets).apps
        SkinCareTip = new_apps.get_model('face_analyzer', 'SkinCareTip')
        LegacyService = new_apps.get_model('customers', 'Service')

        self.assertEqual(SkinCareTip.objects.get(pk=self.matched).related_service_id, self.site_id)
        self.assertIsNone(SkinCareTip.objects.get(pk=self.unmatched).related_service_id)
        self.assertTrue(LegacyService.objects.filter(pk=self.legacy_id).exists())
