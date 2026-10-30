"""Read-only reports from synthetic and existing session artifacts."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
import usage_report


class UsageReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)/'run';self.base.mkdir()
        self.sessions=Path(self.tmp.name)/'sessions';self.sessions.mkdir()
    def tearDown(self):self.tmp.cleanup()
    def write(self,path,value):
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text('\n'.join(json.dumps(e) for e in value)+'\n')
    def worker(self,key='review_a',thread='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',provider='A',usage=None):
        log=self.base/'logs'/f'{key}_123456abcdef.jsonl'
        events=[{'type':'thread.started','thread_id':thread}]
        for _ in range(2):events.append({'type':'item.completed','item':{'type':'web_search','action':{'type':'open','url':'https://example.test/source'}}})
        if usage is not None:events.append({'type':'turn.completed','usage':usage})
        self.write(log,events)
        log.with_suffix('.prompt.txt').write_text('TASK ASSIGNMENT (machine generated):\n'+json.dumps({'task':'review_batch','approved_provider':provider}))
        return log
    def session(self,thread='aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'):
        def token(total,last):return {'type':'event_msg','payload':{'type':'token_count','info':{'total_token_usage':total,'last_token_usage':last}}}
        first={'input_tokens':100,'cached_input_tokens':0,'output_tokens':5}
        second={'input_tokens':150,'cached_input_tokens':90,'output_tokens':10}
        values=[{'type':'event_msg','payload':{'type':'task_started'}},token(first,first),token(first,first),
                token({'input_tokens':250,'cached_input_tokens':90,'output_tokens':15},second),
                {'type':'response_item','payload':{'type':'custom_tool_call','name':'exec','input':'text(" ");'}},
                {'type':'event_msg','payload':{'type':'task_started'}},token({'input_tokens':999,'cached_input_tokens':999,'output_tokens':999},first)]
        self.write(self.sessions/f'rollout-{thread}.jsonl',values)
    def test_cumulative_usage_peak_and_duplicate_observations_are_distinct(self):
        self.worker(usage={'input_tokens':250,'cached_input_tokens':90,'output_tokens':15});self.session()
        report=usage_report.build(self.base,self.sessions);worker=report['workers'][0]
        self.assertEqual(worker['session']['model_requests'],2)
        self.assertEqual(worker['usage']['input_tokens'],250)
        self.assertEqual(worker['session']['peak_request_input_tokens'],150)
        self.assertEqual(worker['session']['context_growth_tokens'],50)
        self.assertEqual(worker['session']['tools']['literal_print_noops'],1)
        self.assertEqual(worker['repeated_url_accesses'],{'https://example.test/source':2})
        self.assertEqual(worker['usage']['uncached_input_tokens'],160)
        self.assertIn('| --- |',usage_report.markdown(report))
    def test_missing_sessions_and_cached_counters_remain_unknown(self):
        self.worker(usage={'input_tokens':10,'output_tokens':2})
        report=usage_report.build(self.base,self.sessions/'absent');worker=report['workers'][0]
        self.assertIsNone(worker['session']['model_requests'])
        self.assertEqual(worker['session']['unavailable_reason'],'session directory missing')
        self.assertIsNone(worker['usage']['cached_input_tokens'])
        self.assertIsNone(worker['usage']['uncached_input_tokens'])
        self.assertEqual(report['aggregate']['run']['workers_missing_request_counts'],1)
    def test_absent_usage_is_not_reported_as_zero(self):
        self.worker()
        worker=usage_report.build(self.base,self.sessions)['workers'][0]
        self.assertTrue(all(v is None for v in worker['usage'].values()))
        self.assertIsNone(worker['elapsed_seconds'])
    def test_ambiguous_old_performance_attempts_are_not_allocated(self):
        self.worker()
        self.write(self.base/'performance.jsonl',[{'kind':'execution','key':'review_a','elapsed_seconds':s,'input_tokens':s} for s in (10,20)])
        worker=usage_report.build(self.base,self.sessions)['workers'][0]
        self.assertIsNone(worker['elapsed_seconds']);self.assertIsNone(worker['usage']['input_tokens'])
    def test_provider_and_task_totals_disclose_partial_measurement(self):
        self.worker(provider='A',usage={'input_tokens':250,'cached_input_tokens':90,'output_tokens':15});self.session()
        self.worker(key='review_b',thread='bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',provider='B',usage={'input_tokens':50,'cached_input_tokens':10,'output_tokens':3})
        report=usage_report.build(self.base,self.sessions)
        self.assertEqual(report['aggregate']['run']['input_tokens'],300)
        self.assertEqual(report['aggregate']['provider']['A']['input_tokens'],250)
        self.assertEqual(report['aggregate']['provider']['B']['input_tokens'],50)
        self.assertIsNone(report['aggregate']['run']['model_requests'])
        self.assertEqual(report['aggregate']['run']['measured_model_requests'],2)
    def test_partial_request_cache_counts_do_not_become_cumulative_totals(self):
        self.worker(usage={'input_tokens':250,'output_tokens':15});self.session()
        path=next(self.sessions.glob('*.jsonl'));rows=list(usage_report.events(path))
        for row in rows:
            info=row.get('payload',{}).get('info')
            if info and info['last_token_usage']['input_tokens']==100:info['last_token_usage'].pop('cached_input_tokens',None)
        self.write(path,rows)
        worker=usage_report.build(self.base,self.sessions)['workers'][0]
        self.assertIsNone(worker['usage']['cached_input_tokens'])
        self.assertIsNone(worker['usage']['uncached_input_tokens'])
        self.assertTrue(worker['session']['missing_usage_counters'])

    def test_missing_request_observation_does_not_invent_full_request_count_or_peak(self):
        self.worker();self.session();path=next(self.sessions.glob('*.jsonl'))
        rows=list(usage_report.events(path));rows.insert(1,{'type':'event_msg','payload':{'type':'token_count','info':None}})
        self.write(path,rows)
        report=usage_report.build(self.base,self.sessions);session=report['workers'][0]['session']
        self.assertIsNone(session['model_requests']);self.assertIsNone(session['peak_request_input_tokens'])
        self.assertEqual(session['observed_request_counters'],2)
        self.assertEqual(report['aggregate']['run']['measured_model_requests'],2)
        self.assertIsNone(report['workers'][0]['usage']['input_tokens'])

    def test_one_old_metric_for_multiple_attempts_is_not_attributed_twice(self):
        first=self.worker();second=first.with_name('review_a_654321fedcba.jsonl')
        self.write(second,list(usage_report.events(first)))
        point={'kind':'execution','key':'review_a','elapsed_seconds':10,'input_tokens':10}
        self.write(self.base/'performance.jsonl',[point])
        report=usage_report.build(self.base,self.sessions)
        self.assertTrue(all(w['elapsed_seconds'] is None for w in report['workers']))
        point['artifact']=first.name;self.write(self.base/'performance.jsonl',[point])
        report=usage_report.build(self.base,self.sessions)
        by_name={Path(w['artifact']).name:w for w in report['workers']}
        self.assertEqual(by_name[first.name]['elapsed_seconds'],10)
        self.assertIsNone(by_name[second.name]['elapsed_seconds'])
