"""Runtime parity against the archived Python generator, not a build tool."""
import base64
import json
from pathlib import Path
import sys
from zipfile import ZipFile
from lxml import etree

ROOT=Path(__file__).resolve().parents[1]
QA=ROOT.parent/'retainer-qa'
sys.path.insert(0,str(ROOT/'original-skill'))
import generate as old

cases=json.loads((QA/'parity-data.json').read_text(encoding='utf-8'))
checks=[]
for case in cases:
    n=case['normalized']; inp=case['input']
    params={**inp,'case_type':n['case_type'],'party_type':n['party_type'],'fee_type':n['fee_type'],
            'fee_info':old.parse_fee(inp['fee_desc'],n['fee_type']),'crime':inp['cause'],
            'client':inp['plaintiff'],'output_base':str(QA/'python-parity')}
    expected=old.generate_documents(params)
    for file in case['files']:
        actual=QA/'js-parity'/n['group']/file['name']
        actual.parent.mkdir(parents=True,exist_ok=True)
        actual.write_bytes(base64.b64decode(file['base64']))
        reference=Path(expected['files'][file['name']])
        assert old.docx_text(actual)==old.docx_text(reference), f"Text mismatch: {actual}"
        with ZipFile(actual) as a, ZipFile(reference) as b:
            actual_files={i.filename for i in a.infolist() if not i.is_dir()}
            reference_files={i.filename for i in b.infolist() if not i.is_dir()}
            assert actual_files==reference_files
            for name in actual_files:
                if name.endswith('.xml'):
                    def sig(data):
                        root=etree.fromstring(data)
                        return [(e.tag,sorted(e.attrib.items())) for e in root.iter() if not e.tag.endswith('}t')]
                    assert sig(a.read(name))==sig(b.read(name)),f"Format structure mismatch: {file['name']} {name}"
                else:
                    assert a.read(name)==b.read(name),f"Asset mismatch: {name}"
        checks.append({'group':n['group'],'name':file['name'],'textEqual':True,'formatStructureEqual':True})
(QA/'parity-results.json').write_text(json.dumps(checks,ensure_ascii=False,indent=2),encoding='utf-8')
print(f'PASS: {len(checks)} documents match Python text and non-text XML structure')
