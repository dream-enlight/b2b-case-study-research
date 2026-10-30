import argparse,copy,json,unittest
from unittest.mock import patch
import test_efficiency as fixtures
import runner,workspace,finish_collected as finish


class FinishCollectedTests(unittest.TestCase):
    setUp=fixtures.EfficiencyTests.setUp
    tearDown=fixtures.EfficiencyTests.tearDown
    cmd=fixtures.EfficiencyTests.cmd
    state=fixtures.EfficiencyTests.state
    fixture=fixtures.EfficiencyTests.fixture
    record=fixtures.EfficiencyTests.record
    result=fixtures.EfficiencyTests.result
    # Reuse fixture helpers without re-running the parent test suite here.
    def prepared(self):
        base,cases=self.fixture(3);s=self.state()
        runner.commit_case_result(base,s,'old',cases,self.result(cases[0]))
        s['listing_universes']={'Beta Software':{'entries':[dict(cases[1],listing_position=1,listing_url='https://stories.example.com/customer-stories')],
            'complete':False,'page':1,'cursor':'more'}}
        runner.save(base,s)
        evidence=base/'evidence.txt';evidence.write_text(cases[1]['url']+' Customer 1')
        manifest=base/'recovery.json';runner.atomic_json(manifest,[{'provider':'Beta Software','position':1,'url':cases[1]['url'],
            'evidence':[{'path':'evidence.txt','quote':evidence.read_text()}]}])
        return base,cases,manifest

    def start(self,manifest):
        finish.start(runner,argparse.Namespace(id='test-company',reason='Explicitly stop to control time and usage.',recovery_file=str(manifest)))

    def test_backup_partial_coverage_and_completed_evidence_preserved(self):
        b,c,m=self.prepared();before=(b/'extracted.json').read_bytes();progress=runner.discovery_path(b).read_bytes()
        self.start(m);s=self.state();self.assertEqual(s['phase'],'finish_collected')
        self.assertTrue((__import__('pathlib').Path(s['early_completion']['backup'])/'run.zip').exists())
        self.assertFalse(s['listing_universes']['Beta Software']['complete'])
        self.assertEqual((b/'extracted.json').read_bytes(),before);self.assertEqual(runner.discovery_path(b).read_bytes(),progress)
        self.start(m);self.assertEqual(self.state()['early_completion'],s['early_completion'])

    def test_recovery_then_normal_integrity_finalization_and_resume(self):
        b,c,m=self.prepared();self.start(m);s=self.state();before=runner.read_json(b/'extracted.json')[c[0]['id']]
        with patch.object(runner,'invoke',return_value={'results':[self.result(c[1])]}),patch.object(runner,'discovery_step',side_effect=AssertionError('No discovery')):
            finish.step(runner,b,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'stage3');self.assertEqual(runner.read_json(b/'extracted.json')[c[0]['id']],before)
        with patch.object(workspace,'ensure_sync',return_value=True):runner.step(b,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'finalize_sheet');self.assertEqual(runner.read_json(b/'final_snapshot.json')['complete'],2)
        self.assertIn('partial and uneven',s['screening_summary']['disclosure'])
        self.assertEqual(s['early_completion']['outcomes'][0]['association'],'content-confirmed; listing href unverified')

    def test_interrupted_attempt_reuses_receipt_without_second_call(self):
        b,c,m=self.prepared();self.start(m);s=self.state();p=s['early_completion'];key=p['recovery_key']
        s['jobs'][key]={'attempts':1,'status':'running'};runner.save(b,s)
        runner.commit_case_result(b,s,key,[c[1]],self.result(c[1]))
        with patch.object(runner,'invoke',side_effect=AssertionError('Never reread')):finish.step(runner,b,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'stage3');self.assertEqual(len(runner.read_json(b/'extracted.json')),2)

    def test_incomplete_attempt_is_unresolved_and_does_not_block(self):
        b,c,m=self.prepared();self.start(m);s=self.state();s['jobs'][s['early_completion']['recovery_key']]={'attempts':1,'status':'running'}
        with patch.object(runner,'invoke',side_effect=AssertionError('Never retry')):finish.step(runner,b,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'stage3');self.assertEqual(s['early_completion']['outcomes'][0]['decision'],'unresolved')
        self.assertEqual(len(runner.read_json(b/'extracted.json')),1)

    def test_tampered_completed_record_rejected_before_transition(self):
        b,c,m=self.prepared();self.start(m);s=self.state();records=runner.read_json(b/'extracted.json');records[c[0]['id']]['customer']='Altered'
        runner.atomic_json(b/'extracted.json',records)
        with self.assertRaisesRegex(runner.RunError,'receipt/extraction mismatch'):finish.step(runner,b,s,60,'FORBIDDEN')

    def test_missing_receipt_and_unbacked_candidate_rejected(self):
        b,c,m=self.prepared();runner.case_receipt_path(b,self.state(),c[0]['id']).unlink()
        with self.assertRaisesRegex(runner.RunError,'receipt'):self.start(m)
        self.assertNotIn('early_completion',self.state())

    def test_existing_sheet_prefix_is_preserved_and_publication_not_repeated(self):
        b,c,m=self.prepared();s=self.state();s['workspace_verified_ids']=[c[0]['id']];runner.save(b,s)
        self.start(m);s=self.state();s['jobs'][s['early_completion']['recovery_key']]={'attempts':1,'status':'running'}
        finish.step(runner,b,s,60,'FORBIDDEN');records=runner.ordered_records(b)
        self.assertEqual([r['id'] for r in records],[c[0]['id']])
        with patch.object(workspace,'request',side_effect=AssertionError('No duplicate write')):
            # Existing publication integrity uses the exact verified prefix.
            s['workspace_sheet']={'id':'sheet','url':'https://docs.google.com/spreadsheets/d/sheet/edit','row_count':1000,'title':'Saved','tab':'Case studies'}
            s['workspace_header_verified']=True
            self.assertTrue(workspace.ensure_sync(b,s,records,runner.atomic_json))

    def test_future_first_thirty_policy_is_unchanged(self):
        b,c,m=self.prepared();s=self.state();s['research_policy']['first_listing_entries']=30;runner.save(b,s);self.start(m)
        self.assertEqual(self.state()['research_policy']['first_listing_entries'],30)

    def test_unbacked_url_rejected_without_state_mutation(self):
        b,c,m=self.prepared();items=runner.read_json(m);items[0]['url']='https://guessed.example.com/story';runner.atomic_json(m,items)
        before=(b/'state.json').read_bytes()
        with self.assertRaisesRegex(runner.RunError,'URL must occur'):self.start(m)
        self.assertEqual((b/'state.json').read_bytes(),before)

    def test_quota_pause_resumes_without_repeating_recovery(self):
        b,c,m=self.prepared();self.start(m);s=self.state()
        def quota(*args):
            s['jobs'][s['early_completion']['recovery_key']]={'attempts':1,'status':'paused','error_kind':'quota'}
            s.update(phase='paused_quota',paused_from='finish_collected');runner.save(b,s)
            return None
        with patch.object(runner,'invoke',side_effect=quota):self.assertFalse(finish.step(runner,b,s,60,'FORBIDDEN'))
        self.assertEqual(s['phase'],'paused_quota')
        self.assertEqual(self.cmd('resume','test-company','--confirm-reset').returncode,0);s=self.state()
        with patch.object(runner,'invoke',side_effect=AssertionError('No retry')):finish.step(runner,b,s,60,'FORBIDDEN')
        self.assertEqual(s['phase'],'stage3')
