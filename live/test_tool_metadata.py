from types import SimpleNamespace

from django.test import SimpleTestCase

from live import views


class ToolMetadataTests(SimpleTestCase):
    def test_tool_metadata_preserves_semantic_icon_and_form_hints(self):
        from tools.sdk import Param
        tool = SimpleNamespace(key='buffer', title='حریم', category='proximity',
                               description='حریم مکانی', icon='target',
                               params=(Param('distance', 'number', 'فاصله', unit='متر',
                                             help='فاصله مثبت', group='settings'),))
        result = views.tool_metadata(tool)
        self.assertEqual(result['icon'], 'target')
        self.assertEqual(result['params'][0]['unit'], 'متر')
        self.assertEqual(result['params'][0]['group'], 'settings')
        self.assertEqual(result['params'][0]['help'], 'فاصله مثبت')
