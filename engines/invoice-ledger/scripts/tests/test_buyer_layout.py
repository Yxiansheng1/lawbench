"""购买方抬头解析：横排版式与数电票竖排表格版式的回归测试（离线，不访问邮箱）。
测试使用合成购买方名称并显式传入期望值，不依赖本机 buyer.json，跨机可复现。"""
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from buyer_verification import parse_buyer, buyer_errors, annotate, normalize

LAW = '示例科技（深圳）有限公司'


def vertical_layout():
    """数电票（Suwell OFD→PDF）真实版式：购买方/销售方信息竖排成「购/买/方/信/息」+「购 名称：」。"""
    return ('         电子发票（普通发票）     发票号码：26000000000000000001\n\n'
            '                                               开票日期：2026年09月16日\n\n'
            ' 购 名称：' + LAW + '                销 名称：某某餐饮有限公司\n'
            ' 买                                   售\n'
            ' 方                                   方\n'
            ' 信 统一社会信用代码/纳税人识别号：91440000MA00000001  信 统一社会信用代码/纳税人识别号：91440300MA00000002\n'
            ' 息                                   息\n')


def horizontal_layout():
    return '购买方名称：' + LAW + ' 统一社会信用代码：91440000MA00000001\n销售方名称：某某公司\n'


class BuyerLayoutTests(unittest.TestCase):
    def test_horizontal_still_passes(self):
        r = parse_buyer(horizontal_layout(), LAW)
        self.assertEqual(r['抬头核验'], '通过', r)
        self.assertEqual(normalize(r['购买方名称']), normalize(LAW))

    def test_vertical_layout_passes(self):
        r = parse_buyer(vertical_layout(), LAW)
        self.assertEqual(r['抬头核验'], '通过', r)
        self.assertEqual(normalize(r['购买方名称']), normalize(LAW))
        # annotate 才会补 材料类型，buyer_errors 同时校验该项
        self.assertEqual(buyer_errors(annotate(vertical_layout(), {}, LAW), LAW), [])

    def test_vertical_layout_does_not_leak_seller(self):
        got = normalize(parse_buyer(vertical_layout(), LAW)['购买方名称'])
        self.assertNotIn('销', got)
        self.assertNotIn('某某餐饮', got)

    def test_vertical_layout_wrong_buyer_is_error_not_pending(self):
        text = vertical_layout().replace(LAW, '某某科技有限公司')
        r = parse_buyer(text, LAW)
        self.assertEqual(r['抬头核验'], '错误', r)
        self.assertEqual(normalize(r['购买方名称']), '某某科技有限公司')

    def test_missing_buyer_is_pending(self):
        text = ' 销 名称：某某餐饮有限公司\n统一社会信用代码：91440300MA00000002\n'
        r = parse_buyer(text, LAW)
        self.assertEqual(r['抬头核验'], '待核', r)
        self.assertEqual(r['购买方名称'], '')
        self.assertIn('购买方抬头待核', buyer_errors(annotate(text, {}, LAW), LAW))

    def test_buyer_label_not_confused_by_product_name(self):
        # 「项目名称/货物名称」等不得被当作购买方标签
        text = '    项目名称    规格型号    单 位     数 量     单 价     金 额\n'
        r = parse_buyer(text, LAW)
        self.assertEqual(r['抬头核验'], '待核', r)

    def test_configurable_buyer_accepts_other_entity(self):
        # 购买方可配置：换主体后，同一张票的判定随之改变
        text = '购买方名称：某某科技有限公司\n'
        self.assertEqual(parse_buyer(text, '某某科技有限公司')['抬头核验'], '通过')
        self.assertEqual(parse_buyer(text, LAW)['抬头核验'], '错误')


if __name__ == '__main__':
    unittest.main()
