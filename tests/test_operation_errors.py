import unittest
from test_management import Fixture
from mod_assistant.diagnostics import diagnose, redact
from mod_assistant.operation_errors import describe_error

class OperationErrorTests(Fixture):
    def test_error_identifies_task_cause_next_step_version_and_local_evidence(self):
        try: raise PermissionError('file access denied: '+str(self.env.installed/'101/items.xml'))
        except PermissionError as error: report=describe_error(error,self.env,'保存完整快照')
        self.assertEqual(report['operation'],'保存完整快照'); self.assertTrue(report['id']); self.assertTrue(report['version'])
        self.assertIn('PermissionError',report['details']); self.assertIn('关闭游戏',report['next_step'])
        self.assertNotIn(str(self.env.player),report['details']); self.assertIn('[本机目录]',report['details'])

    def test_quoted_credentials_and_multiword_authorization_are_hidden_for_manual_sharing(self):
        text='password="secret words"\nauthorization: Bearer private-token\napi_key: another-secret\nnormal diagnostic message'
        result=redact(text)
        for value in ('secret words','private-token','another-secret'): self.assertNotIn(value,result)
        self.assertIn('normal diagnostic message',result)

    def test_log_retains_source_time_encoding_and_only_claims_exact_full_line_numbers(self):
        path=self.env.game/'fixture.log'; path.write_text('start\nLua error in 101\ntraceback\n',encoding='utf-8')
        report=diagnose(path,[self.make('101')],self.env)
        self.assertEqual(report['path'],str(path)); self.assertTrue(report['modified_utc']); self.assertEqual(report['encoding'],'UTF-8')
        self.assertEqual(report['byte_offset'],0); self.assertEqual(report['findings'][0]['line_in_file'],2)
        path.write_bytes(b'x'*4_200_000+b'\nLua error in 101\n')
        report=diagnose(path,[self.make('101')],self.env)
        self.assertTrue(report['tail_only']); self.assertGreater(report['byte_offset'],0)
        self.assertIsNone(report['findings'][0]['line_in_file'])
