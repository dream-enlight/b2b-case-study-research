import copy
import unittest
from unittest.mock import patch

import runner
import workspace
import test_listing_arrival as arrival
import test_listing_boundary as boundary


class ListingSchedulingTests(unittest.TestCase):
    setUp=boundary.ListingBoundaryTests.setUp
    tearDown=boundary.ListingBoundaryTests.tearDown
    cmd=boundary.ListingBoundaryTests.cmd
    state=boundary.ListingBoundaryTests.state
    fixture=boundary.ListingBoundaryTests.fixture
    setup_listing=boundary.ListingBoundaryTests.setup_listing
    page=boundary.ListingBoundaryTests.page
    saved=arrival.ListingArrivalTests.saved
    replay=arrival.ListingArrivalTests.replay

    def key(self,base,state,provider):
        page=state.get('listing_universes',{}).get(provider,{}).get('page',1)
        return 'listing30_'+runner.slugify(provider)+'_'+workspace.digest(runner.provider_scope(base,state,provider))[:12]+f'_page_{page:03d}'

    def test_individual_extraction_and_reconcile_do_not_complete_parent(self):
        base,state,ctx,messages=self.saved('sap');state['jobs']['saved']={'status':'running','attempts':1}
        self.replay(base,state,ctx,messages)
        self.assertEqual(state['jobs']['saved']['status'],'running')
        ledger=runner.read_json(runner.screening_path(base))
        for _ in range(2):
            runner.reconcile_screening(base,state,runner.read_json(runner.inventory_path(base)),ledger)
            self.assertEqual(state['jobs']['saved']['status'],'running')

    def test_parent_completes_only_after_bounded_unit_commit(self):
        base,state,_=self.setup_listing();provider='Beta Software';key=self.key(base,state,provider)
        obj=self.page(base,state,1,2);state['jobs'][key]={'status':'running','attempts':1}
        def streamed(*args):
            ctx=args[4]
            runner.commit_worker_message(base,state,key,ctx,{'discovered_case':obj['cases'][0]},'synthetic')
            self.assertEqual(state['jobs'][key]['status'],'running')
            self.assertEqual(state['listing_universes'][provider]['page'],1)
            state['jobs'][key]['status']='returned'
            return obj
        with patch.object(runner,'invoke',side_effect=streamed),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
        self.assertEqual(state['jobs'][key]['status'],'complete')
        self.assertEqual(state['listing_universes'][provider]['page'],2)
        self.assertFalse(state['listing_universes'][provider]['complete'])

    def test_invalid_unit_retains_parent_as_returned(self):
        base,state,_=self.setup_listing();provider='Beta Software';key=self.key(base,state,provider)
        obj=self.page(base,state,1,2);obj.update(next_cursor='',has_more=True,listing_exhausted=True)
        state['jobs'][key]={'status':'returned','attempts':1}
        with patch.object(runner,'invoke',return_value=obj),patch.object(workspace,'ensure_sync',return_value=True):
            with self.assertRaises(runner.RunError):runner.discovery_step(base,state,60,'FORBIDDEN')
        self.assertEqual(state['jobs'][key]['status'],'returned')
        self.assertEqual(state['listing_universes'][provider]['page'],1)

    def test_misclassified_sap_job_is_eligible_without_status_rewrite_or_record_repeat(self):
        base,state,ctx,messages=self.saved('sap');self.replay(base,state,ctx,messages)
        with patch.object(runner,'provider_scope',return_value=ctx['competing_product']):
            key=self.key(base,state,'Example Process')
            state['jobs'][key]={'status':'complete','attempts':1,'response_ready':False,'stream_recovery':{'positions':[10]}}
            state['approved_providers'].append('Fresh')
            before=copy.deepcopy(state['jobs']);record=(base/'extracted.json').read_bytes()
            for _ in range(2):
                plan=runner.listing_discovery_plan(base,state)
                self.assertEqual(plan['provider'],'Example Process')
            self.assertEqual(state['jobs'],before)
            self.assertEqual((base/'extracted.json').read_bytes(),record)

    def test_saved_evidence_fairness_and_completed_providers_not_rescheduled(self):
        base,state,ctx,messages=self.saved('uipath');self.replay(base,state,ctx,messages)
        state['approved_providers']=['Example Process','Example Automation','IBM','Fresh']
        state['listing_universes']['Example Process']=copy.deepcopy(state['listing_universes']['Example Automation'])
        state['listing_universes']['IBM']=copy.deepcopy(state['listing_universes']['Example Automation'])
        state['coverage_turns']={'Example Process':2,'Example Automation':4,'IBM':5}
        with patch.object(runner,'provider_scope',return_value=ctx['competing_product']):
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'Example Process')
            state['coverage_turns']['Example Process']=6
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'Example Automation')
            state['listing_universes']['Example Automation']['complete']=True
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'IBM')
            state['listing_universes']['IBM']['complete']=True
            state['listing_universes']['Example Process']['complete']=True
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'Fresh')

    def test_cached_unfinished_unit_replays_before_new_worker_and_is_idempotent(self):
        base,state,_=self.setup_listing();provider='Beta Software';key=self.key(base,state,provider)
        obj=self.page(base,state,1,2);state['jobs'][key]={'status':'complete','attempts':1,'response_ready':True}
        runner.atomic_json(base/'results'/f'{key}.json',obj)
        state['approved_providers'].append('Fresh')
        product=runner.provider_scope(base,state,provider)
        with patch.object(runner,'provider_scope',return_value=product),patch.object(runner,'codex_call',side_effect=AssertionError('No worker for saved unit')),patch.object(workspace,'ensure_sync',return_value=True):
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],provider)
            runner.discovery_step(base,state,60,'FORBIDDEN')
        self.assertEqual(state['jobs'][key]['attempts'],1)
        ledger=runner.screening_path(base).read_bytes()
        state=runner.read_state(base)
        # A second scheduling pass must not replay the committed prior page.
        with patch.object(runner,'provider_scope',return_value=product):
            self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'Fresh')
        self.assertEqual(runner.screening_path(base).read_bytes(),ledger)

    def test_interrupted_stream_recovers_without_completing_parent(self):
        base,state,ctx,messages=self.saved('sap');state['jobs']['saved']={'status':'running','attempts':1}
        self.replay(base,state,ctx,messages)
        runner.save(base,state);record=(base/'extracted.json').read_bytes()
        state=runner.read_state(base)
        self.replay(base,state,copy.deepcopy(ctx),messages)
        self.assertEqual(state['jobs']['saved']['status'],'running')
        self.assertEqual((base/'extracted.json').read_bytes(),record)
        self.assertFalse(state['listing_universes']['Example Process']['complete'])
