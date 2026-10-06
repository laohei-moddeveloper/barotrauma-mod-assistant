import gzip
import struct
import threading
from unittest.mock import patch
from test_management import Fixture
from mod_assistant.core import AssistantError,Cancelled
from mod_assistant.save_inspector import read_save,candidates,build_profile,profile_matches,SaveInfo,save_native_preset,association_for


def archive(entries):
    payload=b''
    for name,value in entries:
        encoded=name.encode('utf-16-le'); payload+=struct.pack('<i',len(encoded)//2)+encoded+struct.pack('<i',len(value))+value
    return gzip.compress(payload)


class SaveInspectorTests(Fixture):
    def save(self,xml,entries=None):
        path=self.env.player/'战役.save'; path.parent.mkdir(exist_ok=True)
        path.write_bytes(archive(entries or [('gamesession.xml',xml)])); return path

    def test_real_entry_is_used_instead_of_first_xml_and_no_files_are_extracted(self):
        xml=b'<GameSession version="1.13.4.0" selectedcontentpackagenames="Vanilla|Mod 102|Mod 101" />'
        path=self.save(xml,[('decoy.sub',b'<?xml version="1.0"?><unrelated />'),('gamesession.xml',xml)])
        before=path.read_bytes(); info=read_save(path)
        self.assertEqual(info.names,['Vanilla','Mod 102','Mod 101']); self.assertEqual(len(info.digest),64)
        self.assertFalse((self.env.player/'gamesession.xml').exists()); self.assertEqual(path.read_bytes(),before)

    def test_escaped_name_unicode_and_missing_record(self):
        path=self.save('<GameSession selectedcontentpackagenames="Vanilla|汉化\\|修订|船🚢" />'.encode())
        self.assertEqual(read_save(path).names,['Vanilla','汉化|修订','船🚢'])
        with self.assertRaisesRegex(AssistantError,'旧存档'): read_save(self.save(b'<GameSession />'))

    def test_crc_truncation_duplicate_session_and_path_traversal_rejected(self):
        xml=b'<GameSession selectedcontentpackagenames="Vanilla" />'
        for entries in ([('gamesession.xml',xml),('GAMESESSION.XML',xml)],[('../gamesession.xml',xml)]):
            with self.assertRaises(AssistantError): read_save(self.save(xml,entries))
        path=self.save(xml); path.write_bytes(path.read_bytes()[:-5])
        with self.assertRaises(AssistantError): read_save(path)

    def test_archive_budget_and_entities_are_rejected(self):
        path=self.save(b'<GameSession selectedcontentpackagenames="Vanilla" />',[('large.sub',b'x'*1000),('gamesession.xml',b'<GameSession />')])
        with patch('mod_assistant.save_inspector.MAX_EXPANDED',300):
            with self.assertRaises(AssistantError): read_save(path)
        path=self.save(b'<!DOCTYPE GameSession [<!ENTITY x "Vanilla">]><GameSession selectedcontentpackagenames="&x;"/>')
        with self.assertRaisesRegex(AssistantError,'实体'): read_save(path)
        cancel=threading.Event(); cancel.set()
        with self.assertRaises(Cancelled): read_save(path,cancel)

    def test_same_name_requires_explicit_choice_and_preserves_extra(self):
        mods=[self.make('101',name='Same'),self.make('102',name='Same'),self.make('104',name='Extra')]
        self.configure(['104','101'])
        info=SaveInfo('campaign.save','a'*64,'1.13.4.0','',['Vanilla','Same'],[])
        available,rows=candidates(self.env,info,mods); before=self.config.read_bytes()
        with self.assertRaisesRegex(AssistantError,'同名'): build_profile(self.env,info,available,rows,mods=mods)
        draft,extra=build_profile(self.env,info,available,rows,{1:'102'},mods=mods)
        self.assertEqual([entry['id'] for entry in draft['order']],['102','104','101'])
        self.assertFalse(draft['save_reference']['historical_files_verified']); self.assertEqual(before,self.config.read_bytes())

    def test_matching_considers_order_and_missing_items(self):
        info=SaveInfo('campaign.save','a'*64,'','',['Vanilla','Mod 102','Mod 101'],[])
        result=profile_matches(info,[self.profile(['101','102']),self.profile(['102','101']),self.profile(['101'])])
        self.assertFalse(result[0]['order_matches']); self.assertTrue(result[1]['order_matches']); self.assertEqual(result[2]['missing'],['Mod 102'])

    def test_duplicate_record_cannot_generate_a_preset(self):
        info=SaveInfo('campaign.save','a'*64,'','',['Vanilla','Mod 101','Mod 101'],[])
        mods=[self.make('101')]; available,rows=candidates(self.env,info,mods)
        with self.assertRaisesRegex(AssistantError,'重复'): build_profile(self.env,info,available,rows,mods=mods)

    def test_saved_result_is_native_xml_with_separate_provenance_and_no_config_change(self):
        from mod_assistant.native_profiles import read_native
        info=SaveInfo('campaign.save','a'*64,'1.13.4.0','',['Vanilla','Mod 102','Mod 101'],[])
        mods=[self.make('101'),self.make('102')]; available,rows=candidates(self.env,info,mods)
        draft,_=build_profile(self.env,info,available,rows,mods=mods); before=self.config.read_bytes()
        path=save_native_preset(self.env,draft)
        self.assertEqual(path.parent,self.env.game/'ModLists')
        self.assertEqual([entry['id'] for entry in read_native(self.env,path.read_bytes(),mods)['order']],['102','101'])
        self.assertEqual(association_for(self.env,path.read_bytes())['sha256'],'a'*64)
        self.assertIsNone(association_for(self.env,path.read_bytes()+b' '))
        self.assertEqual(before,self.config.read_bytes())
