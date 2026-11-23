import json
from unittest import mock

from django.test import RequestFactory
from django.urls import reverse

from databases import services
from databases.tests.test_services import BaseCase
from live import workflows
from maps.models import MapLayer, WebMap


class WorkflowTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.db = services.create_database(self.user, 'workflow', 'Abcdefgh123', [])
        self.factory = RequestFactory()

    def request(self, method='get', data=None):
        r = getattr(self.factory, method)('/', data or {})
        r.user = self.user
        return r

    def test_projects_list_and_create_use_existing_maps(self):
        response = workflows.projects(self.request('post', {'title':'پروژه'}), self.db.pk)
        self.assertEqual(response.status_code, 201)
        payload = json.loads(response.content)
        self.assertEqual(WebMap.objects.get(pk=payload['project']['id']).title, 'پروژه')
        response = workflows.projects(self.request(), self.db.pk)
        self.assertEqual(len(json.loads(response.content)['projects']), 1)

    def test_source_is_scoped_to_project_workspace(self):
        project = WebMap.objects.create(database=self.db, title='map')
        layer = MapLayer.objects.create(webmap=project, table='roads', geom_column='geom', geom_type='LINESTRING')
        with mock.patch('live.workflows.tenantdb.catalog') as catalog:
            catalog.return_value.find.return_value = object()
            catalog.return_value.columns.return_value = [{'name':'name', 'type':'text'}]
            response = workflows.source(self.request(), self.db.pk, project.pk, layer.pk)
        payload = json.loads(response.content)
        self.assertEqual(payload['source']['srid'], 4326)
        self.assertEqual(payload['source']['table'], 'roads')
        self.assertEqual(payload['source']['fields'][0]['name'], 'name')

    def test_history_empty_is_valid(self):
        response = workflows.history(self.request(), self.db.pk)
        self.assertEqual(json.loads(response.content)['jobs'], [])

    def test_other_account_cannot_read_any_workflow(self):
        from django.http import Http404

        from accounts.models import User
        project = WebMap.objects.create(database=self.db, title='private')
        layer = MapLayer.objects.create(webmap=project, table='roads', geom_column='geom')
        request = self.request()
        request.user = User.objects.create_user('09120000002')
        for view, args in ((workflows.projects, [self.db.pk]),
                           (workflows.history, [self.db.pk]),
                           (workflows.source, [self.db.pk, project.pk, layer.pk])):
            with self.assertRaises(Http404):
                view(request, *args)

    def test_layer_from_another_project_is_not_exposed(self):
        from django.http import Http404
        first = WebMap.objects.create(database=self.db, title='first')
        second = WebMap.objects.create(database=self.db, title='second')
        layer = MapLayer.objects.create(webmap=second, table='private', geom_column='geom')
        with self.assertRaises(Http404):
            workflows.source(self.request(), self.db.pk, first.pk, layer.pk)

    def test_publish_reuses_existing_service(self):
        with mock.patch('live.workflows.tenantdb.catalog') as catalog, \
                mock.patch('publish.views._publish_one', return_value=('ok', 'منتشر شد')) as publish:
            catalog.return_value.find.return_value = object()
            response = workflows.publish_layer(self.request('post', {'schema':'public', 'table':'roads'}), self.db.pk)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(publish.call_args.args[3], False)

    def test_import_adapter_returns_form_fragment_inside_live(self):
        with mock.patch('dbimport.views.workspace.open_catalog', return_value=(self.db, mock.Mock())):
            request = self.request()
            response = workflows.import_flow(request, self.db.pk)
        payload = json.loads(response.content)
        self.assertIn('name="file"', payload['html'])
        self.assertNotIn('<!doctype', payload['html'])

    def test_geoai_submits_through_existing_service(self):
        self.client.force_login(self.user)
        with mock.patch('analysis.ask.request') as ask:
            response = self.client.post(reverse('live:workflow_ai', args=[self.db.pk]),
                                        {'question': 'مساحت محله‌ها', 'output': 'areas'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['jobsChanged'])
        self.assertEqual(ask.call_args.args[2], 'مساحت محله‌ها')

    def test_rest_workflow_renders_scoped_form(self):
        self.client.force_login(self.user)
        with mock.patch('restapi.manage.tenantdb.catalog') as catalog:
            catalog.return_value.tables.return_value = []
            catalog.return_value.single_pk_tables.return_value = set()
            response = self.client.get(reverse('live:workflow_rest', args=[self.db.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('REST', response.json()['html'])

    def test_ows_workflow_rejects_missing_upload(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse('live:workflow_ows', args=[self.db.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertIn('QGIS', response.json()['error']['message'])

    def test_survey_workflow_lists_projects(self):
        from core.models import SiteSettings

        settings = SiteSettings.get()
        settings.survey_enabled = True
        settings.save(update_fields=["survey_enabled"])
        self.client.force_login(self.user)
        with mock.patch('survey.services.active_projects', return_value=[]):
            response = self.client.get(reverse('live:workflow_survey', args=[self.db.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('برداشت', response.json()['html'])

    def test_satellite_search_reuses_service(self):
        self.client.force_login(self.user)
        with mock.patch('satellite.services.search', return_value=[{'id': 'example'}]) as search:
            response = self.client.post(reverse('live:workflow_satellite', args=[self.db.pk]), {
                'west': 51, 'south': 35, 'east': 52, 'north': 36,
                'start': '2026-11-01', 'end': '2026-11-02',
            })
        self.assertEqual(response.status_code, 200)
        self.assertIn('example', response.json()['html'])
        self.assertEqual(search.call_args.args[2]['bbox'], [51, 35, 52, 36])

    def test_live_table_exposes_edit_controls_to_editor(self):
        self.client.force_login(self.user)
        table = mock.Mock(schema='public', name='roads')
        table.name = 'roads'
        with mock.patch('live.views.tenantdb.catalog') as catalog, \
                mock.patch('dbtables.views._edit_config', return_value={'capable': True}):
            catalog.return_value.tables.return_value = [table]
            catalog.return_value.rows.return_value = {'rows': []}
            response = self.client.get(reverse('live:table', args=[self.db.pk]),
                                       {'schema': 'public', 'table': 'roads'})
        self.assertEqual(response.json()['edit'], {'capable': True})
        self.assertTrue(catalog.return_value.rows.call_args.kwargs['with_keys'])

    def test_market_lists_workspace_plugin_access(self):
        self.client.force_login(self.user)
        with mock.patch('billing.services.market_catalog', return_value={
            'items': [{'id': 'maps', 'name': 'نقشه'}],
        }):
            response = self.client.get(reverse('live:workflow_plugins', args=[self.db.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertIn('نقشه', response.json()['html'])
        self.assertIn('در دسترس', response.json()['html'])

    def test_market_trial_reuses_billing_service(self):
        self.client.force_login(self.user)
        addon = mock.Mock(pk=12)
        with mock.patch('billing.services.market_catalog', return_value={
            'items': [{'id': 'maps', 'name': 'نقشه', 'addon': addon}],
        }), mock.patch('billing.services.start_trial') as start:
            response = self.client.post(reverse('live:workflow_plugins', args=[self.db.pk]),
                                        {'action': 'trial', 'addon': '12'})
        self.assertEqual(response.status_code, 200)
        start.assert_called_once_with(self.user, addon, self.db)

    def test_survey_surface_rejects_project_outside_workspace(self):
        from core.models import SiteSettings

        settings = SiteSettings.get()
        settings.survey_enabled = True
        settings.save(update_fields=["survey_enabled"])
        self.client.force_login(self.user)
        url = reverse('live:workflow_survey_surface', args=[self.db.pk, 999])
        self.assertEqual(self.client.post(url).status_code, 404)

    def test_survey_surface_renders_results_and_saves_contours(self):
        from core.models import SiteSettings
        from survey.models import SurveyProject

        settings = SiteSettings.get()
        settings.survey_enabled = True
        settings.save(update_fields=["survey_enabled"])
        self.client.force_login(self.user)
        project = SurveyProject.objects.create(database=self.db, name="برداشت آزمایشی", srid=32639)
        url = reverse('live:workflow_survey_surface', args=[self.db.pk, project.pk])
        with mock.patch('survey.views._surface', return_value=([], [], {'points': 14, 'interval': 2})), \
                mock.patch('survey.data.save_contours') as save:
            result = self.client.post(url, {'interval': '2', 'save': 'on'})
        self.assertEqual(result.status_code, 200)
        self.assertIn('ذخیره شدند', result.json()['html'])
        save.assert_called_once_with(self.db, project, [])
