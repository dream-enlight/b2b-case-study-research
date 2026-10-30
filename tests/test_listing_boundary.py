import copy,json,unittest
from unittest.mock import patch
import runner,research,performance,workspace
import test_efficiency as efficiency


class ListingBoundaryTests(unittest.TestCase):
    setUp=efficiency.EfficiencyTests.setUp
    tearDown=efficiency.EfficiencyTests.tearDown
    cmd=efficiency.EfficiencyTests.cmd
    state=efficiency.EfficiencyTests.state
    fixture=efficiency.EfficiencyTests.fixture
    record=efficiency.EfficiencyTests.record
    result=efficiency.EfficiencyTests.result

    def setup_listing(self,n=0):
        base,cases=self.fixture(n);s=self.state();s['phase']='stage2'
        s['research_policy']['first_listing_entries']=30
        runner.save(base,s)
        return base,s,cases

    def page(self,base,s,start,count,decisions=None,exhausted=False,verified=True):
        provider=s['approved_providers'][0];listing='https://stories.example.com/customer-stories'
        items=[]
        for p in range(start,start+count):
            items.append(dict(customer=f'Customer {p}',title=f'Story {p}',url=f'https://stories.example.com/entry/{p}',
                listing_position=p,listing_url=listing,decision=(decisions or {}).get(p,'relevant'),reason='Synthetic listing evidence.',
                evidence='Synthetic scoped metadata.',record=None,reading_depth='lightweight',contribution=''))
        research.remember(base,runner.atomic_json,provider=provider,origin='synthetic-listing',capture={'url':listing,'role':'listing',
            'coverage':'excerpt','text':'Synthetic listing order, not discovery order.','order_verified':verified,
            'ordered_entries':[{'position':c['listing_position'],'url':c['url']} for c in items]})
        return {'cases':items,'has_more':not exhausted and start+count<=30,'next_cursor':str(start+count) if not exhausted and start+count<=30 else '',
                'order_verified':verified,'listing_exhausted':exhausted}

    def apply(self,base,s,obj):
        with patch.object(runner,'invoke',return_value=obj),patch.object(workspace,'ensure_sync',return_value=True):
            return runner.discovery_step(base,s,60,'FORBIDDEN')

    def test_new_runs_default_to_first_thirty(self):
        self.modern=True;self.cmd('init','--company','New','--website','https://example.com')
        self.assertEqual(self.state('new')['research_policy']['first_listing_entries'],30)

    def test_thirty_slots_include_exclusions_and_failures_without_replacement(self):
        base,s,_=self.setup_listing()
        self.apply(base,s,self.page(base,s,1,20,{1:'excluded',2:'unresolved'}))
        self.assertFalse(s['listing_universes']['Beta Software']['complete'])
        self.apply(base,s,self.page(base,s,21,10))
        u=s['listing_universes']['Beta Software'];self.assertEqual(len(u['entries']),30);self.assertTrue(u['complete'])
        ledger=runner.read_json(runner.screening_path(base));self.assertEqual(len(ledger),30)
        self.assertEqual(ledger[u['entries'][0]['source_case_id']]['decision'],'excluded')
        self.assertEqual(ledger[u['entries'][1]['source_case_id']]['decision'],'unresolved')
        plan=runner.coverage_plan(base,s)
        self.assertEqual(plan['action'],'review_batch')
        # Metadata relevance is pending extraction until an immutable record exists.
        while plan['action']=='review_batch':
            for case in plan['cases']:runner.commit_case_result(base,s,'synthetic',plan['cases'],self.result(case))
            plan=runner.coverage_plan(base,s)
        self.assertEqual(plan['action'],'done')
        with patch.object(runner,'invoke',side_effect=AssertionError('No replacement discovery')),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'stage3')
        self.assertEqual(sum(len(b['cases']) for b in runner.read_json(base/'batches.json')),28)

    def test_31st_slot_or_missing_listing_order_is_rejected(self):
        base,s,_=self.setup_listing()
        for obj in (self.page(base,s,1,1,verified=False),dict(self.page(base,s,1,1),cases=[dict(self.page(base,s,1,1)['cases'][0],listing_position=31)])):
            with self.assertRaises(runner.RunError):self.apply(base,s,obj)
        self.assertFalse(s.get('listing_universes',{}).get('Beta Software',{}).get('entries'))

    def test_listing_evidence_not_old_inventory_order_is_required(self):
        base,s,cases=self.setup_listing(35)
        obj=self.page(base,s,1,1);obj['cases'][0]['url']=cases[0]['url']
        with self.assertRaisesRegex(runner.RunError,'verify natural listing order'):self.apply(base,s,obj)

    def test_unverified_saved_link_associations_cannot_be_promoted_on_resume(self):
        base,s,_=self.setup_listing()
        obj=self.page(base,s,1,1,verified=False)
        obj['order_verified']=True  # A final assertion cannot upgrade uncertain capture evidence.
        with self.assertRaisesRegex(runner.RunError,'verify natural listing order'):self.apply(base,s,obj)
        self.assertFalse(s['listing_universes']['Beta Software']['entries'])

    def test_less_than_thirty_requires_real_exhaustion(self):
        base,s,_=self.setup_listing()
        self.apply(base,s,self.page(base,s,1,7,exhausted=True))
        self.assertTrue(s['listing_universes']['Beta Software']['complete'])
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),7)

    def test_listing_only_recovery_rejects_deep_records(self):
        base,s,_=self.setup_listing();s['listing_order_recovery']=True
        obj=self.page(base,s,1,1);obj['cases'][0]['reading_depth']='substantive'
        with self.assertRaisesRegex(runner.RunError,'must not perform deep'):self.apply(base,s,obj)

    def test_excess_old_queue_is_not_scheduled_and_completed_records_survive(self):
        base,s,cases=self.setup_listing(40)
        for c in cases[:35]:runner.commit_case_result(base,s,'old',cases,self.result(c))
        original=(base/'extracted.json').read_bytes();ledger=(runner.screening_path(base)).read_bytes()
        s['listing_universes']={'Beta Software':{'entries':[dict(cases[39],listing_position=1)],'complete':True,'order_verified':True}}
        p=runner.coverage_plan(base,s);self.assertEqual([c['id'] for c in p['cases']],[cases[39]['id']])
        active=research.eligible_inventory(s,{'Beta Software':cases},runner.read_json(base/'extracted.json'))
        self.assertEqual({c['id'] for c in active['Beta Software']},{c['id'] for c in cases[:35]+[cases[39]]})
        self.assertEqual((base/'extracted.json').read_bytes(),original)
        self.assertEqual(runner.screening_path(base).read_bytes(),ledger)

    def test_page_replay_after_crash_is_idempotent_and_never_reclassifies(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,20,{1:'excluded'})
        self.apply(base,s,obj);ledger=runner.read_json(runner.screening_path(base))
        s['listing_universes']['Beta Software'].update(page=1,cursor='')
        # The original page was already returned before the simulated crash.
        key='listing30_beta-software_'+workspace.digest(runner.provider_scope(base,s,'Beta Software'))[:12]+'_page_001'
        runner.atomic_json(base/'results'/f'{key}.json',obj);s['jobs'][key]={'status':'returned','attempts':1}
        self.apply(base,s,obj)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),20)
        self.assertEqual(runner.read_json(runner.screening_path(base)),ledger)

    def test_compact_discovery_receipt_retains_full_record_once(self):
        base,s,_=self.setup_listing();item=self.page(base,s,1,1)['cases'][0]
        c=dict(item,id=runner.case_id('Beta Software',item['url']),provider='Beta Software')
        item.update(reading_depth='substantive',record=self.record(c))
        ctx={'task':'discover','first_listing_entries':30,'compact_receipts':True,'approved_provider':'Beta Software',
             'competing_product':runner.provider_scope(base,s,'Beta Software'),'max_cases':20}
        runner.commit_worker_message(base,s,'new',ctx,{'discovered_case':item},'synthetic')
        obj={'cases':[],'completed_ids':[item['url']],'has_more':True,'next_cursor':'2'}
        materialized=runner.expand_worker_receipts(base,s,'new',ctx,obj)
        self.assertEqual(materialized['cases'],[item])
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        with self.assertRaisesRegex(runner.RunError,'duplicated'):
            runner.expand_worker_receipts(base,s,'new',ctx,dict(obj,cases=[item],completed_ids=[]))
        with self.assertRaisesRegex(runner.RunError,'Unverified'):
            runner.expand_worker_receipts(base,s,'new',ctx,dict(obj,completed_ids=['https://unassigned.example.com']))

    def test_early_metadata_exclusion_is_not_reviewed_or_extracted(self):
        base,s,_=self.setup_listing();self.apply(base,s,self.page(base,s,1,1,{1:'excluded'},exhausted=True))
        with patch.object(runner,'codex_call',side_effect=AssertionError('Excluded source must never open')),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,s,60,'FORBIDDEN')
            runner.step(base,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'finalize_sheet')

    def test_real_batched_runtime_events_count_distinct_sources(self):
        fixture={'type':'web_search','action':{'type':'other'},'results':[
            {'url':'https://example.com/a/','ref_id':'turn1view0','snippet':'Total lines: 200'},
            {'url':'https://example.com/a','ref_id':'turn1view1','snippet':'Total lines: 200'},
            {'url':'https://example.com/b','ref_id':'turn1view2','snippet':'Total lines: 100'}]}
        self.assertEqual(performance.source_attempts(fixture),['https://example.com/a','https://example.com/b'])
        for ty in ('open','open_page','find','find_in_page','click'):
            self.assertEqual(len(performance.source_attempts({'type':'web_search','action':{'type':ty,'url':'https://example.com/a'}})),1)
        self.assertEqual(performance.source_attempts({'type':'web_search','action':{'type':'search','query':'test'},'results':[{'url':'https://example.com/a','snippet':'Search summary only'}]}),[])
        self.assertEqual(len(performance.source_attempts({'type':'web_search','action':{'type':'other'},'results':[{'title':'Internal Error'}]})),1)

    def test_actual_event_budget_yields_durable_prefix_and_reassigns_only_unfinished(self):
        import os
        base,cases=self.fixture(5);s=self.state();s['phase']='stage2';s['research_policy']['max_source_attempts']=2
        with patch.dict(os.environ,{'FAKE_MODE':'actual_runtime_budget'}):
            self.assertTrue(runner.run_review_batch(base,s,{'cases':cases,'provider':'Beta Software'},10,efficiency.FAKE))
        self.assertEqual(s['phase'],'stage2')
        self.assertEqual(len(runner.read_json(base/'extracted.json')),2)
        pending=runner.coverage_plan(base,s)['cases']
        self.assertEqual({c['id'] for c in pending},{c['id'] for c in cases[2:]})
        events=[json.loads(line) for line in (base/'performance.jsonl').read_text().splitlines()]
        self.assertTrue(any(e['kind']=='bounded_yield' for e in events))
        self.assertEqual(len(next(e for e in events if e['kind']=='execution')['source_attempts']),2)

    def test_multivendor_extraction_receipt_ids_are_not_merged_by_url(self):
        base,s,cases=self.setup_listing(1);first=cases[0];second=dict(first,provider='Other',id=runner.case_id('Other',first['url']))
        ctx={'task':'extract_batch','assigned_cases':[first,second],'compact_receipts':True}
        for c in (first,second):runner.commit_worker_message(base,s,'extract',ctx,{'extracted_record':self.record(c)},'synthetic')
        obj=runner.expand_worker_receipts(base,s,'extract',ctx,{'records':[],'completed_ids':[first['id'],second['id']]})
        self.assertEqual(len(obj['records']),2)
        self.assertEqual(len(runner.read_json(base/'extracted.json')),2)

    def test_migration_does_not_touch_historical_data_or_budgets(self):
        base,cases=self.fixture(1);s=self.state();runner.commit_case_result(base,s,'old',cases,self.result(cases[0]))
        s['workspace_sheet']={'id':'preserved-sheet','url':'https://docs.google.com/spreadsheets/d/preserved-sheet/edit'};s['workspace_verified_ids']=[cases[0]['id']];runner.save(base,s)
        paths=[base/'extracted.json',runner.screening_path(base),runner.inventory_path(base),runner.case_receipt_path(base,s,cases[0]['id'])]
        before={p:p.read_bytes() for p in paths};policy=copy.deepcopy(s['research_policy'])
        self.assertEqual(self.cmd('enable-listing-boundary','test-company').returncode,0)
        after=self.state();self.assertEqual(after['phase'],s['phase'])
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
        self.assertEqual({k:v for k,v in after['research_policy'].items() if k!='first_listing_entries'},policy)
        self.assertEqual(after['workspace_sheet'],s['workspace_sheet']);self.assertEqual(after['workspace_verified_ids'],s['workspace_verified_ids'])
        unchanged=(base/'state.json').read_bytes();self.cmd('enable-listing-boundary','test-company')
        self.assertEqual((base/'state.json').read_bytes(),unchanged)


if __name__=='__main__':unittest.main()
