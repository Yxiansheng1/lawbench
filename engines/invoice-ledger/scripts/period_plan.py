"""Confirmed reimbursement period and explicit selection of old unpaid records."""
from datetime import date
import re

def make_plan(period, channel, start=None, end=None, history=None, numbers=None):
    if not re.fullmatch(r'[0-9]{4}-(0[1-9]|1[0-2])',period or ''):
        raise ValueError('报销年月须为YYYY-MM，必须先询问用户，不能从票面日期推定')
    date.fromisoformat(period+'-01')
    if channel not in ('local','eml','imap','mcp'):raise ValueError('收集渠道无效')
    if channel!='local' and not (start and end):raise ValueError('邮件来源必须明确搜索起止日期')
    if bool(start)!=bool(end):raise ValueError('搜索起止日期必须同时填写')
    if start and date.fromisoformat(start)>=date.fromisoformat(end):raise ValueError('搜索结束日期为不含上界，必须晚于开始日期')
    if history not in ('exclude','selected'):raise ValueError('必须询问历史未报票是否纳入：exclude或selected')
    numbers=numbers or []
    if not isinstance(numbers,list) or any(not isinstance(n,str) or not re.fullmatch(r'[0-9]{18,20}',n) for n in numbers) or len(numbers)!=len(set(numbers)):
        raise ValueError('历史清单须为不重复的完整票号字符串数组')
    if history=='selected' and not numbers:raise ValueError('纳入历史票须逐张明确票号，不能仅凭未报状态全选')
    if history=='exclude' and numbers:raise ValueError('不纳入历史票时不能提供票号')
    return {'period':period,'channel':channel,'mail_start':start,'mail_end_exclusive':end,'history':history,'history_numbers':numbers}

def require_plan(state):
    p=state.get('reimbursement_plan')
    if not p:raise ValueError('尚未确认报销年月、邮件搜索范围及历史未报票安排；先执行plan')
    return make_plan(p['period'],p['channel'],p.get('mail_start'),p.get('mail_end_exclusive'),p['history'],p['history_numbers'])

def selected_numbers(state):
    p=require_plan(state)
    new={i['fields']['发票号码全号'] for i in state['items'].values() if i.get('admitted_this_job') and i['status']=='历史未报'}
    return sorted(new|set(p['history_numbers']))

def scoped_batch(period,batch):
    prefix=period+'_'
    return batch if batch.startswith(prefix) else prefix+batch
