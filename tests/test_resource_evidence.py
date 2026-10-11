import xml.etree.ElementTree as ET
from test_management import Fixture
from mod_assistant.item_model import build_registry
from mod_assistant.resource_evidence import resolve_resource,item_references


class ResourceEvidenceTests(Fixture):
    def test_unreviewed_content_overlap_is_not_an_item_registration_error(self):
        from mod_assistant.mod_analysis import Features,pair_evidence,pair_detail
        key=('afflictions','affliction','example')
        left=Features('101','A',definitions={key});right=Features('102','B',definitions={key})
        self.assertEqual(pair_evidence(left,right)[0],1)
        result=pair_detail(left,right,['101','102'])
        self.assertFalse(result['expected_xml_winner']);self.assertIn('未建立完整加载模型',result['advice'])
    def roots(self):
        return {item:{'folder':self.make(item).source,'name':'Mod '+item} for item in ('101','102')}

    def test_same_filename_in_different_mod_roots_is_not_a_shared_file(self):
        packages=self.roots()
        for row in packages.values():(row['folder']/'same.png').write_bytes(b'fake texture')
        first=resolve_resource('%ModDir%/same.png',self.env,'101',packages)
        second=resolve_resource('%ModDir%/same.png',self.env,'102',packages)
        self.assertEqual(first['status'],'exists');self.assertEqual(second['status'],'exists')
        self.assertNotEqual(first['provider'],second['provider'])

    def test_named_parent_path_and_missing_texture_have_exact_evidence(self):
        packages=self.roots();(packages['101']['folder']/'parent.png').write_bytes(b'fake')
        found=resolve_resource('%ModDir:Mod 101%/parent.png',self.env,'102',packages)
        self.assertEqual((found['status'],found['provider'],found['file']),('exists','101','parent.png'))
        missing=resolve_resource('%ModDir%/missing.png',self.env,'102',packages)
        self.assertEqual(missing['status'],'missing');self.assertEqual(missing['provider'],'102')

    def test_ambiguous_names_and_escaping_paths_are_not_guessed(self):
        packages=self.roots();packages['102']['name']='Mod 101'
        self.assertEqual(resolve_resource('%ModDir:Mod 101%/a.png',self.env,'102',packages)['status'],'ambiguous')
        self.assertEqual(resolve_resource('%ModDir%/../secret.png',self.env,'102',packages)['status'],'outside_scope')
        self.assertEqual(resolve_resource('%ModDir%file.png',self.env,'102',packages)['status'],'unresolved')

    def test_absolute_game_resource_is_allowed_but_other_roots_are_excluded(self):
        path=self.env.game/'texture.png';path.write_bytes(b'fake')
        self.assertEqual(resolve_resource(str(path),self.env,'101',self.roots())['status'],'exists')
        outside=self.env.game.parent/'outside.png';outside.write_bytes(b'not a game asset')
        self.assertEqual(resolve_resource(str(outside),self.env,'101',self.roots())['status'],'outside_scope')

    def test_recipe_reference_reports_missing_or_clear_masked_definition(self):
        packages=[{'id':'vanilla','name':'Vanilla','index':-1,'files':[('base.xml',ET.fromstring('<Item identifier="iron"/>'))]},
                  {'id':'clear','name':'Clear','index':0,'files':[('clear.xml',ET.fromstring('<Clear/>'))]}]
        registry=build_registry(packages)
        item=ET.fromstring('<Item identifier="a"><Fabricate><RequiredItem identifier="iron"/><RequiredItem identifier="missing"/></Fabricate></Item>')
        result=item_references(item,self.env,'101',self.roots(),registry)
        self.assertEqual([row['status'] for row in result],['target_unavailable','not_found_in_model'])
        self.assertEqual(result[0]['target_status'],'cleared')
