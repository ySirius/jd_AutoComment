import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import auto_comment_plus as app


def response(text='', data=None, status=200):
    result = Mock(status_code=status, text=text)
    result.json.return_value = data
    return result


def image_data(*urls):
    return {'imgComments': {
        'imgCommentCount': len(urls),
        'imgList': [{'imageUrl': url} for url in urls],
    }}


class ImageTests(unittest.TestCase):
    def test_download_accepts_absolute_and_protocol_relative_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            for url in ('//img.test/image.jpg', 'https://img.test/image.jpg',
                        'http://img.test/image.jpg'):
                with self.subTest(url=url), patch.object(app.requests, 'get') as get:
                    get.return_value.content = b'image bytes'
                    target = str(Path(directory) / 'image.jpg')
                    with patch.object(app.os, 'makedirs'):
                        self.assertEqual(app.download_image(url, target), target)
                    self.assertEqual(get.call_args.args[0],
                                     'https:' + url if url.startswith('//') else url)
                    self.assertEqual(Path(target).read_bytes(), b'image bytes')

    def test_download_failure_returns_none(self):
        with patch.object(app.requests, 'get', side_effect=requests.Timeout):
            self.assertIsNone(app.download_image('//img.test/image.jpg', 'test.jpg'))

    def test_upload_sends_filename_and_closes_file(self):
        session = Mock()
        headers = {'Cookie': 'fake-cookie', 'Content-Type': 'application/x-www-form-urlencoded'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.jpg'
            path.write_bytes(b'image bytes')

            def post(*args, **kwargs):
                name, file, mime = kwargs['files']['Filedata']
                self.assertEqual(name, 'image.jpg')
                self.assertEqual(file.read(), b'image bytes')
                self.assertEqual(mime, 'image/jpeg')
                self.assertNotIn('Content-Type', kwargs['headers'])
                self.assertEqual(kwargs['headers']['Cookie'], 'fake-cookie')
                return response('jfs/uploaded.jpg')

            session.post.side_effect = post
            result = app.upload_image('image.jpg', str(path), session, headers)
            self.assertEqual(result.text, 'jfs/uploaded.jpg')
            self.assertTrue(session.post.call_args.kwargs['files']['Filedata'][1].closed)
            self.assertIn('Content-Type', headers)

    def test_upload_http_error_is_failure_and_closes_file(self):
        session = Mock()
        session.post.return_value.raise_for_status.side_effect = requests.HTTPError
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'image.jpg'
            path.write_bytes(b'image bytes')
            self.assertIsNone(app.upload_image('image.jpg', str(path), session, {}))
            self.assertTrue(session.post.call_args.kwargs['files']['Filedata'][1].closed)

    def test_uploaded_url_normalization(self):
        cases = {
            'jfs/t1/new.jpg': '//img20.360buyimg.com/shaidan/s645x515_jfs/t1/new.jpg',
            ' "jfs/t1/new.png"\n': '//img20.360buyimg.com/shaidan/s645x515_jfs/t1/new.png',
            '//img30.360buyimg.com/shaidan/new.jpg': '//img30.360buyimg.com/shaidan/new.jpg',
            'https://img30.360buyimg.com/shaidan/new.jpeg': 'https://img30.360buyimg.com/shaidan/new.jpeg',
            '<html>error.jpg</html>': None,
            'error.jpg': None,
            '': None,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(app.uploaded_image_url(response(value)), expected)
        self.assertIsNone(app.uploaded_image_url(None))
        self.assertIsNone(app.uploaded_image_url(response('jfs/new.jpg', status=500)))

    def test_single_image_uses_uploaded_url(self):
        with patch.object(app, 'download_image', return_value='image.jpg'), \
             patch.object(app, 'upload_image', return_value=response('jfs/new.jpg')) as upload:
            actual = app.prepare_comment_images(image_data('//img.test/original.jpg'), Mock(), {})
        self.assertEqual(actual, ['//img20.360buyimg.com/shaidan/s645x515_jfs/new.jpg'])
        upload.assert_called_once()

    def test_partial_upload_failure_keeps_only_successful_image(self):
        with patch.object(app, 'download_image', return_value='image.jpg'), \
             patch.object(app, 'upload_image', side_effect=[None, response('jfs/second.jpg')]):
            actual = app.prepare_comment_images(image_data('//img.test/1.jpg', '//img.test/2.jpg'), Mock(), {})
        self.assertEqual(actual, ['//img20.360buyimg.com/shaidan/s645x515_jfs/second.jpg'])

    def test_all_uploads_failed_does_not_fall_back_to_source_urls(self):
        with patch.object(app, 'download_image', return_value='image.jpg'), \
             patch.object(app, 'upload_image', return_value=None), \
             self.assertRaises(ValueError):
            app.prepare_comment_images(image_data('//img.test/1.jpg'), Mock(), {})

    def test_download_failure_does_not_upload(self):
        with patch.object(app, 'download_image', return_value=None), \
             patch.object(app, 'upload_image') as upload, self.assertRaises(ValueError):
            app.prepare_comment_images(image_data('//img.test/1.jpg'), Mock(), {})
        upload.assert_not_called()

    def test_no_images_and_malformed_responses_are_distinct(self):
        self.assertEqual(app.prepare_comment_images(image_data(), Mock(), {}), [])
        for data in (None, {}, {'imgComments': None},
                     {'imgComments': {'imgCommentCount': 1, 'imgList': []}}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                app.prepare_comment_images(data, Mock(), {})


class OrdinaryImageTests(unittest.TestCase):
    def run_orders(self, images, uploads, dry_run=False):
        bodies = []
        for i in range(len(images)):
            bodies.append(f'''<tbody>
              <tr class="tr-th"><td><span></span><span></span><span><a>order-{i}</a></span></td></tr>
              <tr class="tr-bd"><td><div><div></div><div><div>
                <a href="//item.jd.com/{i}.html">Product {i}</a>
              </div></div></div></td></tr>
            </tbody>''')
        html = '<div id="main"><div></div><div><div></div><div><table>' + ''.join(bodies) + '</table></div></div></div>'
        gets = [response(html)] + [response(data=data) for data in images]
        with patch.object(app, 'headers', {}, create=True), \
             patch.object(app, 'headers2', {}, create=True), \
             patch.object(app.time, 'sleep'), \
             patch.object(app, 'generation', return_value=(5, 'Test review')), \
             patch.object(app.requests, 'get', side_effect=gets), \
             patch.object(app, 'download_image', return_value='image.jpg'), \
             patch.object(app, 'upload_image', side_effect=uploads), \
             patch.object(app.cffi_req, 'post', return_value=response(data={'success': True})) as post:
            app.ordinary({'待评价订单': len(images)}, {'logger': logging.getLogger('test'), 'dry_run': dry_run})
        return post

    def test_imageless_product_does_not_disable_next_products_images(self):
        post = self.run_orders([image_data(), image_data('//img.test/original.jpg')],
                               [response('jfs/uploaded.jpg')])
        self.assertEqual(post.call_count, 2)
        first, second = [call.kwargs['data'] for call in post.call_args_list]
        self.assertNotIn('imgs', first)
        self.assertEqual(second['imgs'], '//img20.360buyimg.com/shaidan/s645x515_jfs/uploaded.jpg')

    def test_failed_product_is_skipped_and_next_product_still_has_images(self):
        post = self.run_orders([image_data('//img.test/1.jpg'), image_data('//img.test/2.jpg')],
                               [None, response('jfs/uploaded.jpg')])
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['data']['productId'], '1')
        self.assertIn('imgs', post.call_args.kwargs['data'])

    def test_two_images_are_submitted_as_uploaded_urls(self):
        post = self.run_orders([image_data('//img.test/1.jpg', '//img.test/2.jpg')],
                               [response('jfs/first.jpg'), response('jfs/second.jpg')])
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs['data']['imgs'],
                         '//img20.360buyimg.com/shaidan/s645x515_jfs/first.jpg,'
                         '//img20.360buyimg.com/shaidan/s645x515_jfs/second.jpg')

    def test_dry_run_does_not_submit_comment(self):
        post = self.run_orders([image_data('//img.test/1.jpg')],
                               [response('jfs/uploaded.jpg')], dry_run=True)
        post.assert_not_called()


if __name__ == '__main__':
    unittest.main()
