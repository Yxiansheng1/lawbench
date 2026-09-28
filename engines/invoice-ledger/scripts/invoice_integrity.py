"""Shared invoice amount, identity and admission rules. No file-name amount fallback."""
import re
from decimal import Decimal, InvalidOperation
from datetime import date

def total_amount(text):
    number = r'([+-]?\d[\d,]*(?:\.\d{1,2})?)(?![\d.])'
    patterns = [
        r'价税合计[^\n\r]{0,90}?[（(]\s*小写\s*[)）]\s*[:：]?\s*[¥￥]?\s*' + number,
        r'价税合计\s*[:：]?\s*[¥￥]\s*' + number,
        r'(?:票面金额|实收金额|票价|票款|总金额)\s*[:：]?\s*[¥￥]?\s*' + number,
    ]
    for pattern in patterns:
        values = {Decimal(v.replace(',', '')) for v in re.findall(pattern, text)}
        if values:
            if len(values) != 1:
                return '', '多个明确合计金额不一致'
            return format(next(iter(values)), '.2f'), ''
    return '', '未找到明确的价税合计或票价标签'

def valid_identity(value):
    # Numeric concatenation of 10/12-digit legacy code + 8-digit number, or 20-digit e-invoice.
    return bool(re.fullmatch(r'(?:\d{18}|\d{20})', str(value or '')))

def admission_errors(r, categories=None):
    errors = []
    full = str(r.get('发票号码全号') or '')
    if not valid_identity(full): errors.append('票据身份不完整：需20位数电票号或10/12位代码与8位号码组合')
    if r.get('_amount_error'): errors.append(r['_amount_error'])
    try:
        amount = Decimal(str(r.get('价税合计（元）')))
        if not amount.is_finite() or amount == 0 or amount != amount.quantize(Decimal('.01')):
            errors.append('金额必须为非零、有限的两位小数')
    except (InvalidOperation, TypeError, ValueError): errors.append('金额缺失或非法')
    try:
        dt = date.fromisoformat(str(r.get('开票日期')))
        if dt > date.today(): errors.append('开票日期在未来')
    except (ValueError, TypeError): errors.append('开票日期缺失或非法')
    category = r.get('发票类别')
    if not category or category in ('其他','未分类') or (categories is not None and category not in categories):
        errors.append('分类缺失或需人工核定')
    return errors

def ledger_gate(rows, headers, excluded):
    failures, seen = [], {}
    for n, row in enumerate(rows, 2):
        r = {k: row[i] if i < len(row) else None for k, i in headers.items()}
        if r.get('状态') in excluded: continue
        errors = admission_errors(r)
        key = str(r.get('发票号码全号') or '')
        if key and key in seen: errors.append(f'有效全号重复，另见第{seen[key]}行')
        seen[key] = n
        if errors: failures.append((n, '；'.join(errors)))
    return failures
