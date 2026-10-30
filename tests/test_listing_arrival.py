import argparse
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import runner
import research
import test_listing_boundary as boundary


class ListingArrivalTests(unittest.TestCase):
    setUp=boundary.ListingBoundaryTests.setUp
    tearDown=boundary.ListingBoundaryTests.tearDown
    cmd=boundary.ListingBoundaryTests.cmd
    state=boundary.ListingBoundaryTests.state
    fixture=boundary.ListingBoundaryTests.fixture
    setup_listing=boundary.ListingBoundaryTests.setup_listing

    def saved(self,name):
        base,state,_=self.setup_listing()
        data=json.loads((Path(__file__).parent/'fixtures/listing_arrival'/f'{name}.json').read_text())
        ctx=data['context'];provider=ctx['approved_provider']
        state['approved_providers']=[provider]
        return base,state,ctx,data['messages']

    def replay(self,base,state,ctx,messages):
        for message in messages:
            runner.commit_worker_message(base,state,'saved',ctx,message,'saved-fixture')

    def test_exact_saved_sap_extraction_at_ten_and_idempotent_resume(self):
        base,state,ctx,messages=self.saved('sap')
        self.replay(base,state,ctx,messages)
        universe=state['listing_universes']['Example Process']
        self.assertEqual([r['position'] for r in universe['observed_slots']],list(range(1,31)))
        self.assertEqual([r['listing_position'] for r in universe['entries']],[10])
        records=(base/'extracted.json').read_bytes()
        self.assertEqual(next(iter(runner.read_json(base/'extracted.json').values()))['customer'],'Example Customer')
        self.assertFalse(universe['complete'])
        with self.assertRaisesRegex(runner.RunError,'lack recorded case decisions'):
            runner.require_listing_decisions(universe,complete=True)
        state=runner.read_state(base)
        self.replay(base,state,copy.deepcopy(ctx),messages)
        self.assertEqual((base/'extracted.json').read_bytes(),records)
        self.assertEqual(len(state['listing_universes']['Example Process']['entries']),1)

    def test_exact_saved_uipath_metadata_at_ten_without_fabricated_decisions(self):
        base,state,ctx,messages=self.saved('uipath')
        self.replay(base,state,ctx,messages)
        universe=state['listing_universes']['Example Automation']
        self.assertEqual(len(universe['observed_slots']),12)
        self.assertEqual([r['listing_position'] for r in universe['entries']],[10])
        self.assertEqual(runner.read_json(runner.screening_path(base)),{})
        self.assertFalse((base/'extracted.json').exists())

    def test_out_of_order_missing_decisions_then_interrupted_resume(self):
        base,state,ctx,messages=self.saved('uipath');self.replay(base,state,ctx,messages)
        proof=messages[0]['source_capture'];template=messages[1]['discovered_case']
        def row(p):
            return dict(template,listing_position=p,title=proof['ordered_entries'][p-1]['title'],customer='Unknown')
        for p in [12,2,1,6]:self.replay(base,state,ctx,[{'discovered_case':row(p)}])
        state=runner.read_state(base)
        for p in [11,9,8,7,5,4,3]:self.replay(base,state,dict(ctx),[{'discovered_case':row(p)}])
        universe=state['listing_universes']['Example Automation']
        runner.require_listing_decisions(universe,complete=True)
        self.assertEqual([r['listing_position'] for r in universe['entries']],list(range(1,13)))

    def test_unsupported_position_missing_evidence_and_conflict_rejected(self):
        base,state,ctx,messages=self.saved('uipath');self.replay(base,state,ctx,messages)
        row=messages[1]['discovered_case']
        for changes in ({'listing_position':13},{'listing_position':31},{'title':'Invented title'},
                        {'customer':'Conflicting identity'},{'url':'https://guessed.example.com/story'}):
            with self.subTest(changes=changes),self.assertRaises(runner.RunError):
                self.replay(base,state,ctx,[{'discovered_case':dict(row,**changes)}])
        # Exact repeated checkpoints are replay-safe, never additional slots.
        self.replay(base,state,ctx,[{'discovered_case':row}])
        self.assertEqual(len(state['listing_universes']['Example Automation']['entries']),1)
        with patch.object(research,'captures_for',return_value=[]):
            with self.assertRaisesRegex(runner.RunError,'verify natural listing order'):
                runner.commit_listing_candidate(base,state,'saved',dict(ctx,_listing_proofs={}),row)

    def test_out_of_order_cannot_exceed_worker_budget_or_close_with_holes(self):
        base,state,ctx,messages=self.saved('uipath');ctx['max_cases']=1
        self.replay(base,state,ctx,messages)
        row=messages[1]['discovered_case'];proof=messages[0]['source_capture']
        with self.assertRaisesRegex(runner.RunError,'bounded unit'):
            self.replay(base,state,ctx,[{'discovered_case':dict(row,listing_position=1,title=proof['ordered_entries'][0]['title'])}])
        with self.assertRaisesRegex(runner.RunError,'lack recorded case decisions'):
            runner.require_listing_decisions(state['listing_universes']['Example Automation'])

    def test_recover_saved_failed_stream_without_model_or_clearing_pause(self):
        base,state,ctx,messages=self.saved('sap');provider=ctx['approved_provider']
        # Use the exact saved assignment product without looking up a new scope.
        key='listing30_example-process_'+runner.workspace.digest(ctx['competing_product'])[:12]+'_page_001'
        state.update(phase='paused_error',paused_from='stage2',pause_reason='original validation')
        state['jobs'][key]={'status':'paused','response_ready':False,
            'last_error':'Listing positions must be a distinct consecutive prefix.','attempts':1}
        runner.save(base,state)
        log=base/'logs'/f'{key}_fixture.jsonl'
        log.parent.mkdir(exist_ok=True)
        log.write_text('\n'.join(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps(m)}}) for m in messages)+'\n')
        log.with_suffix('.prompt.txt').write_text(json.dumps(ctx)+'\n')
        with patch.object(runner,'provider_scope',return_value=ctx['competing_product']),patch.object(runner,'codex_call',side_effect=AssertionError('No model')):
            runner.recover_listing_events(argparse.Namespace(id=state['id']))
            first=(base/'extracted.json').read_bytes()
            runner.recover_listing_events(argparse.Namespace(id=state['id']))
        saved=runner.read_state(base)
        self.assertEqual(saved['phase'],'paused_error')
        self.assertEqual(saved['jobs'][key]['attempts'],1)
        self.assertEqual((base/'extracted.json').read_bytes(),first)
        self.assertEqual(saved['jobs'][key]['stream_recovery']['positions'],[10])
