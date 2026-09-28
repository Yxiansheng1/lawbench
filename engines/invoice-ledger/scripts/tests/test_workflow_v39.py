"""Portable rules and MIME enumeration tests; synthetic data only, no mailbox connection."""
import sys,unittest,tempfile,json,zipfile
from pathlib import Path
from email.message import EmailMessage
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from buyer_verification import parse_buyer,buyer_errors,configured_buyer,annotate,UNSET_BUYER
from collection_job import load,save,expand,reconcile
from mail_collect import collect_eml,store,digest
from extract_fields import normalize_ocr_text,parse_text_fields
from invoice_integrity import total_amount
LAW='示例科技有限公司'   # 测试用合成购买方；不依赖本机 buyer.json，保证跨机可复现
class WorkflowTests(unittest.TestCase):
    def test_buyer_exact(self):self.assertEqual(parse_buyer('购买方名称：'+LAW,LAW)['抬头核验'],'通过')
    def test_buyer_normalization(self):self.assertEqual(parse_buyer('购买方名称：示例科技(深圳) 有限公司','示例科技（深圳）有限公司')['抬头核验'],'通过')
    def test_seller_not_buyer(self):self.assertEqual(parse_buyer('销售方名称：'+LAW,LAW)['抬头核验'],'待核')
    def test_note_not_buyer(self):self.assertEqual(parse_buyer('备注：购买方名称：'+LAW,LAW)['抬头核验'],'待核')
    def test_person_rejected(self):self.assertEqual(parse_buyer('购买方名称：张三',LAW)['抬头核验'],'错误')
    def test_other_entity_rejected(self):self.assertEqual(parse_buyer('购买方名称：示例有限公司',LAW)['抬头核验'],'错误')
    def test_multiple_buyers_pending(self):self.assertEqual(parse_buyer('购买方名称：张三\n购买方名称：'+LAW,LAW)['抬头核验'],'待核')
    def test_unset_buyer_is_pending_and_explains(self):
        """未配置购买方时必须待核并给出配置指引，不得猜测放行。"""
        r=parse_buyer('购买方名称：'+LAW,'')
        self.assertEqual(r['抬头核验'],'待核');self.assertEqual(r['抬头原因'],UNSET_BUYER)
        self.assertIn(UNSET_BUYER,buyer_errors(annotate('购买方名称：'+LAW,{},''),''))
    def test_buyer_resolution_env_beats_file(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ,{'INVOICE_BUYER':'甲有限公司'},clear=False):
            self.assertEqual(configured_buyer(),'甲有限公司')
        with patch.dict(os.environ,{'INVOICE_BUYER':''},clear=False):
            self.assertNotEqual(configured_buyer(),'甲有限公司')  # 空值不生效，回落配置文件
    def test_ocr_money_spacing(self):self.assertEqual(total_amount(normalize_ocr_text('价税合计 （ 小写 ） ¥ 50 ， 00'))[0],'50.00')
    def test_legacy_code_required(self):self.assertIn('_identity_error',parse_text_fields('发票号码：123456789012345678','x.pdf'))
    def test_mime_and_link_accounting(self):
        with tempfile.TemporaryDirectory() as td:
            job=Path(td);state=load(job);m=EmailMessage();m['Subject']='发票';m.set_content('下载发票：https://example.invalid/file.pdf')
            m.add_attachment(b'%PDF-test',maintype='application',subtype='pdf',filename='a.pdf')
            collect_eml(job,'synthetic',m.as_bytes(),state);collect_eml(job,'synthetic',m.as_bytes(),state)
            self.assertEqual(len(state['items']),2);reconcile(job,state)
            self.assertFalse(state['reconciliation']['processing_complete']);self.assertFalse(state['reconciliation']['mailbox_scope_complete'])
    def test_zip_only_pdf(self):
        with tempfile.TemporaryDirectory() as td:
            job=Path(td);state=load(job);zpath=job/'test.zip'
            with zipfile.ZipFile(zpath,'w') as z:z.writestr('../a.pdf',b'%PDF-test');z.writestr('a.xml','test')
            raw=zpath.read_bytes();state['items']['zip']={'id':'zip','kind':'local','name':'test.zip','status':'已下载','path':store(job,raw,'.zip'),'sha256':digest(raw)}
            expand(job,state)
            self.assertEqual(sum(i['status']=='未选取' for i in state['items'].values()),1)
            self.assertFalse((job.parent/'a.pdf').exists());self.assertFalse(list((job/'原始资料').glob('*.xml')))
    def test_link_item_detection(self):
        import workflow
        self.assertFalse(workflow._has_link_items({'items':{'a':{'kind':'local'}}}))
        self.assertFalse(workflow._has_link_items({'items':{}}))
        self.assertTrue(workflow._has_link_items({'items':{'a':{'kind':'local'},'b':{'kind':'link'}}}))
    def test_mcp_channel_declares_body_link_gap(self):
        """MCP已下载文件渠道不解析邮件正文：必须显式声明"仅正文链接"类发票未覆盖，不得静默留白。"""
        import workflow
        from period_plan import make_plan
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);job=root/'job';src=root/'src';src.mkdir(parents=True)
            (src/'a.pdf').write_bytes(b'%PDF-1.4 synthetic')
            st=load(job);st['reimbursement_plan']=make_plan('2026-09','mcp','2026-08-19','2026-09-19','exclude');save(job,st)
            old=sys.argv
            try:
                sys.argv=['workflow.py','collect','--job',str(job),'--batch','第一批','--src',str(src),'--download-links']
                rc=workflow.main()
            finally:
                sys.argv=old
            self.assertIn(rc,(0,2))
            state=load(job);cov=state['coverage']
            self.assertEqual(cov['adapter'],'mcp-export')
            self.assertEqual(cov['body_link_coverage'],'not_covered')
            self.assertIn('仅正文链接',cov['limitation'])
            self.assertFalse(workflow._has_link_items(state))
if __name__=='__main__':unittest.main()
