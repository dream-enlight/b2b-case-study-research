import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import runner
import research
import workspace
import test_listing_boundary as boundary


class InaccessibleListingTests(unittest.TestCase):
    setUp=boundary.ListingBoundaryTests.setUp
    tearDown=boundary.ListingBoundaryTests.tearDown
    cmd=boundary.ListingBoundaryTests.cmd
    state=boundary.ListingBoundaryTests.state
    fixture=boundary.ListingBoundaryTests.fixture
    setup_listing=boundary.ListingBoundaryTests.setup_listing
    page=boundary.ListingBoundaryTests.page
    apply=boundary.ListingBoundaryTests.apply

    def saved_failure(self):
        base,state,_=self.setup_listing()
        data=json.loads((Path(__file__).parent/'fixtures/microsoft_inaccessible_listing.json').read_text())
        state['approved_providers']=['Example Suite']
        runner.atomic_json(base/'landscape.json',{'competitors':[data['product']]})
        state['listing_universes']={'Example Suite':{'entries':[],'page':1,'cursor':'','complete':False,'order_verified':False}}
        product=runner.provider_scope(base,state,'Example Suite')
        key='listing30_example-suite_'+workspace.digest(product)[:12]+'_page_001'
        state['jobs'][key]={'status':'returned','response_ready':True,'attempts':1}
        runner.atomic_json(base/'results'/f'{key}.json',data['response'])
        research.remember(base,runner.atomic_json,provider='Example Suite',capture=data['capture'],origin=data['capture']['origin'])
        runner.save(base,state)
        return base,state,key,data

    def test_exact_saved_microsoft_failure_closes_incomplete_without_worker(self):
        base,state,key,data=self.saved_failure()
        paths=[base/'results'/f'{key}.json',runner.screening_path(base),runner.inventory_path(base)]
        before={p:p.read_bytes() for p in paths}
        with patch.object(runner,'codex_call',side_effect=AssertionError('No repeat model/access')),patch.object(workspace,'ensure_sync',return_value=True):
            self.assertTrue(runner.discovery_step(base,state,60,'FORBIDDEN'))
        universe=state['listing_universes']['Example Suite']
        self.assertTrue(universe['complete']) # scheduling closed, coverage incomplete
        self.assertEqual(universe['coverage_status'],'incomplete')
        self.assertEqual(universe['listing_access_status'],'inaccessible')
        self.assertIsNone(universe['listing_story_count'])
        self.assertFalse(universe['listing_exhausted']);self.assertFalse(universe['order_verified'])
        self.assertEqual(universe['entries'],[])
        self.assertIn('Placeholder for Title',universe['continuation_limitation'])
        self.assertIn('capture_sha256',universe['listing_access_evidence'])
        self.assertEqual(state['jobs'][key]['attempts'],1)
        self.assertTrue(all(p.read_bytes()==v for p,v in before.items()))
        self.assertFalse((base/'extracted.json').exists())

    def test_scheduler_continues_other_provider_and_does_not_replay_closed_listing(self):
        base,state,key,data=self.saved_failure()
        with patch.object(workspace,'ensure_sync',return_value=True):runner.discovery_step(base,state,60,'FORBIDDEN')
        state['approved_providers'].append('Fresh')
        with patch.object(runner,'provider_scope',return_value=data['product']):
            for _ in range(2):self.assertEqual(runner.listing_discovery_plan(base,state)['provider'],'Fresh')
        self.assertEqual(state['jobs'][key]['attempts'],1)

    def test_empty_exhaustion_is_not_reinterpreted_as_inaccessible(self):
        base,state,key,data=self.saved_failure()
        for change in ({'listing_exhausted':True},{'order_verified':True},{'has_more':True}):
            self.assertFalse(runner.commit_inaccessible_listing(base,state,key,'Example Suite',{},dict(data['response'],**change)))
        self.assertFalse(state['listing_universes']['Example Suite']['complete'])

    def test_missing_blocked_evidence_or_metadata_alone_cannot_close_listing(self):
        base,state,key,data=self.saved_failure()
        for change in ({'coverage':'metadata'},{'positions_verified':True},{'continuation':{'kind':'exhausted'}},
                       {'continuation':{'kind':'blocked','target':data['response']['next_cursor'],'evidence':''}}):
            proof=dict(data['capture'],**change)
            with patch.object(research,'captures_for',return_value=[proof]):
                self.assertFalse(runner.commit_inaccessible_listing(base,state,key,'Example Suite',{},data['response']))
        self.assertFalse(state['listing_universes']['Example Suite']['complete'])

    def test_saved_real_card_evidence_cannot_be_silently_dropped(self):
        base,state,key,data=self.saved_failure()
        proof=copy.deepcopy(data['capture']);proof.update(positions_verified=True,ordered_entries=[{'position':1,'title':'Actual observed card','url':None,'url_status':'unresolved'}])
        research.remember(base,runner.atomic_json,provider='Example Suite',capture=proof)
        with self.assertRaisesRegex(runner.RunError,'conflicts with saved card evidence'):
            runner.commit_inaccessible_listing(base,state,key,'Example Suite',{},data['response'])
        self.assertFalse(state['listing_universes']['Example Suite']['complete'])

    def test_genuine_exhausted_listing_with_cards_remains_exhausted(self):
        base,state,_=self.setup_listing();obj=self.page(base,state,1,2,exhausted=True)
        self.apply(base,state,obj)
        universe=state['listing_universes']['Beta Software']
        self.assertEqual(universe['coverage_status'],'exhausted')
        self.assertEqual(len(universe['entries']),2)
        self.assertNotEqual(universe.get('listing_access_status'),'inaccessible')

    def test_inaccessible_coverage_enters_methods_source_summary(self):
        base,state,key,data=self.saved_failure()
        with patch.object(runner,'codex_call',side_effect=AssertionError('No worker')),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,state,60,'FORBIDDEN')
            runner.discovery_step(base,state,60,'FORBIDDEN')
        summary=state['screening_summary']['providers'][0]
        self.assertEqual(summary['provider'],'Example Suite')
        self.assertEqual(summary['listing_entries'],0)
        self.assertIsNone(summary['listing_story_count'])
        self.assertEqual(summary['listing_access_status'],'inaccessible')
        self.assertEqual(summary['listing_coverage_status'],'incomplete')
        self.assertIn('template placeholders',summary['continuation_limitation'])
        prompt=(runner.ROOT/'prompts/global_synthesis.md').read_text()
        self.assertIn('Zero observed cards is not evidence of zero customer stories',prompt)
