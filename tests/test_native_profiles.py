import unittest
from test_management import Fixture
from mod_assistant.core import AssistantError, inventory
from mod_assistant.mod_order import read_order
from mod_assistant.native_profiles import read_native, native_bytes, write_native
from mod_assistant.profiles import apply_profile, normalize_profile


class NativeProfileTests(Fixture):
    def test_game_xml_roundtrip_core_order_unicode_and_other_settings(self):
        data=read_native(self.env,b'<mods name="Game list"><Workshop id="103" name="Core"/><Workshop id="102"/><Workshop id="101"/></mods>')
        self.assertEqual(data['core']['id'],'103'); self.assertEqual([x['id'] for x in data['order']],['102','101'])
        data['name']='中文 & English'
        result=read_native(self.env,native_bytes(data)); self.assertEqual(result['name'],data['name'])
        apply_profile(self.env,result,process_guard=self.guard)
        self.assertEqual(read_order(self.env),['102','101']); self.assertIn(b'volume="77"',self.config.read_bytes())

    def test_local_names_ambiguous_or_missing_never_silently_ignored(self):
        folder=self.env.game/'LocalMods/a'; folder.mkdir(parents=True)
        (folder/'filelist.xml').write_text('<contentpackage name="Local Name" />')
        data=read_native(self.env,b'<mods><Vanilla/><Local name="local name" /></mods>')
        apply_profile(self.env,data,process_guard=self.guard)
        second=self.env.player/'LocalMods/b'; second.mkdir(parents=True)
        (second/'filelist.xml').write_text('<contentpackage name="LOCAL NAME" />')
        before=self.config.read_bytes()
        with self.assertRaises(AssistantError): apply_profile(self.env,data,process_guard=self.guard)
        self.assertEqual(before,self.config.read_bytes())
        missing=read_native(self.env,b'<mods><Vanilla/><Workshop id="999"/></mods>')
        self.assertEqual(missing['order'][0]['id'],'999')
        with self.assertRaises(AssistantError): apply_profile(self.env,missing,process_guard=self.guard)
        self.assertEqual(before,self.config.read_bytes())

    def test_missing_core_resolves_after_install_and_old_json_converts(self):
        data=read_native(self.env,b'<mods><Workshop id="999"/><Workshop id="101"/></mods>')
        self.make('999',core=True)
        apply_profile(self.env,data,process_guard=self.guard)
        self.assertEqual(read_order(self.env),['101']); self.assertIn(b'Installed/999',self.config.read_bytes())
        legacy=normalize_profile({'schema':'barotrauma-mod-assistant-profile-v1','appid':602960,'mods':[{'id':'102','name':'Old'}]})
        written=write_native(self.env.game/'ModLists/Converted.xml',legacy)
        self.assertEqual(read_native(self.env,written.read_bytes())['order'][0]['id'],'102')

    def test_invalid_xml_ids_entities_duplicates_and_multiple_cores_rejected(self):
        self.make('104',core=True)
        for value in (b'<config/>',b'<mods><Workshop id="../x"/></mods>',b'<mods><Workshop id="101"/><Workshop id="101"/></mods>',
                      b'<!DOCTYPE mods [<!ENTITY x "expanded">]><mods name="&x;"/>',
                      b'<mods><Workshop id="103"/><Workshop id="104"/></mods>',b'<mods><Local/></mods>'):
            with self.assertRaises(AssistantError): read_native(self.env,value)
        with self.assertRaises(AssistantError): read_native(self.env,b' '*2100000)
