import sys
from pathlib import Path
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

import unittest
from unittest.mock import patch, Mock

import analyzer


class AnalyzerTests(unittest.TestCase):

    def test_parse_price_from_text(self):
        self.assertEqual(analyzer.parse_price_from_text("$123.45"), 123.45)
        self.assertEqual(analyzer.parse_price_from_text("USD $1,200"), 1200.0)

    @patch('analyzer.requests.get')
    def test_scrape_price_data(self, mock_get):
        html = '<table><tr><td>Booster Box</td><td>$999.99</td></tr></table>'
        mock_get.return_value = Mock(status_code=200, text=html)
        price = analyzer.scrape_price_data("Test Set")
        self.assertAlmostEqual(price, 999.99)

    @patch('analyzer.requests.get')
    def test_scrape_ebay_sales(self, mock_get):
        html = '<ul><li class="s-item">Sold item $50 Mar 10, 2025</li></ul>'
        mock_get.return_value = Mock(status_code=200, text=html)
        res = analyzer.scrape_ebay_sales("Test query")
        self.assertEqual(res['count_sold'], 1)
        self.assertAlmostEqual(res['avg_price'], 50.0)

    @patch('analyzer.requests.get')
    def test_scrape_tcgplayer_listings(self, mock_get):
        html = 'Showing 123 listings as low as $10'
        mock_get.return_value = Mock(status_code=200, text=html)
        res = analyzer.scrape_tcgplayer_listings("Test product")
        self.assertEqual(res['listings_count'], 123)

    @patch('analyzer.requests.get')
    def test_get_set_info(self, mock_get):
        # First call: API search JSON
        api_resp = Mock()
        api_resp.status_code = 200
        api_resp.json.return_value = {"query": {"search": [{"title": "Test Set"}]}}

        # Second call: page HTML with infobox
        html = '<table class="infobox"><tr><th>Cards</th><td>60</td></tr><tr><th>Released</th><td>January 1, 2020</td></tr></table>'
        page_resp = Mock(status_code=200, text=html)

        mock_get.side_effect = [api_resp, page_resp]
        info = analyzer.get_set_info("Test Set")
        self.assertEqual(info['num_cards'], 60)
        self.assertIn('2020', info['release_date'])

    @patch('analyzer.requests.get')
    def test_get_top_chase_cards(self, mock_get):
        html = '<table><tr><td><a href="/product/1">Rare Card</a></td><td>$500</td></tr></table>'
        mock_get.return_value = Mock(status_code=200, text=html)
        res = analyzer.get_top_chase_cards("Test Set", top_n=1)
        self.assertEqual(len(res['top_cards']), 1)
        self.assertEqual(res['top_cards'][0]['name'], 'Rare Card')
        self.assertAlmostEqual(res['top_cards'][0]['price'], 500.0)

    @patch('analyzer.subprocess.run')
    def test_check_reprint_news_cli(self, mock_run):
        # simulate snscrape CLI output
        sample = '{"content":"Possible reprint announced","user":{"username":"user1"},"id":"123"}\n'
        mock_run.return_value = Mock(returncode=0, stdout=sample)
        res = analyzer.check_reprint_news("Test Set")
        self.assertTrue(res['warning'])

    @patch('analyzer.requests.get')
    def test_get_psa_population(self, mock_get):
        html = 'PSA 10 123 PSA 9 200'
        mock_get.return_value = Mock(status_code=200, text=html)
        res = analyzer.get_psa_population("Test Card")
        self.assertEqual(res['psa10'], 123)

    @patch('analyzer.requests.get')
    def test_analyze_sentiment_fallback(self, mock_get):
        # force requests.get to raise so analyze_sentiment uses dummy fallback
        mock_get.side_effect = Exception('network')
        res = analyzer.analyze_sentiment("Test Set")
        self.assertIn(res['classification'], ('mixed', 'mostly positive', 'mostly negative', 'no data'))

    def test_compute_metrics_with_mocks(self):
        # Use patch to temporarily replace internal functions so globals aren't mutated
           # Patch the underlying core module used by the wrapper so compute_metrics
           # (which lives in the core module) resolves the mocked functions.
           with patch('analyzer.analyzer_core.scrape_price_data', return_value=150.0), \
               patch('analyzer.analyzer_core.scrape_ebay_sales', return_value={"count_sold": 14, "avg_price": 140.0}), \
               patch('analyzer.analyzer_core.scrape_tcgplayer_listings', return_value={"listings_count": 28}), \
               patch('analyzer.analyzer_core.get_top_chase_cards', return_value={"top_cards": [{"name": "Top", "price": 50.0}], "sum_top": 50.0, "avg_top": 50.0}), \
               patch('analyzer.analyzer_core.get_psa_population', return_value={"psa10": 10}), \
               patch('analyzer.analyzer_core.check_reprint_news', return_value={"warning": False, "matches": []}), \
               patch('analyzer.analyzer_core.analyze_sentiment', return_value={"avg_polarity": 0.5, "classification": "mostly positive", "sample": []}):

            metrics = analyzer.compute_metrics("Test Set")
            self.assertEqual(metrics['box_price'], 150.0)
            self.assertEqual(metrics['sold_count_30d'], 14)
            self.assertEqual(metrics['listings_count'], 28)
            self.assertIn('summary', metrics)


if __name__ == '__main__':
    unittest.main()
