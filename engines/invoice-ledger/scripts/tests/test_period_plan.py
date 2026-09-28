"""Period and history-selection guards; no mailbox access."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from period_plan import make_plan,require_plan,selected_numbers,scoped_batch

class PeriodTests(unittest.TestCase):
    def test_month_required(self):
        for month in (None,'2026','2026-13','2026-9','0000-01','../2026-09'):
            with self.assertRaises(ValueError):make_plan(month,'local',history='exclude')
    def test_email_scope_required(self):
        for channel in ('imap','eml','mcp'):
            with self.assertRaises(ValueError):make_plan('2026-09',channel,history='exclude')
    def test_scope_separate_from_period(self):
        p=make_plan('2026-09','imap','2026-07-01','2026-08-01','exclude')
        self.assertEqual(p['period'],'2026-09');self.assertEqual(p['mail_start'],'2026-07-01')
    def test_history_decision_required(self):
        with self.assertRaises(ValueError):make_plan('2026-09','local')
    def test_selected_requires_explicit_numbers(self):
        for numbers in ([],[123],['123'],['2'*20,'2'*20]):
            with self.assertRaises(ValueError):make_plan('2026-09','local',history='selected',numbers=numbers)
    def test_old_unpaid_not_implicitly_selected(self):
        state={'reimbursement_plan':make_plan('2026-09','local',history='exclude'),'items':{'a':{'fields':{'发票号码全号':'1'*20},'status':'历史未报'},'b':{'fields':{'发票号码全号':'2'*20},'status':'历史未报','admitted_this_job':True}}}
        self.assertEqual(selected_numbers(state),['2'*20])
    def test_selected_old_not_required_in_current_download(self):
        state={'reimbursement_plan':make_plan('2026-09','local',history='selected',numbers=['1'*20]),'items':{}}
        self.assertEqual(selected_numbers(state),['1'*20])
    def test_legacy_job_cannot_infer_month(self):
        with self.assertRaises(ValueError):require_plan({'batch':'示例批次'})
    def test_month_namespaces_do_not_collide(self):
        self.assertNotEqual(scoped_batch('2026-09','第一批'),scoped_batch('2026-10','第一批'))
        self.assertEqual(scoped_batch('2026-09','2026-09_第一批'),'2026-09_第一批')

if __name__=='__main__':unittest.main()
