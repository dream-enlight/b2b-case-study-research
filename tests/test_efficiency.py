import copy,json,unittest
from pathlib import Path
from unittest.mock import patch
import runner,research,workspace
import test_runner as legacy
FAKE=legacy.FAKE


class EfficiencyTests(unittest.TestCase):
    setUp=legacy.RunnerTests.setUp
    tearDown=legacy.RunnerTests.tearDown
    cmd=legacy.RunnerTests.cmd
    state=legacy.RunnerTests.state
    google=legacy.RunnerTests.google
    dispatch=legacy.RunnerTests.dispatch
    pump=legacy.RunnerTests.pump
    traced_assignments=legacy.RunnerTests.traced_assignments

    def fixture(self,n=5):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        base=runner.run_dir('test-company');s=self.state()
        s.update(phase='paused_error',paused_from='stage2',pause_reason='User paused research.',approved_providers=['Beta Software'])
        s['jobs']={'preserved':{'status':'complete','attempts':1}}
        runner.atomic_json(base/'landscape.json',{'competitors':[{'name':'Beta Software','product':'Beta Platform','reason':'Shared workflow','sources':['https://beta.example.com/product']}]})
        runner.atomic_json(base/'product_understanding.json',runner.validate_product({'summary':'Synthetic integration product.','core_workflow':'Connect workflows.',
            'capabilities':[{'name':'Integration','description':'Connect workflows.','sources':['https://example.com/product']}],
            'sources':['https://example.com/product'],'uncertainties':[]}))
        product=runner.provider_scope(base,s,'Beta Software');ledger={}
        for i in range(n):
            u=f'https://stories.example.com/acme/{i}';cid=runner.case_id('Beta Software',u)
            ledger[cid]={'id':cid,'provider':'Beta Software','url':u,'customer':f'Customer {i}','title':f'Story {i}',
                         'decision':'needs_review','reason':'Workflow unclear.','evidence':'Synthetic summary.','basis':'lightweight','competing_product':product}
        runner.atomic_json(runner.screening_path(base),ledger);runner.atomic_json(runner.inventory_path(base),{'Beta Software':[]})
        runner.atomic_json(runner.discovery_path(base),{'Beta Software':{'page':2,'cursor':'','seen_cursors':[''],'complete':True}})
        runner.save(base,s)
        self.assertEqual(self.cmd('upgrade-efficiency','test-company').returncode,0)
        return base,list(ledger.values())

    def record(self,c):
        return {'provider':c['provider'],'source_url':c['url'],'customer':c['customer'],'people':'Not established in the published case.',
                'company_profile':'Synthetic B2B application vendor.','buying_situation':'Manual reconciliation could not scale; the team required unified workflow measurement.',
                'status':'complete','note':''}

    def result(self,c):return {'id':c['id'],'decision':'relevant','reason':'Shared approved workflow.','evidence':'Synthetic source evidence.',
                              'record':self.record(c),'contribution':'A distinct customer and workflow.'}

    def test_upgrade_preserves_paused_state_scope_jobs_and_inventories(self):
        base,cases=self.fixture();s=self.state();before={p.name:p.read_bytes() for p in (runner.inventory_path(base),runner.discovery_path(base),base/'product_understanding.json')}
        self.assertEqual(s['phase'],'paused_error');self.assertEqual(s['paused_from'],'stage2')
        self.assertEqual(s['jobs'],{'preserved':{'status':'complete','attempts':1}})
        self.assertEqual(s['research_policy']['review_batch_size'],20)
        self.assertEqual(self.cmd('upgrade-efficiency','test-company').returncode,0)
        self.assertEqual(self.state(),s)
        self.assertTrue(all((base/n).read_bytes()==v for n,v in before.items()))
        self.assertTrue((Path(s['efficiency_backup'])/'run.zip').exists())

    def test_five_case_worker_checkpoints_each_case_and_filters_relevance(self):
        base,cases=self.fixture();self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        s=self.state();self.assertEqual(s['phase'],'stage2')
        records=runner.read_json(base/'extracted.json');self.assertEqual(len(records),3)
        ledger=runner.read_json(runner.screening_path(base));self.assertEqual([ledger[c['id']]['decision'] for c in cases],['relevant','relevant','relevant','excluded','unresolved'])
        self.assertEqual(len(s['case_checkpoints']),5)
        a=self.traced_assignments(trace)[0];self.assertEqual(len(a['review_cases']),5)
        self.assertIn('target_scope',a);self.assertIn('competing_products',a)
        before=(base/'extracted.json').read_bytes()
        runner.recover_case_work(base,s);runner.recover_case_work(base,s)
        self.assertEqual((base/'extracted.json').read_bytes(),before)
        self.assertTrue(all(p['committed'] for p in map(runner.read_json,(base/'research/cases').rglob('*.json'))))

    def test_default_twenty_case_batch_saves_eighteen_relevant_and_two_decisions(self):
        base,cases=self.fixture(25);self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        self.assertEqual(len(self.traced_assignments(trace)[0]['review_cases']),20)
        self.assertEqual(len(self.state()['case_checkpoints']),20)
        self.assertEqual(len(runner.read_json(base/'extracted.json')),18)
        plan=runner.coverage_plan(base,self.state());self.assertEqual(len(plan['cases']),5)
        self.assertTrue(all(c['id'] not in self.state()['case_checkpoints'] for c in plan['cases']))

    def test_twenty_case_interruption_resumes_eighteen_unfinished_and_config_is_explicit(self):
        base,cases=self.fixture(20);self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'batch_interrupt','FAKE_TRACE':str(trace)})
        self.assertEqual(len(runner.read_json(base/'extracted.json')),2)
        self.assertEqual(len(runner.coverage_plan(base,self.state())['cases']),18)
        self.assertEqual(self.state()['research_policy']['review_batch_size'],20)
        self.assertNotEqual(self.cmd('configure-research','test-company','--review-batch-size','7').returncode,0)
        self.assertEqual(self.cmd('configure-research','test-company','--review-batch-size','7','--reason','Synthetic test: measured response-size constraint.').returncode,0)
        self.assertEqual(self.state()['research_policy']['review_batch_size'],7)
        self.assertEqual(len(runner.coverage_plan(base,self.state())['cases']),7)
        self.assertEqual(runner.efficient_schema('review_batch',7)['properties']['results']['maxItems'],7)
        self.assertEqual(runner.efficient_schema('review_batch')['properties']['results']['maxItems'],20)
        self.assertEqual(self.state()['phase'],'paused_quota')

    def test_interrupted_batch_preserves_two_cases_and_never_reassigns_them(self):
        base,cases=self.fixture();self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'batch_interrupt','FAKE_TRACE':str(trace)})
        self.assertEqual(self.state()['phase'],'paused_quota')
        saved=runner.read_json(base/'extracted.json');self.assertEqual(set(saved),{c['id'] for c in cases[:2]})
        self.cmd('resume','test-company','--confirm-reset')
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        assignments=self.traced_assignments(trace)
        batches=[a['review_cases'] for a in assignments if a.get('task')=='review_batch']
        self.assertEqual([len(b) for b in batches],[5,3])
        self.assertTrue(all(c['id'] not in saved for c in batches[1]))
        self.assertTrue(all(runner.read_json(base/'extracted.json')[k]==v for k,v in saved.items()))
        self.assertEqual(len(self.cells),3);self.assertEqual(len(set(self.state()['workspace_verified_ids'])),3)

    def test_invalid_case_does_not_erase_previous_case_in_same_batch(self):
        base,cases=self.fixture();self.cmd('resume','test-company')
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'batch_wrong_identity'})
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(set(runner.read_json(base/'extracted.json')),{cases[0]['id']})
        self.assertIn('identity',self.state()['pause_reason'])

    def test_adjacent_json_checkpoints_stream_before_interruption(self):
        base,cases=self.fixture();self.cmd('resume','test-company')
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'combined_interrupt'})
        self.assertEqual(self.state()['phase'],'paused_quota')
        self.assertEqual(set(runner.read_json(base/'extracted.json')),{c['id'] for c in cases[:2]})
        self.assertEqual(len(runner.coverage_plan(base,self.state())['cases']),3)

    def test_recover_adjacent_checkpoint_envelopes_from_saved_logs_without_reading(self):
        base,cases=self.fixture();s=self.state();key='review_batch_synthetic'
        assignment=base/'research/batches'/f'{key}.json'
        runner.atomic_json(assignment,{'key':key,'cases':cases,'dataset_revision':s.get('dataset_revision'),'committed':False})
        text=json.dumps({'source_capture':{'url':cases[0]['url'],'coverage':'excerpt','text':'Saved published evidence.'}})+'\n'+json.dumps({'case_result':self.result(cases[0])})
        runner.atomic_text(base/'logs'/f'{key}_test.jsonl',json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}})+'\n')
        with patch.object(runner,'codex_call',side_effect=AssertionError('No source reading')):
            runner.recover_case_work(base,s);runner.recover_case_work(base,s)
        self.assertEqual(set(runner.read_json(base/'extracted.json')),{cases[0]['id']})
        self.assertEqual(research.context(base,[cases[0]])['sources'][cases[0]['url']]['coverage'],'excerpt')
        self.assertEqual(list(runner.checkpoint_messages('Ordinary prose')),[])

    def test_case_receipt_recovers_crash_before_record_commit_without_worker(self):
        base,cases=self.fixture();s=self.state();row=self.result(cases[0])
        with patch.object(runner,'persist_records',side_effect=OSError('Synthetic crash after receipt')):
            with self.assertRaises(OSError):runner.commit_case_result(base,s,'synthetic_batch',cases,row)
        receipt=runner.case_receipt_path(base,s,cases[0]['id']);self.assertFalse(runner.read_json(receipt)['committed'])
        with patch.object(runner,'codex_call',side_effect=AssertionError('No research')):runner.recover_case_work(base,self.state())
        self.assertTrue(runner.read_json(receipt)['committed']);self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        row['record']['buying_situation']='Conflicting change'
        with self.assertRaises(runner.RunError):runner.commit_case_result(base,self.state(),'synthetic_batch',cases,row)

    def discovery_fixture(self):
        base,cases=self.fixture(1)
        runner.atomic_json(runner.screening_path(base),{})
        return base,cases

    def discovery_item(self,c):
        row=self.result(c);row.pop('id')
        return dict(row,url=c['url'],customer=c['customer'],title=c['title'],reading_depth='substantive')

    def test_shared_testimonial_url_reuses_verified_source_and_audits_second_customer(self):
        base,cases=self.discovery_fixture();s=self.state();c=cases[0];key='inventory_shared'
        ctx={'approved_provider':c['provider'],'max_cases':100,'competing_product':c['competing_product']}
        first=self.discovery_item(c)
        runner.commit_worker_message(base,s,key,ctx,{'discovered_case':first},'synthetic.jsonl')
        receipt=runner.case_receipt_path(base,s,c['id']);before=receipt.read_bytes();records=(base/'extracted.json').read_bytes()
        second=copy.deepcopy(first);second.update(customer='Second Customer',title='Second testimonial')
        second['record'].update(customer='Second Customer',buying_situation='Needed delegated sales actions.')
        second.update(reason='Sales actions.',evidence='Second published testimonial.')
        with patch.object(runner,'codex_call',side_effect=AssertionError('No repeated case reading')):
            runner.commit_worker_message(base,s,key,ctx,{'discovered_case':second},'synthetic.jsonl')
            runner.commit_discovered_case(base,s,key,ctx,first)
            runner.commit_discovered_case(base,s,key,ctx,second)
            runner.commit_discovered_case(base,s,'resumed_inventory',ctx,second)
        self.assertEqual(receipt.read_bytes(),before);self.assertEqual((base/'extracted.json').read_bytes(),records)
        audits=list((base/'research/discovery_collisions').rglob('*.json'));self.assertEqual(len(audits),1)
        self.assertEqual(runner.read_json(audits[0])['attempted'],second)
        self.assertFalse(runner.coverage_plan(base,s).get('cases'))
        # Neither changed review evidence nor an out-of-assignment emission is
        # authorized by the discovery-only reuse guard.
        changed=self.result(c);changed['record']['customer']='Second Customer'
        with self.assertRaisesRegex(runner.RunError,'immutable'):runner.commit_case_result(base,s,key,[c],changed)
        with self.assertRaisesRegex(runner.RunError,'identity'):runner.commit_case_result(base,s,key,[],self.result(c))
        with self.assertRaisesRegex(runner.RunError,'identity'):
            runner.commit_worker_message(base,s,key,{'assigned_cases':[]},{'extracted_record':self.record(c)},'synthetic.jsonl')
        with self.assertRaisesRegex(runner.RunError,'immutable'):runner.persist_records(base,[c],[changed['record']])
        wrong_source=copy.deepcopy(second);wrong_source['record']['source_url']='https://unassigned.example.com/'
        with self.assertRaisesRegex(runner.RunError,'provider\\+URL'):
            runner.commit_discovered_case(base,s,key,ctx,wrong_source)
        self.assertEqual(len(list((base/'research/discovery_collisions').rglob('*.json'))),1)

    def test_discovery_duplicate_requires_authoritative_complete_extraction(self):
        base,cases=self.discovery_fixture();s=self.state();c=cases[0]
        ctx={'approved_provider':c['provider'],'max_cases':100,'competing_product':c['competing_product']}
        first=self.discovery_item(c);runner.commit_discovered_case(base,s,'inventory_shared',ctx,first)
        receipt=runner.case_receipt_path(base,s,c['id']);before=receipt.read_bytes()
        records=runner.read_json(base/'extracted.json');records[c['id']]['buying_situation']='Conflicting saved evidence'
        runner.atomic_json(base/'extracted.json',records)
        with self.assertRaisesRegex(runner.RunError,'extraction mismatch'):
            runner.commit_discovered_case(base,s,'inventory_shared',ctx,first)
        self.assertEqual(receipt.read_bytes(),before)
        self.assertFalse((base/'research/discovery_collisions').exists())

    def test_discovery_duplicate_recovers_uncommitted_receipt_without_reading(self):
        base,cases=self.discovery_fixture();s=self.state();c=cases[0]
        ctx={'approved_provider':c['provider'],'max_cases':100,'competing_product':c['competing_product']}
        first=self.discovery_item(c)
        with patch.object(runner,'persist_records',side_effect=OSError('Crash before extraction')):
            with self.assertRaises(OSError):runner.commit_discovered_case(base,s,'inventory_shared',ctx,first)
        runner.commit_discovered_case(base,s,'inventory_shared',ctx,first)
        self.assertTrue(runner.read_json(runner.case_receipt_path(base,s,c['id']))['committed'])
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)

    def test_discovery_completed_source_is_known_and_not_reviewed_or_extracted_again(self):
        base,cases=self.discovery_fixture();s=self.state();c=cases[0]
        ctx={'approved_provider':c['provider'],'max_cases':100,'competing_product':c['competing_product']}
        runner.commit_discovered_case(base,s,'inventory_shared',ctx,self.discovery_item(c))
        runner.atomic_json(runner.discovery_path(base),{c['provider']:{'page':1,'cursor':'','seen_cursors':[],'complete':False}})
        captured=[]
        def invoke(*args):
            captured.append(args[4]);return {'cases':[], 'has_more':False,'next_cursor':''}
        with patch.object(runner,'invoke',side_effect=invoke),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,s,60,FAKE)
        self.assertEqual(captured[0]['task'],'discover');self.assertIn(c['url'],captured[0]['known_case_urls'])
        with patch.object(workspace,'ensure_sync',return_value=True):runner.discovery_step(base,s,60,FAKE)
        self.assertEqual(s['phase'],'stage3')
        with patch.object(runner,'invoke',side_effect=AssertionError('No repeated extraction')),patch.object(workspace,'ensure_sync',return_value=True):
            runner.step(base,s,60,FAKE)
        self.assertEqual(s['phase'],'finalize_sheet')

    def test_committed_active_record_repairs_missing_inventory_metadata_without_reading(self):
        base,cases=self.fixture(1);s=self.state();c=cases[0]
        runner.commit_case_result(base,s,'saved-case',cases,self.result(c))
        records=(base/'extracted.json').read_bytes()
        runner.atomic_json(runner.screening_path(base),{})
        runner.atomic_json(runner.inventory_path(base),{c['provider']:[]})
        with patch.object(runner,'codex_call',side_effect=AssertionError('No repeated research')):
            runner.recover_case_work(base,s);runner.recover_case_work(base,s)
        self.assertEqual((base/'extracted.json').read_bytes(),records)
        self.assertEqual(runner.read_json(runner.screening_path(base))[c['id']]['decision'],'relevant')
        self.assertEqual([x['id'] for x in runner.read_json(runner.inventory_path(base))[c['provider']]],[c['id']])
        # An archived/removed record must not be resurrected from an old receipt.
        runner.atomic_json(base/'extracted.json',{});runner.atomic_json(runner.screening_path(base),{})
        runner.recover_case_work(base,s)
        self.assertEqual(runner.read_json(base/'extracted.json'),{})
        self.assertEqual(runner.read_json(runner.screening_path(base)),{})

    def test_unpublished_scope_correction_with_existing_sheet_preserves_remote_identity(self):
        base,cases=self.fixture(1);s=self.state();c=cases[0]
        runner.commit_case_result(base,s,'saved',cases,self.result(c))
        s.update(workspace_sheet={'id':'offline-sheet','url':'https://docs.google.com/spreadsheets/d/offline-sheet/edit','tab':'Case studies','sheet_id':7,'row_count':1000},workspace_header_verified=True,workspace_verified_ids=[])
        workspace.ensure_sync(base,s,runner.ordered_records(base),runner.atomic_json);runner.save(base,s)
        request=s['workspace_pending'];self.assertEqual(request['kind'],'sheet_preflight')
        result=self.cmd('exclude-case','test-company','--case-id',c['id'],'--reason','Synthetic career profile is not a customer case.')
        self.assertEqual(result.returncode,0,result.stderr);after=self.state()
        self.assertEqual(after['workspace_sheet'],s['workspace_sheet']);self.assertEqual(after['phase'],s['phase'])
        self.assertNotIn('workspace_pending',after);self.assertEqual(after['workspace_verified_ids'],[])
        history=runner.read_json(base/'history'/f'exclude_case_{c["id"]}.json')
        self.assertEqual(history['withdrawn_workspace_request'],request)
        self.assertEqual(history['record']['id'],c['id'])
        runner.recover_case_work(base,after);self.assertNotIn(c['id'],runner.read_json(base/'extracted.json'))

    def test_scope_correction_rejects_verified_or_possibly_written_rows(self):
        base,cases=self.fixture(1);s=self.state();c=cases[0]
        runner.commit_case_result(base,s,'saved',cases,self.result(c))
        for pending,verified in [(None,[c['id']]),({'kind':'sheet_write','status':'dispatched'},[]),({'kind':'sheet_verify','status':'ready'},[])]:
            s['workspace_verified_ids']=verified
            if pending:s['workspace_pending']=pending
            else:s.pop('workspace_pending',None)
            runner.save(base,s);before=runner.read_state(base)
            result=self.cmd('exclude-case','test-company','--case-id',c['id'],'--reason','Synthetic wrong source.')
            self.assertNotEqual(result.returncode,0);self.assertEqual(self.state(),before)

    def test_old_revision_case_receipt_cannot_resurrect_excluded_evidence(self):
        base,cases=self.fixture();s=self.state()
        with patch.object(runner,'persist_records',side_effect=OSError('Crash before applying old revision')):
            with self.assertRaises(OSError):runner.commit_case_result(base,s,'old_batch',cases,self.result(cases[0]))
        s['dataset_revision']='revised-universe';runner.save(base,s)
        runner.recover_case_work(base,s)
        self.assertFalse((base/'extracted.json').exists())
        self.assertEqual(runner.read_json(runner.screening_path(base))[cases[0]['id']]['decision'],'needs_review')

    def test_full_grid_publication_check_rejects_a_distant_duplicate(self):
        base,cases=self.fixture(2);runner.persist_records(base,cases,[self.record(c) for c in cases])
        for _ in range(20):
            self.cmd('publish-saved','test-company');s=self.state();p=s.get('workspace_pending')
            if p and p['kind']=='sheet_saved_verify':
                self.cells[600]=workspace.rows_for([self.record(cases[0])])[0];break
            if p:self.assertEqual(self.dispatch(p).returncode,0)
        for _ in range(10):
            p=self.state().get('workspace_pending')
            if p:
                result=self.dispatch(p)
                if result.returncode:
                    self.assertIn('unexpected rows',self.state()['pause_reason']);break
            self.cmd('publish-saved','test-company')
        else:self.fail('Distant duplicate was not detected')
        self.assertFalse(self.state().get('workspace_saved_verification'))

    def test_evidence_and_known_failures_survive_fresh_contexts(self):
        base,cases=self.fixture();c=cases[0]
        research.remember(base,runner.atomic_json,capture={'url':c['url'],'coverage':'excerpt','text':'Reusable published source evidence.'},provider=c['provider'])
        research.remember(base,runner.atomic_json,event={'item':{'type':'mcp_tool_call','result':{'content':[{'type':'text','text':'Browser is not available: iab'}]}}})
        research.remember(base,runner.atomic_json,event={'item':{'type':'command_execution','aggregated_output':'urlopen error: DNS unavailable'}})
        research.remember(base,runner.atomic_json,capture={'url':'https://stories.example.com/failed.pdf','coverage':'failed','text':'First PDF attempt failed.'})
        memory=research.context(base,[c,{'url':'https://stories.example.com/failed.pdf'}])
        self.assertEqual(memory['sources'][c['url']]['text'],'Reusable published source evidence.')
        self.assertIn('browser',memory['known_tool_failures']);self.assertIn('shell_network',memory['known_tool_failures'])
        self.assertIn('access_failure',memory['sources']['https://stories.example.com/failed.pdf'])
        self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        call=json.loads(trace.read_text().splitlines()[0]);a=self.traced_assignments(trace)[0]
        self.assertEqual(a['evidence_memory']['sources'][c['url']]['text'],'Reusable published source evidence.')
        self.assertIn('--ignore-user-config',call['args']);self.assertIn('features.shell_tool=false',call['args'])
        self.assertIn('features.apps=false',call['args']);self.assertNotEqual(call['cwd'],str(runner.ROOT))
        self.assertNotIn('Refold_case_study_database.xlsx',call['prompt'])

    def test_old_access_failures_survive_the_short_window_and_provider_changes(self):
        base,cases=self.fixture(1);provider=cases[0]['provider'];url='https://stories.example.com/old-failed.pdf'
        research.remember(base,runner.atomic_json,capture={'url':url,'coverage':'failed','text':'First PDF attempt unreadable; never retry.'},provider='Another provider in an earlier mixed task')
        for i in range(12):
            research.remember(base,runner.atomic_json,capture={'url':f'https://stories.example.com/new/{i}','coverage':'excerpt','text':'Newer usable evidence.'},provider=provider)
        memory=research.context(base,provider=provider)
        self.assertNotIn(url,memory['sources'])
        self.assertIn(url,memory['known_access_failures'])
        self.assertIn('never retry',memory['known_access_failures'][url])

    def test_collection_rotates_without_volume_or_saturation_priority(self):
        base,cases=self.fixture(25);s=self.state();s['approved_providers']=['Heavy','Beta Software','New Competitor']
        records={str(i):dict(self.record(cases[0]),provider='Heavy',customer=f'Heavy {i}') for i in range(15)}
        inventory={'Heavy':[],'Beta Software':[]};ledger={c['id']:c for c in cases};progress={'Heavy':{'complete':False},'Beta Software':{'complete':True}}
        p=research.plan(s,inventory,ledger,records,progress);self.assertEqual(p['provider'],'Heavy');self.assertEqual(p['action'],'discover')
        s['coverage_turns']={'Heavy':1}
        p=research.plan(s,inventory,ledger,records,progress);self.assertEqual(p['provider'],'Beta Software');self.assertEqual(len(p['cases']),20)
        records.update({c['id']:self.record(c) for c in cases[:20]})
        s['coverage_turns']['Beta Software']=2
        p=research.plan(s,inventory,ledger,records,progress);self.assertEqual(p['provider'],'New Competitor');self.assertEqual(p['action'],'discover')
        inventory['New Competitor']=[];progress['New Competitor']={'complete':True}
        # All remaining Beta cases stay eligible despite its larger completed set.
        progress['Heavy']={'complete':True}
        p=research.plan(s,inventory,ledger,records,progress);self.assertEqual(p['provider'],'Beta Software');self.assertEqual(len(p['cases']),5)
        self.assertEqual(sum(r['complete_records'] for r in p['coverage']),35)
        records.update({c['id']:self.record(c) for c in cases[20:]})
        progress['Heavy']={'complete':False}
        self.assertEqual(research.plan(s,inventory,ledger,records,progress)['provider'],'Heavy')

    def test_heavy_provider_and_repeated_customer_remain_in_full_batch(self):
        base,cases=self.fixture(25);s=self.state();s['approved_providers']=['Beta Software','Gamma']
        for c in cases:c['customer']='Repeated Customer'
        gamma=dict(cases[0],id='gamma-case',provider='Gamma',url='https://gamma.example.com/case')
        ledger={c['id']:c for c in cases+[gamma]}
        records={str(i):dict(self.record(cases[0]),customer=f'Prior {i}') for i in range(100)}
        progress={'Beta Software':{'complete':True},'Gamma':{'complete':True}}
        inventory={'Beta Software':[],'Gamma':[]}
        p=research.plan(s,inventory,ledger,records,progress)
        self.assertEqual(p['provider'],'Beta Software');self.assertEqual(len(p['cases']),20)
        self.assertEqual(sum(c['provider']=='Beta Software' for c in p['cases']),19)
        self.assertIn(gamma,p['cases'])
        records.update({c['id']:self.record(c) for c in p['cases']})
        p=research.plan(s,inventory,ledger,records,progress);self.assertEqual(len(p['cases']),6)
        self.assertEqual(p['coverage'][0]['screening_counts']['needs_review'],25)
        records.update({c['id']:self.record(c) for c in p['cases']})
        self.assertEqual(research.plan(s,inventory,ledger,records,progress)['action'],'done')

    def test_analysis_prompts_separate_frequency_from_descriptive_judgment(self):
        for stage in (4,5,6,7):
            prompt=runner.prompt_for(stage,{})
            self.assertIn('provider concentration',prompt)
            self.assertIn('descriptive',prompt.casefold())
            self.assertIn('do not recommend',prompt.casefold())
            self.assertIn('evidence',prompt.casefold())
        prompt=runner.prompt_for(2,{'efficient_worker':True,'task':'discover'})
        self.assertIn('never total-case limits',prompt)
        self.assertIn('thematic',prompt)

    def test_legacy_inventory_without_exhaustion_checkpoint_is_extended_not_reset(self):
        base,cases=self.fixture(2);s=self.state()
        runner.persist_records(base,cases,[self.record(c) for c in cases])
        records=(base/'extracted.json').read_bytes()
        runner.atomic_json(runner.inventory_path(base),{'Beta Software':cases})
        runner.discovery_path(base).unlink()
        with patch.object(runner,'codex_call',side_effect=AssertionError('No reading before saved-record sync')):
            runner.discovery_step(base,s,60,FAKE)
        self.assertEqual((base/'extracted.json').read_bytes(),records)
        self.assertEqual(runner.read_json(runner.inventory_path(base))['Beta Software'],cases)
        progress=runner.read_json(runner.discovery_path(base))['Beta Software']
        self.assertFalse(progress['complete']);self.assertIn('do not reopen',progress['cursor'])
        self.assertEqual(runner.coverage_plan(base,s)['action'],'discover')

    def test_partial_landing_read_stays_pending_without_false_completed_receipt(self):
        base,cases=self.fixture(1);s=self.state();c=cases[0]
        runner.atomic_json(runner.screening_path(base),{})
        context={'approved_provider':c['provider'],'max_cases':20,'competing_product':c['competing_product']}
        item={k:c[k] for k in ('url','customer','title')}
        item.update(decision='needs_review',reason='Full PDF not yet attempted; landing excerpt does not establish product.',evidence='Saved landing excerpt.',record=None,reading_depth='substantive',contribution='Scope unconfirmed.')
        runner.commit_discovered_case(base,s,'partial-discovery',context,item)
        self.assertFalse(runner.case_receipt_path(base,s,c['id']).exists())
        self.assertEqual(runner.coverage_plan(base,s)['cases'][0]['id'],c['id'])
        self.assertEqual(runner.read_json(runner.screening_path(base))[c['id']]['basis'],'partial')
        runner.commit_case_result(base,s,'review',[c],self.result(c))
        runner.commit_discovered_case(base,s,'partial-discovery',context,item)
        self.assertEqual(runner.read_json(runner.screening_path(base))[c['id']]['decision'],'relevant')

    def test_failed_discovery_access_persists_unresolved_and_is_not_reassigned(self):
        self.modern=True
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'unresolved_discovery'})
        base=runner.run_dir('test-company');s=self.state()
        self.assertEqual(s['phase'],'stage2')
        self.assertEqual(list(runner.read_json(runner.screening_path(base)).values())[0]['decision'],'unresolved')
        self.assertEqual(runner.coverage_plan(base,s)['cases'],[])
        self.assertIn('unresolved',runner.efficient_schema('discover')['properties']['cases']['items']['properties']['decision']['enum'])

    def test_explicit_exhaustion_notes_are_preserved_but_remaining_paths_reject(self):
        for mode,phase in [('completed_structured_cursor','stage2'),('conflicting_structured_cursor','paused_error')]:
            with self.subTest(mode=mode):
                self.modern=True;name='Done' if phase=='stage2' else 'Conflict';rid=name.lower()
                self.cmd('app',f'Research {name} — https://example.com','--codex',FAKE)
                # Historical exhaustive-cursor compatibility, not the new
                # first-30 listing protocol (which requires an empty end cursor).
                base=runner.run_dir(rid);old=self.state(rid);old['research_policy'].pop('first_listing_entries',None);runner.save(base,old)
                self.cmd('app','Approve these competitors: Beta Software','--id',rid,'--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':mode})
                s=self.state(rid);base=runner.run_dir(rid);self.assertEqual(s['phase'],phase)
                notes=list((base/'research/discovery_completion_notes').glob('*.json'))
                self.assertEqual(bool(notes),phase=='stage2')
                if notes:self.assertIn('exhausted',runner.read_json(notes[0])['reported_next_cursor'])

    def test_post_response_validation_reuses_cache_but_partial_worker_does_not(self):
        base,cases=self.fixture(1);s=self.state();key='saved-response'
        s['jobs'][key]={'status':'paused','attempts':1,'error_kind':'validation','response_ready':True}
        runner.atomic_json(base/'results'/f'{key}.json',{'cases':[]})
        with patch.object(runner,'codex_call',side_effect=AssertionError('No repeated execution')):
            self.assertEqual(runner.invoke(base,s,2,key,{},60,FAKE),{'cases':[]})
        self.assertEqual(s['jobs'][key]['attempts'],1)
        self.assertEqual(s['jobs'][key]['response_replays'],1)
        s['jobs'][key].update(status='paused',response_ready=False)
        with patch.object(runner,'codex_call',return_value={'cases':[]}) as worker:
            runner.invoke(base,s,2,key,{},60,FAKE)
        self.assertEqual(worker.call_count,1);self.assertEqual(s['jobs'][key]['attempts'],2)

    def test_progressive_batch_combines_uncovered_providers_to_fill_twenty(self):
        base,cases=self.fixture(8);s=self.state();s['approved_providers']=['Beta Software','Gamma Software','Heavy']
        gamma=[]
        for i in range(25):
            c=dict(cases[0],provider='Gamma Software',customer=f'Gamma {i}',url=f'https://gamma.example.com/{i}')
            c['id']=runner.case_id(c['provider'],c['url']);gamma.append(c)
        ledger={c['id']:c for c in cases+gamma};records={'heavy':dict(self.record(cases[0]),provider='Heavy')}
        p=research.plan(s,{'Beta Software':[],'Gamma Software':[],'Heavy':[]},ledger,records,
                        {'Beta Software':{'complete':True},'Gamma Software':{'complete':True},'Heavy':{'complete':False}})
        self.assertEqual(len(p['cases']),20)
        self.assertEqual(sum(c['provider']=='Beta Software' for c in p['cases']),8)
        self.assertEqual(sum(c['provider']=='Gamma Software' for c in p['cases']),12)
        self.assertEqual([c['provider'] for c in p['cases'][:4]],['Beta Software','Gamma Software']*2)

    def test_substantive_discovery_saves_record_immediately_and_skips_review(self):
        self.modern=True
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        trace=Path(self.tmp.name)/'trace'
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'substantive_discovery','FAKE_TRACE':str(trace)})
        base=runner.run_dir('test-company');records=runner.read_json(base/'extracted.json');self.assertEqual(len(records),1)
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        self.assertTrue(all(c['id'] not in records for a in self.traced_assignments(trace) for c in a.get('review_cases',[])))
        self.assertEqual(len(self.state()['workspace_verified_ids']),2)

    def test_streamed_discovery_inventory_survives_empty_final_array(self):
        self.modern=True
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'stream_only_discovery'})
        base=runner.run_dir('test-company');records=runner.read_json(base/'extracted.json')
        inventoried={c['id'] for cases in runner.read_json(runner.inventory_path(base)).values() for c in cases}
        self.assertEqual(len(records),1);self.assertEqual(inventoried,set(records))

    def test_provider_collection_status_reaches_finalized_analysis_database(self):
        base,cases=self.fixture(2);self.cmd('resume','test-company')
        self.pump(until=lambda s:s['phase']=='stage4')
        database=workspace.frozen_database(base,self.state())
        rows=database['screening_summary']['providers']
        self.assertEqual(len(rows),1);self.assertTrue(rows[0]['inventory_complete'])
        self.assertEqual(rows[0]['complete_records'],2)
        self.assertEqual(rows[0]['screening_counts']['relevant'],2)

    def test_case_evidence_notes_survive_finalization_without_changing_sheet_rows(self):
        base,cases=self.fixture(2);s=self.state()
        for c in cases:
            result=self.result(c);result['record']['note']='Source reports a planned adoption, not verified outcomes.'
            runner.commit_case_result(base,s,'saved-source',cases,result)
        expected=workspace.rows_for(runner.ordered_records(base))
        self.cmd('resume','test-company');self.pump(until=lambda s:s['phase']=='stage4')
        database=workspace.frozen_database(base,self.state())
        self.assertEqual(database['rows'],expected)
        self.assertEqual(len(database['case_notes']),2)
        self.assertIn('planned adoption',database['case_notes'][cases[0]['id']])

    def test_publication_only_syncs_55_records_and_full_grid_without_research(self):
        base,cases=self.fixture(55)
        runner.persist_records(base,cases,[self.record(c) for c in cases]);before=(base/'extracted.json').read_bytes();jobs=copy.deepcopy(self.state()['jobs'])
        for _ in range(40):
            result=self.cmd('publish-saved','test-company');self.assertEqual(result.returncode,0,result.stderr)
            s=self.state()
            if s.get('workspace_pending'):self.assertEqual(self.dispatch(s['workspace_pending']).returncode,0)
            elif s.get('workspace_saved_verification'):break
        else:self.fail('Publication-only verification did not finish')
        self.assertEqual(self.state()['phase'],'paused_error');self.assertEqual(self.state()['jobs'],jobs)
        self.assertEqual((base/'extracted.json').read_bytes(),before)
        self.assertEqual(self.state()['workspace_saved_verification']['count'],55)
        self.assertEqual(len(set(self.state()['workspace_verified_ids'])),55);self.assertEqual(len(self.cells),55)
        self.assertEqual(self.write_count,3);sheet=self.state()['workspace_sheet']
        self.assertIn('55 rows',self.cmd('publish-saved','test-company').stdout)
        self.assertEqual(self.write_count,3);self.assertEqual(self.state()['workspace_sheet'],sheet)

    def test_stage3_streamed_records_survive_failure_and_resume_without_reassignment(self):
        base,cases=self.fixture();s=self.state();s.update(phase='stage3');s.pop('paused_from',None)
        runner.atomic_json(base/'batches.json',runner.compile_batches({'Beta Software':cases}));runner.save(base,s)
        self.pump(until=lambda s:len(s.get('workspace_verified_ids',[]))==0 and s.get('workspace_header_verified'))
        trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'extract_interrupt','FAKE_TRACE':str(trace)})
        saved=runner.read_json(base/'extracted.json');self.assertEqual(len(saved),2)
        self.assertEqual(self.state()['phase'],'paused_quota');self.cmd('resume','test-company','--confirm-reset')
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        batches=[a['assigned_cases'] for a in self.traced_assignments(trace) if 'assigned_cases' in a]
        self.assertEqual([len(b) for b in batches],[5,3]);self.assertTrue(all(c['id'] not in saved for c in batches[1]))
        self.assertEqual(len(self.cells),5)


if __name__=='__main__':unittest.main()
