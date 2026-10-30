"""Offline lifecycle checks; no workers, web access or Workspace calls."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import runner
import research
import url_recovery
import workspace
import test_unresolved_listing_cards as cards


class ListingLifecycleTests(unittest.TestCase):
    setUp=cards.UnresolvedListingCardTests.setUp
    tearDown=cards.UnresolvedListingCardTests.tearDown
    cmd=cards.UnresolvedListingCardTests.cmd
    state=cards.UnresolvedListingCardTests.state
    fixture=cards.UnresolvedListingCardTests.fixture
    setup_listing=cards.UnresolvedListingCardTests.setup_listing
    page=cards.UnresolvedListingCardTests.page
    apply=cards.UnresolvedListingCardTests.apply
    unresolved=cards.UnresolvedListingCardTests.unresolved
    record=cards.UnresolvedListingCardTests.record
    result=cards.UnresolvedListingCardTests.result

    def test_thirty_metadata_positions_and_twenty_review_cases(self):
        base,state,_=self.setup_listing()
        obj=self.page(base,state,1,30)
        with patch.object(runner,'invoke',return_value=obj) as worker,patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        context=worker.call_args.args[4]
        self.assertEqual(context['max_cases'],30)
        self.assertTrue(state['listing_universes']['Beta Software']['complete'])
        plan=runner.coverage_plan(base,state)
        self.assertEqual(plan['action'],'review_batch')
        self.assertEqual(len(plan['cases']),20)
        self.assertEqual(state['research_policy']['review_batch_size'],20)

    def test_closed_listing_schedules_bounded_urls_and_preserves_partial_work(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,30)
        self.apply(base,state,obj)
        self.assertEqual(len(runner.coverage_plan(base,state)['cases']),20)
        before=copy.deepcopy(state['listing_universes']['Beta Software'])
        # A bounded worker finishes one slot. Remaining slots are ordinary work.
        row=dict(obj['cases'][0],reason='Two candidates lacked identifying source content.',
                 evidence='Candidate pages did not name this witnessed story.')
        with patch.object(runner,'invoke',return_value={'cases':[row]}),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        plan=runner.coverage_plan(base,state)
        self.assertEqual(plan['action'],'resolve_urls')
        self.assertEqual(plan['cases'][0]['listing_position'],2)
        self.assertEqual(state['phase'],'stage2')
        first=state['listing_universes']['Beta Software']['entries'][0]
        self.assertEqual(first['id'],before['entries'][0]['id'])
        self.assertTrue(first['resolution_outcome']['receipt'])
        self.assertEqual(research.listing_work(state,'Beta Software',{}, {})[0]['status'],'terminal_unresolved')
        runner.save(base,state)
        self.assertEqual(runner.coverage_plan(base,runner.read_state(base))['cases'][0]['listing_position'],2)

    def test_url_upgrade_preserves_slot_identity_and_queues_extraction(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,1)
        self.apply(base,state,obj)
        before=copy.deepcopy(state['listing_universes']['Beta Software']['entries'][0])
        row=dict(obj['cases'][0],url='https://stories.example.com/verified',url_status='content_confirmed',decision='relevant')
        research.remember(base,runner.atomic_json,provider='Beta Software',capture={
            'url':row['url'],'coverage':'excerpt','text':'Story 1 uses the approved product.',
            'listing_association':{'listing_url':row['listing_url'],'position':1,'title':row['title'],'quote':'Story 1 uses the approved product.'}})
        with patch.object(runner,'invoke',return_value={'cases':[row]}),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        entry=state['listing_universes']['Beta Software']['entries'][0]
        self.assertEqual(entry['id'],before['id'])
        self.assertEqual(entry['listing_id'],before['listing_id'])
        self.assertEqual(entry['source_case_id'],runner.case_id('Beta Software',row['url']))
        plan=runner.coverage_plan(base,state)
        self.assertEqual(plan['action'],'review_batch')
        self.assertEqual(plan['cases'][0]['id'],entry['source_case_id'])
        runner.commit_case_result(base,state,'synthetic',plan['cases'],self.result(plan['cases'][0]))
        self.assertEqual(runner.coverage_plan(base,state)['action'],'done')
        self.assertEqual(research.listing_work(state,'Beta Software',runner.read_json(runner.screening_path(base)),runner.read_json(base/'extracted.json'))[0]['status'],'extracted')
        self.assertEqual(len(research.eligible_inventory(state,runner.read_json(runner.inventory_path(base)),runner.read_json(base/'extracted.json'))['Beta Software']),1)

    def test_unproven_candidate_never_becomes_source(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,1);self.apply(base,state,obj)
        row=dict(obj['cases'][0],url='https://stories.example.com/guess',url_status='content_confirmed',decision='relevant')
        with patch.object(runner,'invoke',return_value={'cases':[row]}),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        entry=state['listing_universes']['Beta Software']['entries'][0]
        self.assertIsNone(entry['url'])
        self.assertEqual(runner.read_json(runner.screening_path(base)),{})
        self.assertTrue(list((base/'research/url_recovery_unverified').glob('*.json')))

    def test_substantive_discovery_has_independent_twenty_case_limit(self):
        base,state,_=self.setup_listing();obj=self.page(base,state,1,30)
        ctx={'approved_provider':'Beta Software','max_cases':30,'competing_product':runner.provider_scope(base,state,'Beta Software')}
        for row in obj['cases'][:20]:
            runner.commit_listing_candidate(base,state,'synthetic',ctx,dict(row,reading_depth='substantive'))
        with self.assertRaisesRegex(runner.RunError,'substantive review budget'):
            runner.commit_listing_candidate(base,state,'synthetic',ctx,dict(obj['cases'][20],reading_depth='substantive'))
        runner.commit_listing_candidate(base,state,'synthetic',ctx,obj['cases'][20])
        self.assertEqual(len(state['listing_universes']['Beta Software']['entries']),21)

    def test_completed_history_is_read_only_and_legacy_ids_still_work(self):
        base,state,_=self.setup_listing();obj=self.page(base,state,1,1,exhausted=True);self.apply(base,state,obj)
        entry=state['listing_universes']['Beta Software']['entries'][0]
        # Simulate the previous entry format, whose id is its source-case id.
        entry['id']=entry.pop('source_case_id');entry.pop('listing_id')
        original=copy.deepcopy(state)
        plan=runner.coverage_plan(base,state)
        self.assertEqual(plan['cases'][0]['id'],entry['id'])
        self.assertEqual(state,original)
        state['phase']='complete';runner.save(base,state)
        self.assertTrue(runner.step(base,state,60,'FORBIDDEN') is None or state['phase']=='complete')

    def test_closed_observed_only_slot_is_still_schedulable(self):
        base,state,_=self.setup_listing();obj,proof=self.unresolved(base,state,1)
        runner.remember_listing_slots(state,'Beta Software',proof)
        state['listing_universes']['Beta Software']['complete']=True
        runner.save(base,state)
        plan=runner.listing_discovery_plan(base,state)
        self.assertEqual(plan['action'],'resolve_urls')
        row=dict(obj['cases'][0],customer='Unknown',reason='The witnessed card exposes no destination and no identifying candidate source was accessible.')
        with patch.object(runner,'invoke',return_value={'cases':[row]}),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        self.assertEqual(runner.coverage_plan(base,state)['action'],'done')
        self.assertEqual(len(state['listing_universes']['Beta Software']['entries']),1)

    def test_quota_interrupt_retains_slot_receipt_and_does_not_close_peers(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,2);self.apply(base,state,obj)
        row=dict(obj['cases'][0],reason='Candidate sources failed to identify this exact card.')
        def interrupted(base,state,stage,key,context,timeout,cli):
            runner.commit_worker_message(base,state,key,context,{'discovered_case':row},'synthetic')
            return None
        with patch.object(runner,'invoke',side_effect=interrupted),patch.object(workspace,'ensure_sync',return_value=True):
            self.assertFalse(runner.discovery_step(base,state,60,'FORBIDDEN'))
        self.assertEqual([r['listing_position'] for r in runner.coverage_plan(base,state)['cases']],[2])
        receipt=state['listing_universes']['Beta Software']['entries'][0]['resolution_outcome']['receipt']
        self.assertTrue(runner.read_json(Path(receipt))['row']['reason'])

    def test_saved_search_candidate_is_passed_before_new_browsing(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,1)
        obj['cases'][0].update(title='Customer One exact case title',customer='Customer One')
        # The candidate index never asserts that a candidate is a verified URL.
        state['listing_universes']={'Beta Software':{'entries':[obj['cases'][0]]}}
        runner.atomic_json(base/'research/memory.json',{'searches':{'saved':{'results':[
            {'title':'Customer One exact case title','url':'https://stories.example.com/candidate','snippet':'Saved metadata only.'}]}}})
        found=url_recovery.candidates(base,state)
        self.assertEqual(found['Beta Software:1'][0]['url'],'https://stories.example.com/candidate')
        self.assertIsNone(state['listing_universes']['Beta Software']['entries'][0]['url'])

    def test_unfinished_legacy_stage_three_returns_to_pending_urls(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,1);self.apply(base,state,obj)
        state['phase']='stage3';runner.save(base,state)
        with patch.object(runner,'invoke',side_effect=AssertionError('Transition needs no research')):
            self.assertTrue(runner.step(base,state,60,'FORBIDDEN'))
        self.assertEqual(state['phase'],'stage2')
        self.assertEqual(runner.coverage_plan(base,state)['action'],'resolve_urls')
