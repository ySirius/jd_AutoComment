import unittest
from unittest.mock import patch

import auto_comment_plus as app


class CommentLengthTests(unittest.TestCase):
    def generate(self, sentences, name='八角', product='王守义八角55g'):
        with patch.object(app.jdspider, 'JDSpider') as spider, \
             patch.object(app.jieba.analyse, 'textrank', return_value=[name]):
            spider.return_value.get_data.return_value = sentences
            return app.generation(product)

    def test_short_source_is_extended_to_eighty_characters(self):
        for _ in range(20):
            score, text = self.generate(['不错不错！', '很好！'])
            self.assertEqual(score, 5)
            self.assertGreaterEqual(len(text), 80)
            self.assertNotIn('$', text)
            self.assertIn(text[-1], '。！？.!?')

    def test_empty_source_uses_templates(self):
        for source in ([], ['', '  ', None]):
            with self.subTest(source=source):
                _, text = self.generate(source)
                self.assertGreaterEqual(len(text), 80)

    def test_product_substitution_is_counted_before_length_check(self):
        source = '$' * 30 + '！'
        _, text = self.generate([source], name='调味八角')
        self.assertEqual(text, '调味八角' * 30 + '！')
        self.assertNotIn('$', text)

    def test_gift_review_also_reaches_eighty_characters(self):
        _, text = self.generate([], product='赠品收纳袋', name='收纳袋')
        self.assertGreaterEqual(len(text), 80)

    def test_review_keeps_existing_four_sentence_behavior(self):
        with patch.object(app.jdspider, 'JDSpider') as spider, \
             patch.object(app.jieba.analyse, 'textrank', return_value=['八角']):
            spider.return_value.get_data.return_value = ['不错！', '很好！', '满意！', '喜欢！', '实用！']
            _, text = app.generation('八角', _type=0)
        self.assertEqual(text.count('！'), 4)


if __name__ == '__main__':
    unittest.main()
