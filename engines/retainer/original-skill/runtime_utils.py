"""Deterministic input and DOCX helpers; no network or source-template writes."""
import os
import re
import zipfile
from decimal import Decimal
from lxml import etree

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
NS = {'w': W}


def integer_cn(n, digits='零壹贰叁肆伍陆柒捌玖'):
    if n == 0:
        return digits[0]
    units = ['', '拾', '佰', '仟'] if digits[1] == '壹' else ['', '十', '百', '千']
    groups = ['', '万', '亿', '兆']
    if not 0 <= n < 10**16:
        raise ValueError('金额超出支持范围')
    chunks = []
    while n:
        chunks.append(n % 10000)
        n //= 10000
    out = ''
    gap = False
    for i in range(len(chunks)-1, -1, -1):
        value = chunks[i]
        if not value:
            gap = bool(out)
            continue
        if out and (gap or value < 1000):
            out += digits[0]
        part = ''
        zero = False
        for pos in range(3, -1, -1):
            d = value // 10**pos % 10
            if d:
                if zero:
                    part += digits[0]
                part += digits[d] + units[pos]
                zero = False
            elif part:
                zero = True
        out += part + groups[i]
        gap = False
    if digits[1] == '一' and out.startswith('一十'):
        out = out[1:]
    return out


def money(value):
    value = value.replace('，', ',').replace('萬', '万').strip()
    if ',' in value and not re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d+)?\s*(?:万)?(?:元)?(?:整)?', value):
        raise ValueError('千位分隔符格式错误')
    value = value.replace(',', '')
    m = re.fullmatch(r'(\d+(?:\.\d+)?)\s*(万)?(?:元)?(?:整)?', value)
    if not m:
        raise ValueError('金额请使用阿拉伯数字，如 50000元、2.5万元')
    amount = Decimal(m[1]) * (10000 if m[2] else 1)
    if amount >= Decimal(10**16) or amount != amount.quantize(Decimal('.01')):
        raise ValueError('金额超出范围或精度超过分')
    cents = int(amount * 100)
    yuan, fraction = divmod(cents, 100)
    jiao, fen = divmod(fraction, 10)
    upper = integer_cn(yuan) + '元'
    if not fraction:
        upper += '整'
    else:
        if jiao:
            upper += '零壹贰叁肆伍陆柒捌玖'[jiao] + '角'
        elif yuan:
            upper += '零'
        if fen:
            upper += '零壹贰叁肆伍陆柒捌玖'[fen] + '分'
    return upper, format(amount, 'f').rstrip('0').rstrip('.') if '.' in format(amount, 'f') else str(amount)


def parse_fee(text, fee_type):
    text = text.strip().replace('％', '%').replace('萬', '万')
    rates = list(re.finditer(r'(\d+(?:\.\d+)?)\s*%', text))
    cn = re.search(r'百分之([零〇一二两三四五六七八九十百点\d.]+)', text)
    if cn:
        raw = cn[1]
        if re.fullmatch(r'\d+(?:\.\d+)?', raw):
            rate = Decimal(raw)
        else:
            def to_n(s):
                for i in range(101):
                    if integer_cn(i, '零一二三四五六七八九') == s.replace('两', '二').replace('〇', '零'):
                        return i
                raise ValueError('无法识别中文百分比')
            bits = raw.split('点')
            rate = Decimal(to_n(bits[0]))
            if len(bits) > 1:
                rate += Decimal('0.' + ''.join(str('零一二三四五六七八九'.index(c)) for c in bits[1]))
        rate_text = format(rate, 'f')
    elif len(rates) == 1:
        rate_text = rates[0][1]
        rate = Decimal(rate_text)
    else:
        rate = None
    if len(rates) > 1 or (cn and rates):
        raise ValueError('请只提供一个风险费率')
    amount_text = re.sub(r'\d+(?:\.\d+)?\s*%', '', text)
    if cn:
        amount_text = amount_text.replace(cn[0], '')
    matches = re.findall(r'\d[\d,，]*(?:\.\d+)?\s*(?:万)?(?:元)?', amount_text)
    if len(matches) != 1 or re.search(r'[-负]|结果|另付|后期\s*\d', amount_text):
        raise ValueError('请提供一个明确金额；分期或结果收费方案暂不支持自动生成')
    upper, short = money(matches[0])
    result = {'upfront': upper, 'upfront_short': '¥' + short, 'risk_rate': '百分之___（___%）'}
    if fee_type == 'semi_risk':
        if rate is None or not 0 < rate <= 100:
            raise ValueError('半风险收费需要明确前期金额及 0 至 100 之间的费率')
        whole, _, fraction = rate_text.partition('.')
        cn_rate = integer_cn(int(whole), '零一二三四五六七八九')
        if fraction:
            cn_rate += '点' + ''.join('零一二三四五六七八九'[int(c)] for c in fraction)
        result['risk_rate'] = f'百分之{cn_rate}（{rate_text}%）'
    elif rate is not None or any(k in text for k in ['风险', '回款', '分成']):
        raise ValueError('固定收费模板不支持风险或比例收费')
    return result


def safe_name(name):
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:100]
    if not name or name in {'.', '..'}:
        raise ValueError('目录名称不能为空')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', name, re.I):
        name = '_' + name
    return name


def unique_directory(base, name):
    os.makedirs(base, exist_ok=True)
    name = safe_name(name)
    for i in range(10000):
        path = os.path.join(base, name + (f' ({i})' if i else ''))
        try:
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise FileExistsError('同名目录过多')


def replace_text_nodes(nodes, replacements):
    """Replace across text nodes, retaining unrelated text and run properties."""
    text = ''.join(n.text or '' for n in nodes)
    if not replacements:
        return
    pattern = re.compile('|'.join(re.escape(k) for k in sorted(replacements, key=len, reverse=True)))
    offsets, pos = [], 0
    for n in nodes:
        offsets.append(pos)
        pos += len(n.text or '')
    for match in reversed(list(pattern.finditer(text))):
        hits = [i for i, n in enumerate(nodes) if offsets[i] < match.end() and offsets[i] + len(n.text or '') > match.start()]
        if not hits:
            continue
        first, last = hits[0], hits[-1]
        prefix = (nodes[first].text or '')[:match.start()-offsets[first]]
        suffix = (nodes[last].text or '')[match.end()-offsets[last]:]
        value = str(replacements[match[0]])
        nodes[first].text = prefix + value + (suffix if first == last else '')
        nodes[first].set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
        for i in hits[1:]:
            nodes[i].text = suffix if i == last else ''


def fill_template(src, dst, replacements):
    payload = []
    with zipfile.ZipFile(src) as z:
        for info in z.infolist():
            data = z.read(info.filename)
            if info.filename.startswith('word/') and info.filename.endswith('.xml'):
                root = etree.fromstring(data)
                for para in root.findall('.//w:p', NS):
                    replace_text_nodes(para.findall('.//w:t', NS), replacements)
                data = etree.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
            payload.append((info, data))
    with zipfile.ZipFile(dst, 'w') as z:
        for info, data in payload:
            z.writestr(info, data)


def docx_text(path):
    parts = []
    with zipfile.ZipFile(path) as z:
        for n in z.namelist():
            if n.startswith('word/') and n.endswith('.xml'):
                root = etree.fromstring(z.read(n))
                parts.extend(''.join(p.xpath('.//w:t/text()', namespaces=NS)) for p in root.findall('.//w:p', NS))
    return '\n'.join(parts)
