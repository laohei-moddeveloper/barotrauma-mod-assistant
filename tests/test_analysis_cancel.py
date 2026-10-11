import threading
from unittest.mock import patch
from test_management import Fixture
from mod_assistant.core import Cancelled
from mod_assistant.mod_analysis import inspect
from mod_assistant.analysis_cache import inspect_cached,SCHEMA


class AnalysisCancellationTests(Fixture):
    def test_pre_cancelled_scan_does_not_open_the_manifest(self):
        event=threading.Event();event.set();mod=self.make('101')
        with patch('mod_assistant.mod_analysis.load_package',side_effect=AssertionError('A cancelled scan opened a manifest')):
            with self.assertRaises(Cancelled):inspect(mod,cancel=event)

    def test_cancel_inside_xml_parse_is_not_saved_as_a_partial_cache(self):
        mod=self.make('101');path=mod.source/'items.xml'
        path.write_text('<Items>'+''.join('<Item identifier="id'+str(index)+'"/>' for index in range(2000))+'</Items>')
        before=path.read_bytes()
        class Pending:
            calls=0
            def is_set(self):
                self.calls+=1;return self.calls>=6
        pending=Pending()
        with patch('mod_assistant.analysis_cache.signature',return_value='test'):
            with self.assertRaises(Cancelled):inspect_cached(self.env,[mod],cancel=pending)
        self.assertFalse(list((self.env.work/f'analysis/features-v{SCHEMA}').glob('*.json')))
        self.assertEqual(path.read_bytes(),before)

    def test_script_inventory_cancellation_propagates_without_a_result(self):
        mod=self.make('101');event=threading.Event()
        def files(folder):
            event.set();yield folder/'unexecuted.lua'
        with patch('mod_assistant.mod_analysis.mod_files',side_effect=files):
            with self.assertRaises(Cancelled):inspect(mod,cancel=event)
