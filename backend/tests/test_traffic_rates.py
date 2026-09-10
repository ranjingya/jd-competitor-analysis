"""验证渠道占比的日与周期计算口径。"""

import unittest

from jd_competitor_analysis.dimensions import enrich_traffic_visitor_rates
from jd_competitor_analysis.period_aggregation import _aggregate_traffic


def channel(first, second, own, competitor):
    """生成包含无关源占比的渠道测试行。"""
    return dict(level_1=first, level_2=second, level_3=None,
                self_visitors=own, competitor_visitors=competitor,
                self_visitor_rate=1.025, competitor_visitor_rate=1.025,
                self_total_visitor_rate=1.025, competitor_total_visitor_rate=1.025)


class TrafficRatesTests(unittest.TestCase):
    def test_separate_totals_and_direct_siblings(self):
        rows = [channel('内', None, 150, 80), channel('外', None, 50, 20),
                channel('内', '搜索', 30, 10), channel('内', '推荐', 20, 30)]
        enrich_traffic_visitor_rates(rows)
        self.assertEqual(rows[0]['self_total_visitor_rate'], .75)
        self.assertEqual(rows[0]['competitor_total_visitor_rate'], .8)
        self.assertEqual(rows[2]['self_current_level_visitor_rate'], .6)
        self.assertEqual(rows[2]['self_total_visitor_rate'], .15)
        self.assertEqual(rows[2]['competitor_current_level_visitor_rate'], .25)
        self.assertEqual(rows[2]['competitor_total_visitor_rate'], .1)
        self.assertEqual(rows[2]['self_visitors'], 30)
        self.assertEqual(rows[0]['self_visitor_rate'], .75)

    def test_missing_and_zero_denominators(self):
        rows = [channel('内', None, None, 0), channel('内', '搜索', 10, None)]
        enrich_traffic_visitor_rates(rows)
        self.assertIsNone(rows[0]['self_total_visitor_rate'])
        self.assertIsNone(rows[0]['competitor_total_visitor_rate'])
        self.assertIsNone(rows[1]['self_total_visitor_rate'])
        self.assertIsNone(rows[1]['competitor_current_level_visitor_rate'])

    def test_period_uses_accumulated_channels_not_daily_rates(self):
        days = [{'report': {'traffic_sources': [channel('内', None, 100, 50),
                                                channel('外', None, 100, 50)]}},
                {'report': {'traffic_sources': [channel('内', None, 300, 50),
                                                channel('外', None, 0, 150)]}}]
        result = {r['level_1']: r for r in _aggregate_traffic(days)}
        self.assertEqual(result['内']['self_visitors'], 400)
        self.assertEqual(result['内']['self_total_visitor_rate'], .8)
        self.assertAlmostEqual(result['内']['competitor_total_visitor_rate'], 1 / 3)
