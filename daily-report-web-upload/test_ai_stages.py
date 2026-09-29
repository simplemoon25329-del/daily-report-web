import copy
import io
import json
import os
import unittest
from unittest.mock import patch

from ai_service import extract_work, validate_stage1, validate_stage2
from report_generator import align_work_items


class StageTests(unittest.TestCase):
    def setUp(self):
        self.tasks = ['检查240T1# 徐超 赵千喜', '更换75T 米中玉 沈一凡',
                      '检查2#首站 张三', '检查7MW1#及25MW 李四']
        self.plans = ['复查240T1#', '复查75T']
        self.text = '热工今日工作：\n' + '\n'.join(self.tasks) + '\n明日计划：\n' + '\n'.join(self.plans)
        self.first = {'professions': [{'profession': '热工',
            'today_items': [{'id': 'T' + str(i + 1), 'raw_text': text} for i, text in enumerate(self.tasks)],
            'tomorrow_items': [{'id': 'M' + str(i + 1), 'raw_text': text} for i, text in enumerate(self.plans)]}], 'warnings': []}
        self.second = {'today_items': [{'id': 'T' + str(i + 1), 'today': text.split()[0],
            'people': text.split()[1:], 'today_hazard': None, 'status': None, 'remark': ''}
            for i, text in enumerate(self.tasks)],
            'tomorrow_items': [{'id': 'M' + str(i + 1), 'tomorrow': text, 'tomorrow_hazard': None}
            for i, text in enumerate(self.plans)]}

    def test_two_calls_and_four_preview_rows(self):
        responses = [io.BytesIO(json.dumps({'choices': [{'finish_reason': 'stop',
            'message': {'content': json.dumps(value)}}]}).encode('utf-8'))
            for value in (self.first, self.second)]
        with patch('urllib.request.build_opener') as opener:
            opener.return_value.open.return_value.__enter__.side_effect = responses
            items, warnings = extract_work(self.text, 'test-key')
            self.assertEqual(opener.return_value.open.call_count, 2)
            body = json.loads(opener.return_value.open.call_args_list[1].args[0].data)
            self.assertEqual(json.loads(body['messages'][1]['content']), self.first)
        rows = align_work_items(items)
        self.assertEqual(len(rows), 4)
        self.assertEqual([row.tomorrow for row in rows], self.plans + ['', ''])
        self.assertEqual([row.today for row in rows], [text.split()[0] for text in self.tasks])
        self.assertEqual([row.people for row in rows], ['徐超 赵千喜', '米中玉 沈一凡', '张三', '李四'])
        self.assertTrue(all(row.today_hazard == '否' and row.status == '已完成' for row in rows))
        self.assertEqual(warnings, [])

    def test_stage1_ids_and_raw_text(self):
        for key, value in [('id', 'T2'), ('id', None), ('raw_text', ''), ('raw_text', '改写原文')]:
            with self.subTest(key=key, value=value):
                payload = copy.deepcopy(self.first)
                payload['professions'][0]['today_items'][0][key] = value
                with self.assertRaises(ValueError):
                    validate_stage1(payload, self.text)

    def test_stage1_requires_arrays(self):
        for side in ('today_items', 'tomorrow_items'):
            payload = copy.deepcopy(self.first)
            payload['professions'][0][side] = 'not-array'
            with self.assertRaises(ValueError):
                validate_stage1(payload, self.text)

    def test_stage2_missing_extra_modified_reordered_ids(self):
        for change in ('missing', 'extra', 'modified', 'reordered'):
            payload = copy.deepcopy(self.second)
            rows = payload['today_items']
            if change == 'missing':
                rows.pop()
            elif change == 'extra':
                rows.append(copy.deepcopy(rows[0]))
            elif change == 'modified':
                rows[0]['id'] = 'T9'
            else:
                rows.reverse()
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_stage2(payload, self.first)

    def test_people_cannot_cross_ids_or_be_string(self):
        for people in ('徐超', ['米中玉'], None):
            payload = copy.deepcopy(self.second)
            payload['today_items'][0]['people'] = people
            with self.assertRaises(ValueError):
                validate_stage2(payload, self.first)

    def test_empty_content_rejected(self):
        payload = copy.deepcopy(self.second)
        payload['today_items'][0]['today'] = ''
        with self.assertRaises(ValueError):
            validate_stage2(payload, self.first)

    def test_explicit_values_preserved(self):
        payload = copy.deepcopy(self.second)
        payload['today_items'][0].update(today_hazard='动火作业', status='未完成', remark='保留')
        item = validate_stage2(payload, self.first)[0][0]
        self.assertEqual((item.today_hazard, item.status, item.remark), ('动火作业', '未完成', '保留'))

    def test_invalid_json_stops_before_stage2(self):
        with patch('ai_service._request_completion', return_value='{broken') as request:
            with self.assertRaisesRegex(ValueError, 'JSON'):
                extract_work(self.text, 'test-key')
            self.assertEqual(request.call_count, 1)

    def test_web_debug_discards_user_text(self):
        with patch.dict(os.environ, {'DAILY_REPORT_AI_DEBUG': '1'}), patch(
            'ai_service._request_completion', side_effect=[json.dumps(self.first), json.dumps(self.second)]
        ), patch('ai_service.LOGGER.debug') as log:
            extract_work(self.text, '徐超')
        log.assert_not_called()


if __name__ == '__main__':
    unittest.main()
