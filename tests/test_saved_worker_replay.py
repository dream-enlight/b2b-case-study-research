"""Saved-output replay, using synthetic and captured listing failure fixtures."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import runner,research,workspace
import test_efficiency as efficiency
import test_listing_arrival as arrival


class SavedWorkerReplayTests(unittest.TestCase):
    setUp=efficiency.EfficiencyTests.setUp
    tearDown=efficiency.EfficiencyTests.tearDown
    cmd=efficiency.EfficiencyTests.cmd
    state=efficiency.EfficiencyTests.state
    fixture=efficiency.EfficiencyTests.fixture
    record=efficiency.EfficiencyTests.record
    result=efficiency.EfficiencyTests.result
    setup_listing=arrival.ListingArrivalTests.setup_listing
    saved=arrival.ListingArrivalTests.saved

    def artifacts(self,base,state,cases,messages=(),result=None):
        key='review_batch_saved';log=base/'logs'/f'{key}_123456abcdef.jsonl'
        ctx={'target':state['company'],'task':'review_batch','approved_provider':cases[0]['provider'],
             'competing_product':runner.provider_scope(base,state,cases[0]['provider']),
             'review_cases':cases,'compact_receipts':False}
        runner.atomic_text(log,'\n'.join(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(m)}}) for m in messages)+'\n')
        runner.atomic_text(log.with_suffix('.prompt.txt'),'TASK ASSIGNMENT (machine generated):\n'+json.dumps(ctx))
        if result is not None:runner.atomic_json(log.with_suffix('.result.json'),result)
        state['phase']='stage2';state['jobs'][key]={'status':'paused','attempts':1,'error_kind':'validation','response_ready':False,'last_error':'Original exact failure'}
        runner.save(base,state)
        return key,log,ctx

    def source(self,case):return {'source_capture':{'url':case['url'],'coverage':'excerpt','text':'Saved published customer evidence for the approved workflow.'}}

    def test_valid_raw_final_is_revalidated_and_cached_without_codex(self):
        base,cases=self.fixture(1);state=self.state()
        key,log,ctx=self.artifacts(base,state,cases,[self.source(cases[0])],{'results':[self.result(cases[0])],'completed_ids':[]})
        original=log.with_suffix('.result.json').read_bytes()
        with patch.object(runner,'codex_call',side_effect=AssertionError('No paid reexecution')):
            result=runner.invoke(base,state,2,key,ctx,1,'FORBIDDEN')
        self.assertEqual(len(result['results']),1)
        self.assertEqual(state['jobs'][key]['attempts'],1)
        self.assertTrue(state['jobs'][key]['response_ready'])
        self.assertEqual(log.with_suffix('.result.json').read_bytes(),original)
        self.assertTrue((base/'results'/f'{key}.json').exists())
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)

    def test_malformed_final_does_not_discard_valid_stream_or_become_cache(self):
        base,cases=self.fixture(1);state=self.state()
        key,log,ctx=self.artifacts(base,state,cases,[self.source(cases[0]),{'case_result':self.result(cases[0])}])
        runner.atomic_text(log.with_suffix('.result.json'),'{broken')
        with patch.object(runner,'codex_call',side_effect=AssertionError('All cases already saved')):
            result=runner.invoke(base,state,2,key,ctx,1,'FORBIDDEN')
        self.assertEqual(result,{'results':[]})
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        self.assertFalse((base/'results'/f'{key}.json').exists())
        audit=runner.read_json(log.with_suffix('.replay.json'))
        self.assertFalse(audit['raw_final_reusable']);self.assertTrue(audit['errors'])

    def test_empty_customer_and_missing_source_evidence_remain_unfinished(self):
        for missing_customer in (False,True):
            with self.subTest(missing_customer=missing_customer):
                # Each variant gets an isolated temporary run.
                base,cases=self.fixture(1);state=self.state();row=self.result(cases[0])
                if missing_customer:row['record']['customer']=''
                source=[self.source(cases[0])] if missing_customer else []
                key,log,ctx=self.artifacts(base,state,cases,source,{'results':[row],'completed_ids':[]})
                self.assertIsNone(runner.replay_worker_output(base,state,key,ctx,2))
                self.assertFalse((base/'extracted.json').exists())
                self.assertFalse((base/'results'/f'{key}.json').exists())
                self.assertEqual(runner.coverage_plan(base,state)['cases'][0]['id'],cases[0]['id'])
                # Remove this synthetic run for the next independent variant.
                __import__('shutil').rmtree(base)

    def test_partial_recovery_schedules_only_the_unsupported_case(self):
        base,cases=self.fixture(2);state=self.state();bad=self.result(cases[1]);bad['record']['customer']=''
        key,log,ctx=self.artifacts(base,state,cases,[self.source(c) for c in cases],{'results':[self.result(cases[0]),bad],'completed_ids':[]})
        with patch.object(runner,'codex_call',side_effect=AssertionError('Local recovery only')):
            runner.recover_case_work(base,state)
        self.assertEqual(set(runner.read_json(base/'extracted.json')),{cases[0]['id']})
        self.assertEqual([c['id'] for c in runner.coverage_plan(base,state)['cases']],[cases[1]['id']])
        self.assertFalse((base/'results'/f'{key}.json').exists())

    def test_actual_sap_out_of_order_failure_replays_without_position_changes(self):
        base,state,ctx,messages=self.saved('sap');state['company']=ctx['target'];key='listing30_sap_saved'
        log=base/'logs'/f'{key}_123456abcdef.jsonl'
        runner.atomic_text(log.with_suffix('.prompt.txt'),'TASK ASSIGNMENT (machine generated):\n'+json.dumps(ctx))
        runner.atomic_text(log,'\n'.join(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(m)}}) for m in messages))
        state['jobs'][key]={'status':'paused','attempts':1,'error_kind':'validation','response_ready':False,
                            'last_error':'Listing positions must be a distinct consecutive prefix.'}
        expected=copy.deepcopy(next(m['discovered_case'] for m in messages if 'discovered_case' in m))
        with patch.object(runner,'provider_scope',return_value=ctx['competing_product']),patch.object(runner,'codex_call',side_effect=AssertionError('No SAP research')):
            runner.recover_case_work(base,state)
        entry=state['listing_universes']['Example Process']['entries'][0]
        self.assertEqual(entry['listing_position'],10)
        self.assertEqual(entry['url'],runner.norm_url(expected['url']))
        self.assertEqual(entry['customer'],expected['customer'])
        self.assertFalse(state['listing_universes']['Example Process']['complete'])
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        self.assertEqual(state['jobs'][key]['last_error'],'Listing positions must be a distinct consecutive prefix.')

    def test_changed_approved_scope_does_not_replay_old_research(self):
        base,cases=self.fixture(1);state=self.state()
        key,log,ctx=self.artifacts(base,state,cases,[self.source(cases[0])],{'results':[self.result(cases[0])],'completed_ids':[]})
        runner.atomic_json(base/'research/batches'/f'{key}.json',{'key':key,'cases':cases,'dataset_revision':None,'committed':False})
        landscape=runner.read_json(base/'landscape.json');landscape['competitors'][0]['product']='Different business line'
        runner.atomic_json(base/'landscape.json',landscape)
        self.assertIsNone(runner.replay_worker_output(base,state,key,ctx,2))
        self.assertFalse((base/'extracted.json').exists())

    def test_artifact_checksums_fail_closed(self):
        base,cases=self.fixture(1);state=self.state()
        key,log,ctx=self.artifacts(base,state,cases)
        runner.atomic_json(log.with_suffix('.execution.json'),{'assignment':ctx,'dataset_revision':None,'artifacts':{log.name:'wrong-checksum'}})
        with patch.object(runner,'codex_call',side_effect=AssertionError('No corruption bypass')):
            with self.assertRaisesRegex(runner.RunError,'checksum mismatch'):runner.invoke(base,state,2,key,ctx,1,'FORBIDDEN')

    def test_unchanged_memory_does_not_replace_index(self):
        base,cases=self.fixture(1);capture=self.source(cases[0])['source_capture']
        research.remember(base,runner.atomic_json,capture=capture,provider=cases[0]['provider'],origin='same')
        with patch.object(runner,'atomic_json',wraps=runner.atomic_json) as write:
            research.remember(base,runner.atomic_json,capture=capture,provider=cases[0]['provider'],origin='same')
        self.assertFalse(any(call.args[0].name=='memory.json' for call in write.call_args_list))

    def test_empty_customer_can_only_copy_explicit_assigned_source_identity(self):
        base,cases=self.fixture(1);state=self.state();row=self.result(cases[0]);row['record']['customer']=''
        source=self.source(cases[0]);source['source_capture']['text']='Customer: '+cases[0]['customer']+'\nPublished source identifies this exact customer.'
        key,log,ctx=self.artifacts(base,state,cases,[source],{'results':[row],'completed_ids':[]})
        original=log.with_suffix('.result.json').read_bytes()
        with patch.object(runner,'codex_call',side_effect=AssertionError('Explicit saved identity is sufficient')):
            result=runner.invoke(base,state,2,key,ctx,1,'FORBIDDEN')
        self.assertEqual(result['results'][0]['record']['customer'],cases[0]['customer'])
        self.assertEqual(log.with_suffix('.result.json').read_bytes(),original)
        self.assertEqual(runner.read_json(log.with_suffix('.replay.json'))['corrections'][0]['quote'],'Customer: '+cases[0]['customer'])

    def test_stream_failure_saves_raw_artifacts_and_exact_failure(self):
        base,cases=self.fixture(2);self.cmd('resume','test-company')
        self.cmd('run','test-company','--codex',efficiency.FAKE,'--max-tasks','1',env={'FAKE_MODE':'batch_empty_customer'})
        state=self.state();job=next(v for k,v in state['jobs'].items() if k.startswith('review_batch_'))
        metadata=runner.read_json(base/job['last_execution'])
        self.assertEqual(metadata['failure']['message'],'Complete extraction has empty essential fields')
        self.assertTrue((base/'logs'/metadata['events']).exists())
        self.assertTrue((base/'logs'/metadata['stderr']).exists())
        self.assertTrue(metadata['artifacts'])
        self.assertEqual(state['phase'],'paused_error')
        self.assertIn('case_result',(base/'logs'/metadata['events']).read_text())

    def test_final_validation_failure_preserves_raw_output_and_existing_receipts(self):
        base,cases=self.fixture(1);self.cmd('resume','test-company')
        self.cmd('run','test-company','--codex',efficiency.FAKE,'--max-tasks','1',env={'FAKE_MODE':'invalid_final_json'})
        state=self.state();key,job=next((k,v) for k,v in state['jobs'].items() if k.startswith('review_batch_'))
        metadata=runner.read_json(base/job['last_execution']);raw=base/'logs'/metadata['raw_output']
        self.assertEqual(raw.read_text(),'{broken')
        self.assertIn('final output is not valid JSON',metadata['failure']['message'])
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        with patch.object(runner,'codex_call',side_effect=AssertionError('Committed record must be reused')):
            runner.recover_case_work(base,state)
        self.assertEqual(raw.read_text(),'{broken')
        self.assertEqual(state['jobs'][key]['attempts'],1)

    def test_fresh_worker_is_requested_only_for_remaining_unsupported_case(self):
        base,cases=self.fixture(2);state=self.state();bad=self.result(cases[1]);bad['record']['customer']=''
        self.artifacts(base,state,cases,[self.source(c) for c in cases],{'results':[self.result(cases[0]),bad],'completed_ids':[]})
        runner.recover_case_work(base,state);remaining=runner.coverage_plan(base,state)['cases']
        self.assertEqual([c['id'] for c in remaining],[cases[1]['id']])
        ctx={'target':state['company'],'task':'review_batch','review_cases':remaining,'approved_provider':cases[1]['provider']}
        with patch.object(runner,'codex_call',return_value={'results':[]}) as worker:
            runner.invoke(base,state,2,'review_new_remaining',ctx,1,'SYNTHETIC')
        self.assertEqual([c['id'] for c in worker.call_args.args[4]['review_cases']],[cases[1]['id']])
        self.assertNotIn(cases[1]['id'],runner.read_json(base/'extracted.json'))

    def test_saved_linked_document_can_supply_readable_extraction_evidence(self):
        base,cases=self.fixture(1);state=self.state();case=cases[0];pdf='https://documents.test/full-case.pdf'
        key,log,ctx=self.artifacts(base,state,cases)
        ctx.pop('review_cases');ctx['assigned_cases']=cases;ctx['task']='extract_batch'
        runner.atomic_text(log.with_suffix('.prompt.txt'),'TASK ASSIGNMENT (machine generated):\n'+json.dumps(ctx))
        messages=[{'source_capture':{'url':case['url'],'coverage':'metadata','text':'Actual full-case link: '+pdf}},
                  {'source_captures':[{'url':pdf,'coverage':'full_text','text':'Published full-case evidence.'}],
                   'extracted_record':self.record(case)}]
        runner.atomic_text(log,'\n'.join(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(m)}}) for m in messages))
        with patch.object(runner,'codex_call',side_effect=AssertionError('Saved linked evidence is sufficient')):
            result=runner.invoke(base,state,3,key,ctx,1,'FORBIDDEN')
        self.assertEqual(result,{'records':[]})
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)

    def test_conflicting_customer_labels_are_not_repaired(self):
        base,cases=self.fixture(1);state=self.state();row=self.result(cases[0]);row['record']['customer']=''
        source=self.source(cases[0]);source['source_capture']['text']='Customer: '+cases[0]['customer']+'\nCustomer: Different customer'
        key,log,ctx=self.artifacts(base,state,cases,[source],{'results':[row],'completed_ids':[]})
        self.assertIsNone(runner.replay_worker_output(base,state,key,ctx,2))
        self.assertFalse((base/'extracted.json').exists())
        self.assertEqual(runner.read_json(log.with_suffix('.replay.json'))['corrections'],[])

    def test_known_invalid_cache_is_archived_before_genuine_missing_work(self):
        base,cases=self.fixture(1);state=self.state();bad=self.result(cases[0]);bad['record']['customer']=''
        key,log,ctx=self.artifacts(base,state,cases,[self.source(cases[0])],{'results':[bad],'completed_ids':[]})
        cache=base/'results'/f'{key}.json';runner.atomic_json(cache,{'results':[bad],'completed_ids':[]})
        original=cache.read_bytes();state['jobs'][key]['response_ready']=True
        with patch.object(runner,'codex_call',return_value={'results':[]}) as worker:
            runner.invoke(base,state,2,key,ctx,1,'SYNTHETIC')
        worker.assert_called_once()
        self.assertEqual(state['jobs'][key]['failure_history'][0]['message'],'Original exact failure')
        rejected=list((base/'results/rejected').glob('*.json'))
        self.assertEqual(len(rejected),1);self.assertEqual(rejected[0].read_bytes(),original)
        self.assertFalse((base/'extracted.json').exists())
