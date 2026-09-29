import copy
import csv
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from zipfile import ZipFile

import test_ai_stages
from ai_service import extract_work, validate_stage2
from dictionaries import load_dictionaries
from report_generator import FIELDS, align_work_items, generate_report


class ReviewTests(unittest.TestCase):
    def setUp(self):
        fixture = test_ai_stages.StageTests()
        fixture.setUp()
        self.first, self.second, self.text = fixture.first, fixture.second, fixture.text

    def details(self):
        checks = []
        items, _ = validate_stage2(self.second, self.first, checks)
        return items, checks

    def test_clear_review(self):
        self.second['today_items'][0].update(needs_review=False, review_reason='')
        self.assertFalse(self.details()[1][0]['needs_review'])
        self.assertEqual(self.details()[1][0]['review_reason'], '')

    def test_uncertain_people(self):
        self.second['today_items'][0].update(people=[], needs_review=True, review_reason='人员边界不明确')
        self.assertTrue(self.details()[1][0]['needs_review'])
        self.assertEqual(self.details()[1][0]['review_reason'], '人员边界不明确')

    def test_old_response_defaults(self):
        self.assertTrue(all(not row['needs_review'] and row['review_reason'] == '' for row in self.details()[1]))

    def test_review_types(self):
        for key, value in [('needs_review', 1), ('needs_review', 'false'), ('review_reason', None)]:
            payload = copy.deepcopy(self.second)
            payload['today_items'][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_stage2(payload, self.first)

    def test_dictionary_context_and_two_calls(self):
        with patch('ai_service.load_dictionaries', return_value={'professions': ['热工'], 'people': ['曹志勇']}), patch(
            'ai_service._request_completion', side_effect=[json.dumps(self.first), json.dumps(self.second)]
        ) as request:
            extract_work(self.text, 'test-key')
        self.assertEqual(request.call_count, 2)
        self.assertIn('["热工"]', request.call_args_list[0].args[0])
        self.assertIn('["曹志勇"]', request.call_args_list[1].args[0])
        self.assertIn('不是完整', request.call_args_list[0].args[0])
        self.assertIn('不是完整', request.call_args_list[1].args[0])

    def test_unknown_profession_preserved(self):
        self.first['professions'][0]['profession'] = '自动化专业'
        self.assertEqual(self.details()[0][0].profession, '自动化专业')

    def test_unknown_person_preserved(self):
        with patch('ai_service.load_dictionaries', return_value={'professions': ['热工'], 'people': ['曹志勇']}), patch(
            'ai_service._request_completion', side_effect=[json.dumps(self.first), json.dumps(self.second)]
        ):
            items, _ = extract_work(self.text, 'test-key')
        self.assertEqual(items[2].people, '张三')

    def test_id_comparison_binding(self):
        checks = self.details()[1]
        self.assertEqual([row['id'] for row in checks], ['T1', 'T2', 'T3', 'T4', 'M1', 'M2'])
        for check, source in zip(checks, self.first['professions'][0]['today_items'] + self.first['professions'][0]['tomorrow_items']):
            self.assertEqual(check['raw_text'], source['raw_text'])
            self.assertIn(check['result']['today'] or check['result']['tomorrow'], check['raw_text'])

    def test_review_not_in_word(self):
        baseline = io.BytesIO()
        marked = io.BytesIO()
        template = Path(__file__).parent / 'template/生产工作日报模板.docx'
        generate_report(template, self.details()[0], date(2026, 9, 18), baseline)
        self.second['today_items'][0].update(needs_review=True, review_reason='REVIEW_ONLY_MARKER')
        generate_report(template, self.details()[0], date(2026, 9, 18), marked)
        with ZipFile(baseline) as first, ZipFile(marked) as second:
            self.assertEqual({name: first.read(name) for name in first.namelist()},
                             {name: second.read(name) for name in second.namelist()})

    def test_dictionary_fallbacks(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dictionaries.json'
            self.assertEqual(load_dictionaries(path), {'professions': [], 'people': []})
            for value in ('', '{broken', 'null', '{"people": 12}'):
                path.write_text(value, encoding='utf-8')
                self.assertEqual(load_dictionaries(path), {'professions': [], 'people': []})

    def test_dictionary_valid(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dictionaries.json'
            path.write_text(json.dumps({'professions': ['热工'], 'people': ['曹志勇']}, ensure_ascii=False), encoding='utf-8')
            self.assertEqual(load_dictionaries(path), {'professions': ['热工'], 'people': ['曹志勇']})

    @patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-key'})
    def test_page_review_word_csv_and_mode_switch(self):
        from streamlit.testing.v1 import AppTest
        self.second['today_items'][0].update(needs_review=True, review_reason='人员边界不明确')
        self.second['tomorrow_items'][0].update(needs_review=True, review_reason='计划内容需核对')
        app = AppTest.from_file(str(Path(__file__).parent / 'app.py'), default_timeout=30).run()
        app.text_area[0].set_value(self.text).run()
        next(w for w in app.checkbox if w.label.startswith('我同意')).check().run()
        csv_streams = []
        original_writer = csv.writer

        def capture_writer(stream, *args, **kwargs):
            csv_streams.append(stream)
            return original_writer(stream, *args, **kwargs)

        with patch('ai_service._request_completion', side_effect=[json.dumps(self.first), json.dumps(self.second)]), patch('csv.writer', side_effect=capture_writer):
            app.button[0].click().run()
        csv_rows = list(csv.reader(io.StringIO(csv_streams[-1].getvalue())))
        self.assertEqual(csv_rows[0], list(FIELDS))
        self.assertEqual(len(csv_rows), 5)
        self.assertTrue(all(len(row) == len(FIELDS) for row in csv_rows))
        self.assertNotIn('needs_review', csv_streams[-1].getvalue())
        self.assertNotIn('人员边界不明确', csv_streams[-1].getvalue())
        self.assertFalse(app.exception)
        self.assertTrue(any('T1' in w.value and '人员边界不明确' in w.value for w in app.warning))
        self.assertTrue(any('M1' in w.value for w in app.warning))
        self.assertTrue(any(widget.label == '查看AI识别对照' for widget in app.expander))
        self.assertEqual(len(app.session_state['records']), 4)
        self.assertEqual(tuple(app.session_state['records'][0]), FIELDS)
        next(w for w in app.checkbox if w.label == '已核对以上数据，确认生成').check().run()
        next(w for w in app.button if w.label == '生成 Word').click().run()
        self.assertFalse(app.error)
        self.assertIn('download', app.session_state)
        csv_button = next(w for w in app.get('download_button') if w.proto.label == '下载整理后的逗号文本')
        self.assertTrue(csv_button.proto.url)
        app.radio[0].set_value('逗号文本（无需API）').run()
        app.text_area[0].set_value('热工,检查,,,张三,,,').run()
        app.button[0].click().run()
        self.assertNotIn('ai_review', app.session_state)
        self.assertFalse(any(widget.label == '查看AI识别对照' for widget in app.expander))
        self.assertFalse(app.exception)


if __name__ == '__main__':
    unittest.main()
