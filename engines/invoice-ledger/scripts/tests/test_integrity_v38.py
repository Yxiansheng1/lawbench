"""Portable synthetic regression. Run through invoke.py; no historical user data needed."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from invoice_integrity import total_amount,admission_errors,ledger_gate
from extract_fields import parse_text_fields
class IntegrityTests(unittest.TestCase):
    def test_explicit_total(self):self.assertEqual(total_amount('价税合计（小写）￥100.00\n备注￥9999.00')[0],'100.00')
    def test_negative(self):self.assertEqual(total_amount('价税合计（小写）￥-50.00')[0],'-50.00')
    def test_ambiguous(self):self.assertEqual(total_amount('价税合计：￥100.00\n价税合计：￥101.00')[0],'')
    def test_unlabelled(self):self.assertEqual(total_amount('历史记录￥100.00')[0],'')
    def test_legacy(self):self.assertEqual(parse_text_fields('发票代码：1234567890 发票号码：12345678','a.pdf')['发票号码全号'],'123456789012345678')
    def test_short_identity(self):self.assertTrue(admission_errors({'发票号码全号':'12345678','开票日期':'2026-01-01','价税合计（元）':'10.00','发票类别':'办公费'}))
    def test_impossible_date(self):self.assertTrue(admission_errors({'发票号码全号':'1'*20,'开票日期':'2026-02-30','价税合计（元）':'10.00','发票类别':'办公费'}))
    def test_nonfinite(self):self.assertTrue(admission_errors({'发票号码全号':'1'*20,'开票日期':'2026-01-01','价税合计（元）':'NaN','发票类别':'办公费'}))
    def test_duplicate_gate(self):
        headers={'发票号码全号':0,'开票日期':1,'价税合计（元）':2,'发票类别':3,'状态':4};r=['1'*20,'2026-01-01','10.00','办公费','未报']
        self.assertTrue(ledger_gate([r,r],headers,set()))
if __name__=='__main__':unittest.main()
