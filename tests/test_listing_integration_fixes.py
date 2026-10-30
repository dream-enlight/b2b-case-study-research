"""Targeted offline regressions for streamed listings and shared source cases."""
import copy,json,unittest
from unittest.mock import patch
import runner,research,workspace
import test_listing_boundary as boundary


class ListingIntegrationFixTests(unittest.TestCase):
    setUp=boundary.ListingBoundaryTests.setUp
    tearDown=boundary.ListingBoundaryTests.tearDown
    cmd=boundary.ListingBoundaryTests.cmd
    state=boundary.ListingBoundaryTests.state
    fixture=boundary.ListingBoundaryTests.fixture
    setup_listing=boundary.ListingBoundaryTests.setup_listing
    record=boundary.ListingBoundaryTests.record
    result=boundary.ListingBoundaryTests.result
    page=boundary.ListingBoundaryTests.page
    apply=boundary.ListingBoundaryTests.apply

    def modern(self,base,state,start=1,count=2,exhausted=False,shared=False,card_ids=None,unresolved=False):
        state['research_policy']['listing_navigation_version']=2
        obj=self.page(base,state,start,count,exhausted=exhausted)
        if shared:
            for row in obj['cases']:row['url']='https://stories.example.com/shared'
        if unresolved:
            for row in obj['cases']:row.update(url=None,url_status='unresolved',decision='unresolved')
        else:
            for row in obj['cases']:row['url_status']='resolved'
        proof={'url':obj['cases'][0]['listing_url'],'role':'listing','coverage':'excerpt',
               'text':'Synthetic witnessed distinct card order and navigation.','positions_verified':True,
               'ordered_entries':[dict(position=r['listing_position'],title=r['title'],url=r['url'],url_status=r['url_status'],
                                       **({'card_id':card_ids[i]} if card_ids else {})) for i,r in enumerate(obj['cases'])],
               'continuation':{'kind':'exhausted' if exhausted else 'offset','target':obj['next_cursor'],'evidence':'Actual synthetic ending/control.'}}
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof,origin='fixture')
        runner.save(base,state)
        return obj,proof

    def context(self,base,state,max_cases=30):
        return {'task':'discover','approved_provider':'Beta Software','first_listing_entries':30,'listing_contract_v2':True,
                'max_cases':max_cases,'compact_receipts':True,'competing_product':runner.provider_scope(base,state,'Beta Software')}

    def full(self,row):
        return dict(row,decision='relevant',reading_depth='substantive',record=self.record(
            {'provider':'Beta Software','url':row['url'],'customer':row['customer']}))

    def capture(self,url):
        return {'url':url,'coverage':'excerpt','text':'Synthetic published customer facts and approved workflow evidence.'}

    def test_all_fresh_streamed_entries_advance_valid_continuation(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state)
        def worker(base,state,stage,key,ctx,*args):
            for row in obj['cases']:
                runner.commit_worker_message(base,state,key,ctx,{'source_captures':[proof],'discovered_case':row},'offline')
            return runner.expand_worker_receipts(base,state,key,ctx,dict(obj,cases=[],completed_ids=['listing:1','listing:2']))
        with patch.object(runner,'invoke',side_effect=worker),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,1,'FORBIDDEN')
        universe=state['listing_universes']['Beta Software']
        self.assertFalse(universe['complete']);self.assertEqual(universe['page'],2)
        self.assertEqual(universe['cursor'],obj['next_cursor'])
        self.assertEqual(universe['coverage_status'],'continuing')

    def test_a_genuinely_repeated_page_is_explicitly_incomplete(self):
        base,state,_=self.setup_listing();obj,_=self.modern(base,state)
        self.apply(base,state,obj);before=copy.deepcopy(state['listing_universes']['Beta Software']['entries'])
        self.apply(base,state,obj)
        universe=state['listing_universes']['Beta Software']
        self.assertTrue(universe['complete']);self.assertEqual(universe['coverage_status'],'incomplete')
        self.assertEqual(universe['entries'],before)

    def test_distinct_slots_share_one_source_case_and_extraction(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,exhausted=True,shared=True)
        ctx=self.context(base,state)
        runner.commit_worker_message(base,state,'listing',ctx,{'source_captures':[proof,self.capture(obj['cases'][0]['url'])],
                                    'discovered_case':self.full(obj['cases'][0])},'offline')
        runner.commit_worker_message(base,state,'listing',ctx,{'discovered_case':obj['cases'][1]},'offline')
        entries=state['listing_universes']['Beta Software']['entries']
        self.assertEqual([r['listing_position'] for r in entries],[1,2])
        self.assertNotEqual(entries[0]['id'],entries[1]['id'])
        self.assertEqual(entries[0]['source_case_id'],entries[1]['source_case_id'])
        self.assertEqual(len(ctx['_checkpoint_rows']),2)
        expanded=runner.expand_worker_receipts(base,state,'listing',ctx,dict(obj,cases=[],completed_ids=['listing:1','listing:2']))
        self.assertEqual([r['listing_position'] for r in expanded['cases']],[1,2])
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        self.assertEqual(len(runner.ordered_records(base)),1)
        self.assertEqual(len(list((base/'research/cases').rglob('*.json'))),1)
        inventory=runner.read_json(runner.inventory_path(base))
        self.assertEqual(sum(len(b['cases']) for b in runner.compile_batches(inventory)),1)
        for ref in (obj['cases'][0]['url'],entries[0]['source_case_id']):
            with self.assertRaisesRegex(runner.RunError,'Ambiguous listing source receipt'):
                runner.expand_worker_receipts(base,state,'listing',ctx,dict(obj,cases=[],completed_ids=[ref]))

    def test_equal_titles_and_urls_do_not_deduplicate_distinct_cards(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,exhausted=True,shared=True,card_ids=['card-a','card-b'])
        obj['cases'][1]['title']=obj['cases'][0]['title'];proof['ordered_entries'][1]['title']=proof['ordered_entries'][0]['title']
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof,origin='fixture')
        self.apply(base,state,obj)
        self.assertEqual(len(state['listing_universes']['Beta Software']['entries']),2)
        self.assertEqual(len(runner.coverage_plan(base,state)['cases']),1)

    def test_same_card_reappearance_is_idempotent(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,count=1,card_ids=['stable-card'])
        ctx=self.context(base,state)
        for _ in range(2):runner.commit_worker_message(base,state,'listing',ctx,{'source_captures':[proof],'discovered_case':obj['cases'][0]},'offline')
        self.assertEqual(len(state['listing_universes']['Beta Software']['entries']),1)
        self.assertEqual(len(ctx['_checkpoint_rows']),1)

    def test_repeated_stable_card_at_new_navigation_offset_creates_no_missing_slot(self):
        base,state,_=self.setup_listing();obj,_=self.modern(base,state,count=1,card_ids=['stable-card'])
        obj['cases'][0]['decision']='excluded';self.apply(base,state,obj)
        repeated,proof=self.modern(base,state,start=2,count=1,card_ids=['stable-card'])
        repeated['cases'][0].update(title=obj['cases'][0]['title'],customer=obj['cases'][0]['customer'],url=obj['cases'][0]['url'],decision='excluded')
        proof['ordered_entries'][0].update(title=repeated['cases'][0]['title'],url=repeated['cases'][0]['url'])
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof,origin='fixture')
        self.apply(base,state,repeated)
        universe=state['listing_universes']['Beta Software']
        self.assertEqual([r['listing_position'] for r in universe['entries']],[1])
        self.assertEqual([r['position'] for r in universe['observed_slots']],[1])
        self.assertEqual(runner.coverage_plan(base,state)['action'],'done')

    def test_shared_source_slots_each_consume_assignment_budget(self):
        base,state,_=self.setup_listing();obj,_=self.modern(base,state,shared=True)
        ctx=self.context(base,state,max_cases=1)
        runner.commit_listing_candidate(base,state,'listing',ctx,obj['cases'][0])
        with self.assertRaisesRegex(runner.RunError,'bounded unit'):
            runner.commit_listing_candidate(base,state,'listing',ctx,obj['cases'][1])

    def test_unique_historical_url_and_case_id_receipts_still_expand(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,count=1)
        ctx=self.context(base,state)
        runner.commit_worker_message(base,state,'listing',ctx,{'source_captures':[proof],'discovered_case':obj['cases'][0]},'offline')
        row=obj['cases'][0]
        for ref in (row['url'],runner.case_id('Beta Software',row['url']),'listing:1'):
            result=runner.expand_worker_receipts(base,state,'listing',ctx,dict(obj,cases=[],completed_ids=[ref]))
            self.assertEqual(result['cases'],[row])

    def test_full_extraction_completes_prior_pending_metadata_without_identity_change(self):
        base,cases=self.fixture(1);state=self.state();case=cases[0]
        ledger=runner.read_json(runner.screening_path(base));ledger[case['id']]['discovery_key']='old_metadata'
        runner.atomic_json(runner.screening_path(base),ledger)
        row=dict(url=case['url'],customer='New descriptive card label',title='Different listing teaser',
                 reading_depth='substantive',**{k:v for k,v in self.result(case).items() if k!='id'})
        research.remember(base,runner.atomic_json,provider=case['provider'],capture=self.capture(case['url']))
        runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),row)
        receipt=runner.read_json(runner.case_receipt_path(base,state,case['id']))
        self.assertEqual(receipt['case']['customer'],case['customer']);self.assertEqual(receipt['case']['title'],case['title'])
        self.assertEqual(receipt['task'],'new_resolver');self.assertEqual(receipt['case']['discovery_key'],'old_metadata')
        self.assertEqual(runner.read_json(base/'extracted.json')[case['id']]['customer'],case['customer'])
        original=(base/'extracted.json').read_bytes()
        runner.commit_discovered_case(base,state,'another_resolver',self.context(base,state),row)
        self.assertEqual((base/'extracted.json').read_bytes(),original)

    def test_pending_completion_rejects_unsupported_or_invalid_records(self):
        base,cases=self.fixture(1);state=self.state();case=cases[0]
        row=dict(url=case['url'],customer=case['customer'],title=case['title'],reading_depth='substantive',
                 **{k:v for k,v in self.result(case).items() if k!='id'})
        before=runner.screening_path(base).read_bytes()
        with self.assertRaisesRegex(runner.RunError,'readable source evidence'):
            runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),row)
        research.remember(base,runner.atomic_json,provider=case['provider'],capture=self.capture(case['url']))
        invalid=copy.deepcopy(row);invalid['record']['source_url']='https://wrong.example.com/unassigned'
        with self.assertRaisesRegex(runner.RunError,'provider\\+URL'):
            runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),invalid)
        self.assertFalse((base/'extracted.json').exists());self.assertEqual(runner.screening_path(base).read_bytes(),before)

    def test_completed_legacy_extraction_is_reused_and_conflicts_rejected(self):
        base,cases=self.fixture(1);state=self.state();case=cases[0]
        runner.persist_records(base,[case],[self.record(case)])
        row=dict(url=case['url'],customer=case['customer'],title=case['title'],reading_depth='substantive',
                 **{k:v for k,v in self.result(case).items() if k!='id'})
        before=(base/'extracted.json').read_bytes()
        runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),row)
        conflicting=copy.deepcopy(row);conflicting['record']['buying_situation']='Conflicting new claims.'
        with self.assertRaisesRegex(runner.RunError,'immutable'):
            runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),conflicting)
        self.assertEqual((base/'extracted.json').read_bytes(),before)
        self.assertFalse(runner.case_receipt_path(base,state,case['id']).exists())

    def test_enumeration_precedes_resolution_and_then_uses_existing_bounded_queue(self):
        base,state,_=self.setup_listing();first,_=self.modern(base,state,unresolved=True)
        self.apply(base,state,first)
        self.assertEqual(runner.coverage_plan(base,state)['action'],'discover')
        second,_=self.modern(base,state,start=3,exhausted=True,unresolved=True)
        self.apply(base,state,second)
        plan=runner.coverage_plan(base,state)
        self.assertEqual(plan['action'],'resolve_urls');self.assertEqual(len(plan['cases']),4)
        self.assertEqual(state['research_policy']['review_batch_size'],20)

    def test_blocked_enumeration_releases_saved_slots_to_resolution(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,unresolved=True)
        self.apply(base,state,obj)
        proof=dict(proof,continuation={'kind':'blocked','target':obj['next_cursor'],'evidence':'Actual synthetic inaccessible navigation control.'})
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof,origin='fixture')
        self.apply(base,state,dict(obj,cases=[],has_more=False,listing_exhausted=False))
        universe=state['listing_universes']['Beta Software']
        self.assertTrue(universe['complete']);self.assertEqual(universe['coverage_status'],'incomplete')
        self.assertEqual(runner.coverage_plan(base,state)['action'],'resolve_urls')

    def test_saved_combined_shared_source_checkpoints_replay_by_slot(self):
        base,state,_=self.setup_listing();obj,proof=self.modern(base,state,exhausted=True,shared=True)
        ctx=self.context(base,state);ctx['target']=state['company'];key='listing_shared_replay'
        messages=[{'source_captures':[proof,self.capture(obj['cases'][0]['url'])],'discovered_case':self.full(obj['cases'][0])},
                  {'discovered_case':obj['cases'][1]}]
        log=base/'logs'/f'{key}_123456abcdef.jsonl'
        runner.atomic_text(log,'\n'.join(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(m)}}) for m in messages))
        runner.atomic_text(log.with_suffix('.prompt.txt'),'TASK ASSIGNMENT (machine generated):\n'+json.dumps(ctx))
        runner.atomic_json(log.with_suffix('.result.json'),dict(obj,cases=[],completed_ids=['listing:1','listing:2']))
        with patch.object(runner,'codex_call',side_effect=AssertionError('No live worker')):
            result=runner.replay_worker_output(base,state,key,ctx,2)
        self.assertEqual([r['listing_position'] for r in result['cases']],[1,2])
        self.assertEqual(len(state['listing_universes']['Beta Software']['entries']),2)
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)

    def test_later_full_record_also_completes_relevant_metadata(self):
        base,cases=self.fixture(1);state=self.state();case=cases[0]
        ledger=runner.read_json(runner.screening_path(base));ledger[case['id']].update(decision='relevant',discovery_key='old_metadata')
        runner.atomic_json(runner.screening_path(base),ledger)
        row=dict(url=case['url'],customer=case['customer'],title=case['title'],reading_depth='substantive',
                 **{k:v for k,v in self.result(case).items() if k!='id'})
        research.remember(base,runner.atomic_json,provider=case['provider'],capture=self.capture(case['url']))
        runner.commit_discovered_case(base,state,'new_resolver',self.context(base,state),row)
        self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
        self.assertEqual(runner.read_json(runner.screening_path(base))[case['id']]['basis'],'substantive')
