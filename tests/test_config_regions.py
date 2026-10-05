import unittest
import xml.etree.ElementTree as ET

from test_management import Fixture
from mod_assistant.core import AssistantError
from mod_assistant.game_config import package_regions
from mod_assistant.mod_toggle import set_enabled
from mod_assistant.profiles import capture_profile, config_bytes


class FreshConfigTests(Fixture):
    def test_enable_and_profile_apply_empty_game_generated_lists(self):
        for empty in ('<regularpackages />', '<regularpackages></regularpackages>'):
            with self.subTest(empty=empty):
                self.configure([])
                original = self.config.read_text().replace('<regularpackages></regularpackages>', empty)
                original = original.replace('<corepackage path="Content/ContentPackages/Vanilla.xml" />',
                    '<corepackage path="Content/ContentPackages/Vanilla.xml"></corepackage>')
                self.config.write_text(original, encoding='utf-8')
                empty_profile = capture_profile(self.env)
                self.assertEqual(ET.fromstring(config_bytes(self.env, empty_profile)).find('.//regularpackages')[:], [])
                result = set_enabled(self.env, '101', True, process_guard=self.guard)
                self.assertTrue(result.changed)
                self.assertIn('Installed/101/filelist.xml', self.config.read_text())
                self.assertIn('<audio volume="77" />', self.config.read_text())

    def test_comments_quoted_angle_brackets_unicode_and_bom_are_preserved(self):
        self.configure([])
        text = self.config.read_text().replace('<config keep="yes">',
            '<config keep="中文 &gt; English"><!-- <regularpackages /> -->')
        text = text.replace('<regularpackages></regularpackages>', '<regularpackages label="a > b" />')
        self.config.write_bytes(b'\xef\xbb\xbf' + text.encode('utf-8'))
        set_enabled(self.env, '101', True, process_guard=self.guard)
        updated = self.config.read_bytes()
        self.assertTrue(updated.startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'<!-- <regularpackages /> -->', updated)
        self.assertIn('中文 &gt; English'.encode('utf-8'), updated)
        self.assertEqual(len(ET.fromstring(updated).find('.//regularpackages')), 1)

    def test_ambiguous_duplicate_regions_rejected_without_writing(self):
        self.configure([])
        value = self.config.read_bytes().replace(b'</contentpackages>', b'<regularpackages /></contentpackages>')
        self.config.write_bytes(value)
        with self.assertRaisesRegex(AssistantError, '重复'):
            set_enabled(self.env, '101', True, process_guard=self.guard)
        self.assertEqual(self.config.read_bytes(), value)

    def test_doctype_and_unrelated_regions_are_not_edited(self):
        self.assertEqual(package_regions('<config><other><regularpackages /></other></config>'), (None, None))
        self.assertEqual(package_regions('<config><other><contentpackages><regularpackages /></contentpackages></other></config>'), (None, None))
        with self.assertRaises(AssistantError):
            package_regions('<!DOCTYPE config [<!ENTITY value "example">]><config>&value;</config>')


if __name__ == '__main__':
    unittest.main()
