from test_management import Fixture
from mod_assistant.luacs import status,MODERN_SETTINGS


class StatusEvidenceTests(Fixture):
    def test_prompt_and_unreadable_settings_are_not_reported_as_disabled(self):
        (self.env.game/'Barotrauma.dll').write_bytes(b'LuaCs CsRunPolicy')
        for name in ('BarotraumaCore.dll','MoonSharp.Interpreter.dll'): (self.env.game/name).write_bytes(b'fixture')
        path=self.env.game/MODERN_SETTINGS; path.parent.mkdir(parents=True)
        for policy,permission in [('Enabled',True),('Disabled',False),('Prompt',None)]:
            path.write_text(f'<Configuration><LuaCsForBarotrauma><CsRunPolicy Value="{policy}"/></LuaCsForBarotrauma></Configuration>')
            observed=status(self.env); self.assertEqual(observed.policy,policy); self.assertIs(observed.permanent_permission,permission)
            self.assertNotIn('已安装',observed.text)
        path.write_text('<broken>'); observed=status(self.env)
        self.assertEqual(observed.policy,'Unknown'); self.assertIsNone(observed.permanent_permission)
