import json,os,subprocess,sys,tempfile,unittest,time,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
import workspace
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
FAKE=str(ROOT/'tests/fake_codex.py')

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.orig=runner.RUNS
        runner.RUNS=Path(self.tmp.name)
    def tearDown(self):
        runner.RUNS=self.orig
        self.tmp.cleanup()
    def cmd(self,*args,env=None):
        program=['python3',str(ROOT/'runner.py'),*args]
        e=os.environ.copy()
        if env:e.update(env)
        # need point to temp runs for subprocess, so runner accepts environment override below
        e['RESEARCH_RUNS_DIR']=str(runner.RUNS)
        result=subprocess.run(program,text=True,capture_output=True,env=e)
        # Existing tests are regression fixtures for pre-upgrade runs. New-run
        # policy and migrated-run behavior are exercised explicitly below.
        if not getattr(self,'modern',False) and (args[0]=='init' or (args[0]=='app' and args[1].startswith('Research '))):
            for path in runner.RUNS.glob('*/state.json'):
                state=runner.read_json(path);state.pop('research_policy',None);state.pop('analysis_policy',None);state.pop('workspace_policy',None);runner.atomic_json(path,state)
        return result
    def state(self,rid='test-company'):
        return runner.read_state(runner.run_dir(rid))
    def dispatch(self,p,rid='test-company',mutate=None):
        self.assertEqual(self.cmd('workspace',rid,'begin','--request-id',p['id']).returncode,0)
        result=self.google(p,rid)
        if mutate:result=mutate(result)
        path=runner.run_dir(rid)/'tool-response.json';runner.atomic_json(path,result)
        return self.cmd('workspace',rid,'ack','--request-id',p['id'],'--response',str(path))
    def google(self,p,rid):
        """Explicit offline connector fixture. Never used by production code."""
        self.cells=getattr(self,'cells',{})
        k=p['kind'];d=p['details']
        if k in ('sheet_reconcile_copy','sheet_reconcile_copy_verify'):return {'id':'offline-sheet-backup','mimeType':'application/vnd.google-apps.spreadsheet','url':'https://docs.google.com/spreadsheets/d/offline-sheet-backup/edit'}
        if k=='sheet_create':return {'id':'offline-sheet','mimeType':'application/vnd.google-apps.spreadsheet','url':'https://docs.google.com/spreadsheets/d/offline-sheet/edit'}
        if k=='sheet_metadata':return {'spreadsheetId':'offline-sheet','sheets':[{'properties':{'title':'Case studies','sheetId':7,'gridProperties':{'rowCount':1000,'columnCount':5}}}]}
        if k in ('sheet_write','sheet_reconcile_write'):
            self.write_count=getattr(self,'write_count',0)+1
            for index,row in enumerate(d['rows'],d['start']):self.cells[index]=row
            return {'spreadsheetId':'offline-sheet','replies':[]}
        if k.startswith('sheet_'):
            rows=[runner.HEADERS if i==0 else self.cells.get(i,['']*5) for i in range(d['start'],d['start']+d['count'])]
            return {'spreadsheetId':'offline-sheet','sheets':[{'properties':{'sheetId':7},'data':[{'startRow':d['start'],'rowData':[{'values':[{'userEnteredValue':{'stringValue':c}} for c in r]} for r in rows]}]}]}
        if k=='doc_create':return {'id':'offline-doc','mimeType':'application/vnd.google-apps.document','url':'https://docs.google.com/document/d/offline-doc/edit'}
        if k=='doc_layout':
            self.doc_layout=True
            return {'documentId':'offline-doc','replies':[]}
        if k=='doc_verify':
            e=runner.read_json(runner.run_dir(rid)/'report_expected.json')
            heading_labels={line.lstrip('#').strip() for line in (runner.run_dir(rid)/'report.md').read_text().splitlines() if line.startswith('#')}
            content=[];index=1
            for line in e['text'].splitlines():
                value=line+'\n';end=index+len(value.encode('utf-16-le'))//2
                style={'namedStyleType':'HEADING_1' if line in workspace.REPORT_SECTIONS else 'HEADING_2' if line in heading_labels else 'NORMAL_TEXT'}
                if getattr(self,'doc_layout',False) and line in workspace.REPORT_SECTIONS[1:]:style['pageBreakBefore']=True
                content.append({'startIndex':index,'endIndex':end,'paragraph':{'elements':[{'textRun':{'content':value}}],'paragraphStyle':style}});index=end
            content.extend([{'tableRows':[]} for _ in range(e['tables'])])
            return {'documentId':'offline-doc','revisionId':'offline-revision','tabs':[{'tabId':'offline-tab','body':{'content':content}}]}
        self.fail('Unexpected offline action '+k)
    def pump(self,rid='test-company',until=None,env=None):
        for _ in range(60):
            s=self.state(rid)
            if until and until(s):return s
            if s['phase']=='complete' or s['phase'].startswith('paused'):return s
            if s.get('workspace_pending'):
                ack=self.dispatch(s['workspace_pending'],rid);self.assertEqual(ack.returncode,0,ack.stderr)
            elif s['phase'] in ('finalize_sheet','reconcile_sheet'):
                # Observe the transition into Stage 4 before starting its worker.
                runner.step(runner.run_dir(rid),s,60,FAKE)
            else:
                result=self.cmd('run',rid,'--codex',FAKE,'--max-tasks','2',env=env)
                self.assertEqual(result.returncode,0,result.stderr)
        self.fail('Offline orchestration did not terminate')
    def start(self,env=None):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE,env=env)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,env=env)
    def test_doc_verifier_distinguishes_subheading_from_main_overview(self):
        base=runner.run_dir('doc-check');base.mkdir(parents=True)
        labels=list(workspace.REPORT_SECTIONS);text='Overview\nOverview\n'+'\n'.join(labels[1:])+'\n'
        runner.atomic_json(base/'report_expected.json',{'text':text,'tables':0,'headings':6})
        content=[];index=1
        for n,label in enumerate(['Overview','Overview',*labels[1:]]):
            end=index+len(label)+1
            content.append({'startIndex':index,'endIndex':end,'paragraph':{'elements':[{'textRun':{'content':label+'\n'}}],
                'paragraphStyle':{'namedStyleType':'HEADING_2' if n==1 else 'HEADING_1'}}})
            index=end
        state={'workspace_document':{'id':'doc'}}
        pending={'kind':'doc_verify','details':{}}
        workspace.apply_response(base,state,pending,{'documentId':'doc','revisionId':'r','tabs':[{'tabId':'t','body':{'content':content}}]},runner.atomic_json)
        self.assertEqual(state['workspace_pending']['kind'],'doc_layout')
        self.assertEqual(len(state['workspace_pending']['arguments']['requests']),5)

    def test_quota_stops_without_retry_and_needs_manual_reset(self):
        self.assertEqual(self.cmd('init','--company','Test Company','--website','https://example.com').returncode,0)
        r=self.cmd('run','test-company','--codex',FAKE,env={'FAKE_MODE':'quota'})
        self.assertEqual(r.returncode,0)
        s=runner.read_json(runner.run_dir('test-company')/'state.json')
        self.assertEqual(s['phase'],'paused_quota')
        self.assertEqual(s['jobs']['stage1']['attempts'],1)
        self.assertIn('HALTED',self.cmd('run','test-company','--codex',FAKE).stdout)
        self.assertNotEqual(self.cmd('resume','test-company').returncode,0)
        self.assertEqual(self.cmd('resume','test-company','--confirm-reset').returncode,0)
    def test_all_seven_stages_and_verified_workspace_boundary(self):
        self.assertEqual(self.cmd('init','--company','Test Company','--website','https://example.com').returncode,0)
        self.assertIn('APPROVAL REQUIRED',self.cmd('run','test-company','--codex',FAKE).stdout)
        self.assertEqual(self.cmd('approve','test-company','--names','Beta Software').returncode,0)
        self.assertEqual(self.cmd('run','test-company','--codex',FAKE).returncode,0)
        base=runner.run_dir('test-company')
        s=runner.read_json(base/'state.json')
        self.assertEqual(s['phase'],'stage3')
        self.assertEqual(s['workspace_pending']['kind'],'sheet_create')
        self.assertFalse((base/'analysis_4.json').exists())
        s=self.pump()
        self.assertEqual(s['phase'],'complete')
        self.assertTrue(s['document_verified'])
        inv=runner.read_json(base/'inventory.json');self.assertEqual(len(inv),2)
        rec=runner.read_json(base/'extracted.json');self.assertEqual(len(rec),2)
        import csv
        with (base/'case_studies.csv').open(newline='') as fp:
            rows=list(csv.reader(fp))
        self.assertEqual(len(rows),3)
        self.assertEqual(s['approved_providers'],['Test Company','Beta Software'])
        before=copy.deepcopy(s['jobs'])
        self.assertIn('STOP: complete',self.cmd('run','test-company','--codex',FAKE).stdout)
        self.assertEqual(self.state()['jobs'],before)
        self.assertEqual(len(s['workspace_verified_ids']),2)
        for n in range(4,7):self.assertTrue((base/f'analysis_{n}.json').exists())
        self.assertEqual(len(self.cells),2)
    def test_transient_error_pauses_instead_of_looping(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        self.cmd('run','test-company','--codex',FAKE,env={'FAKE_MODE':'offline'})
        s=runner.read_json(runner.run_dir('test-company')/'state.json')
        self.assertEqual(s['phase'],'paused_error')
        self.assertEqual(s['jobs']['stage1']['attempts'],1)

    def test_streaming_quota_kills_worker_before_its_hang(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        began=time.monotonic()
        self.cmd('run','test-company','--codex',FAKE,env={'FAKE_MODE':'quota_hang'})
        self.assertLess(time.monotonic()-began,5)
        self.assertEqual(self.state()['phase'],'paused_quota')

    def test_dispatched_create_never_repeats_and_actual_receipt_can_recover(self):
        self.start();p=self.state()['workspace_pending']
        self.assertEqual(self.cmd('workspace','test-company','begin','--request-id',p['id']).returncode,0)
        self.assertNotEqual(self.cmd('workspace','test-company','begin','--request-id',p['id']).returncode,0)
        self.assertNotEqual(self.cmd('workspace','test-company','retry','--request-id',p['id']).returncode,0)
        path=runner.run_dir('test-company')/'receipt.json';runner.atomic_json(path,self.google(p,'test-company'))
        self.assertEqual(self.cmd('workspace','test-company','ack','--request-id',p['id'],'--response',str(path)).returncode,0)
        self.assertTrue(self.state()['workspace_sheet']['id'])

    def test_uncertain_write_reconciles_exact_rows_without_duplication(self):
        self.start();s=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_write')
        p=s['workspace_pending']
        self.cmd('workspace','test-company','begin','--request-id',p['id'])
        self.google(p,'test-company') # remote write succeeded, response lost
        self.cmd('workspace','test-company','retry','--request-id',p['id'])
        p=self.state()['workspace_pending'];self.assertEqual(p['kind'],'sheet_preflight')
        self.assertEqual(self.dispatch(p).returncode,0)
        self.assertFalse(self.state().get('workspace_pending'))
        self.assertEqual(len(self.state()['workspace_verified_ids']),2)
        self.assertEqual(len(self.cells),2)

    def test_conflicting_sheet_rows_pause_without_overwrite(self):
        self.start();s=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_preflight')
        self.cells[1]=['user edit']*5
        self.assertNotEqual(self.dispatch(s['workspace_pending']).returncode,0)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(self.cells[1],['user edit']*5)

    def test_readback_mismatch_and_connector_unclassified_429_pause(self):
        self.start();s=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_verify')
        p=s['workspace_pending']
        result=self.dispatch(p,mutate=lambda r:{'isError':True,'content':[{'type':'text','text':'HTTP 429 quota exceeded'}]})
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(len(self.state().get('workspace_verified_ids',[])),0)

    def test_actual_429_retry_warnings_pause_without_quota_claim_or_retry(self):
        warnings=runner.read_json(ROOT/'tests/fixtures/codex_429_warnings.json')
        for n,raw in enumerate(warnings,1):
            with self.subTest(failure=n):
                rid='rate-limit-'+str(n)
                self.cmd('init','--id',rid,'--company','Test Company','--website','https://example.com')
                marker=Path(self.tmp.name)/('retry-'+str(n))
                self.cmd('run',rid,'--codex',FAKE,env={'FAKE_MODE':'generic429_warning_'+str(n),'FAKE_RETRY_MARKER':str(marker)})
                state=self.state(rid);job=state['jobs']['stage1']
                self.assertEqual(state['phase'],'paused_error');self.assertEqual(job['error_kind'],'rate_limit')
                self.assertEqual(job['attempts'],1);self.assertFalse(marker.exists())
                self.assertIn(raw,job['last_error']);self.assertIn('exhaustion is not established',state['pause_reason'])
                self.assertNotIn('allowance resets',state['pause_reason']);self.assertNotIn('five-hour',state['pause_reason'])
                self.assertEqual(next((runner.run_dir(rid)/'logs').glob('*.stderr.txt')).read_text(),raw)
                before=copy.deepcopy(state['jobs'])
                self.assertIn('HALTED',self.cmd('run',rid,'--codex',FAKE).stdout)
                self.assertEqual(self.state(rid)['jobs'],before)
                # Manual resume needs no claim that subscription allowance reset.
                self.assertEqual(self.cmd('resume',rid).returncode,0)
                self.assertEqual(self.state(rid)['jobs'],before)

    def test_rate_limit_event_and_routine_retry_warning_are_not_usage_exhaustion(self):
        for mode in ('rate_limit_event','retry_warning'):
            rid=mode.replace('_','-')
            self.cmd('init','--id',rid,'--company','Test Company','--website','https://example.com')
            self.cmd('run',rid,'--codex',FAKE,env={'FAKE_MODE':mode})
            state=self.state(rid)
            self.assertEqual(state['jobs']['stage1']['attempts'],1)
            if mode=='rate_limit_event':
                self.assertEqual(state['phase'],'paused_error');self.assertEqual(state['jobs']['stage1']['error_kind'],'rate_limit')
                self.assertIn('rate_limit_exceeded',state['pause_reason'])
            else:self.assertEqual(state['phase'],'awaiting_approval')

    def test_only_explicit_usage_exhaustion_is_classified_as_quota(self):
        for text in ['HTTP 429','Too many requests','rate_limit_exceeded','quota exceeded','insufficient credits','limit_reached']:
            self.assertFalse(runner.quota_detect(text),text)
        for text in ['UsageLimitExceeded','usage_limit_exceeded','You’ve hit your usage limit.','Usage limit reached; resets in an hour','weekly limit reached']:
            self.assertEqual(runner.limit_kind(text),'quota',text)
        self.assertEqual(runner.limit_kind('HTTP 429: UsageLimitExceeded'),'quota')
        self.assertEqual(runner.limit_kind('{"status_code": 429}'),'rate_limit')
        self.assertIsNone(runner.limit_kind('Invalid source URL: https://example.com/cases/429/'))

    def test_analysis_isolated_and_has_only_finalized_sheet_inputs(self):
        self.start();self.pump(until=lambda s:s['phase']=='stage4')
        trace=Path(self.tmp.name)/'trace.jsonl'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        calls=[json.loads(x) for x in trace.read_text().splitlines()]
        self.assertEqual(len(calls),1)
        args=calls[0]['args'];self.assertIn('--ignore-user-config',args)
        self.assertIn('web_search="disabled"',args);self.assertIn('features.shell_tool=false',args)
        self.assertNotEqual(calls[0]['cwd'],str(ROOT))
        self.assertIn('finalized_google_sheet',calls[0]['prompt'])
        self.assertNotIn('assigned_cases',calls[0]['prompt'])

    def test_tools_in_analysis_are_rejected_and_completed_batches_remain(self):
        self.start();self.pump(until=lambda s:s['phase']=='stage4')
        before=(runner.run_dir('test-company')/'extracted.json').read_bytes()
        self.cmd('run','test-company','--codex',FAKE,env={'FAKE_MODE':'tool_use'})
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(before,(runner.run_dir('test-company')/'extracted.json').read_bytes())

    def test_large_analysis_interrupt_resumes_only_unclassified_sheet_records(self):
        import analysis_pipeline
        self.start(env={'FAKE_CASES':'25'});self.pump(until=lambda s:s['phase']=='stage4')
        base=runner.run_dir('test-company');original=(base/'extracted.json').read_bytes()
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'analysis_interrupt'})
        self.assertEqual(self.state()['phase'],'paused_quota')
        database=workspace.frozen_database(base,self.state())
        saved=analysis_pipeline.classifications(base,database);self.assertEqual(len(saved),2)
        self.cmd('resume','test-company','--confirm-reset')
        trace=Path(self.tmp.name)/'resume-trace.jsonl'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        assignment=json.loads(json.loads(trace.read_text().splitlines()[0])['prompt'].split('TASK ASSIGNMENT (machine generated):\n')[1].split('\n\nRUNNER EXECUTION OVERRIDE:')[0])
        self.assertEqual(len(assignment['records']),20)
        self.assertTrue(set(x['id'] for x in assignment['records']).isdisjoint(saved))
        self.assertEqual(original,(base/'extracted.json').read_bytes())
        self.assertEqual(self.pump()['phase'],'complete')
        audit=runner.read_json(analysis_pipeline.root(base,database)/'coverage_audit.json')
        self.assertEqual(audit['eligible_records'],50);self.assertEqual(audit['classified_records'],50)
        self.assertEqual(len(audit['case_to_profile']),50);self.assertEqual(audit['distinct_profiles'],1)

    def test_final_snapshot_and_analysis_tampering_are_detected(self):
        self.start();self.pump(until=lambda s:s['phase']=='stage4')
        base=runner.run_dir('test-company');snap=runner.read_json(base/'finalized_sheet.json')
        snap['rows'][0][1]='tampered';runner.atomic_json(base/'finalized_sheet.json',snap)
        self.cmd('run','test-company','--codex',FAKE)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('checksum',self.state()['pause_reason'])

    def test_path_traversal_and_invalid_timeout_are_rejected(self):
        self.assertNotEqual(self.cmd('status','../escape').returncode,0)
        self.assertNotEqual(self.cmd('run','x','--timeout','0').returncode,0)

    def test_profile_counts_and_provider_group_batches_stay_bounded(self):
        inventory={p:[{'id':f'{p}{i}'} for i in range(n)] for p,n in [('A',21),('B',3),('C',22)]}
        batches=runner.compile_batches(inventory)
        self.assertEqual(sum(len(b['cases']) for b in batches),46)
        self.assertTrue(all(0<len(b['cases'])<=20 for b in batches))

    def test_multiple_extraction_batches_sync_progressively_once(self):
        self.start(env={'FAKE_CASES':'25'})
        result=self.pump()
        self.assertEqual(result['phase'],'complete')
        self.assertEqual(len(result['workspace_verified_ids']),50)
        self.assertEqual(len(self.cells),50)
        self.assertEqual(self.write_count,4)
        batches=runner.read_json(runner.run_dir('test-company')/'batches.json')
        self.assertTrue(all(len(b['cases'])<=20 for b in batches))

    def test_inaccessible_cases_are_preserved_and_zero_evidence_blocks_analysis(self):
        self.start();s=self.pump(env={'FAKE_MODE':'inaccessible'})
        self.assertEqual(s['phase'],'paused_error')
        self.assertIn('No accessible',s['pause_reason'])
        self.assertEqual(len(self.cells),2)
        self.assertTrue(all(r[4].startswith('INACCESSIBLE') for r in self.cells.values()))
        self.assertFalse((runner.run_dir('test-company')/'analysis_4.json').exists())

    def test_incomplete_extraction_is_not_checkpointed(self):
        self.start();s=self.pump(env={'FAKE_MODE':'missing_record'})
        self.assertEqual(s['phase'],'paused_error')
        self.assertIn('coverage',s['pause_reason'])
        self.assertFalse((runner.run_dir('test-company')/'extracted.json').exists())

    def test_successful_worker_response_survives_interruption_before_stage_commit(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        base=runner.run_dir('test-company');state=runner.read_state(base)
        result={'competitors':[]}
        with patch.object(runner,'codex_call',return_value=result) as call:
            runner.invoke(base,state,1,'stage1',{},60,FAKE)
            saved=runner.read_state(base)
            self.assertEqual(runner.invoke(base,saved,1,'stage1',{},60,FAKE),result)
            self.assertEqual(call.call_count,1)

    def test_extra_sheet_rows_block_finalization(self):
        self.start();s=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_finalize')
        self.cells[600]=['unexpected duplicate']*5
        self.assertNotEqual(self.dispatch(s['workspace_pending']).returncode,0)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertFalse((runner.run_dir('test-company')/'finalized_sheet.json').exists())

    def test_wrong_readback_identity_is_rejected(self):
        self.start();s=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_header')
        def wrong(r):r['spreadsheetId']='another-file';return r
        self.assertNotEqual(self.dispatch(s['workspace_pending'],mutate=wrong).returncode,0)
        self.assertEqual(self.state()['phase'],'paused_error')

    def test_unapproved_competitor_does_not_start_discovery(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.assertNotEqual(self.cmd('app','Approve these competitors: Unapproved','--codex',FAKE).returncode,0)
        self.assertEqual(self.state()['phase'],'awaiting_approval')
        self.assertFalse((runner.run_dir('test-company')/'inventory.json').exists())

    def test_app_resume_reuses_completed_work(self):
        self.start();before=copy.deepcopy(self.state()['jobs'])
        self.cmd('app','Resume Test Company','--codex',FAKE)
        self.assertEqual(self.state()['jobs'],before)
        self.assertEqual(self.state()['workspace_sequence'],1)

    def scoped_discovery(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1')
        base=runner.run_dir('test-company')
        criteria=Path(self.tmp.name)/'scope.md';criteria.write_text('Only customer stories proving the scoped problem, intervention, and documented result.')
        result=self.cmd('set-scope','test-company','--file',str(criteria))
        self.assertEqual(result.returncode,0,result.stderr)
        return base,criteria

    def test_scoped_discovery_rescreens_without_reusing_or_rewriting_old_inventory(self):
        base,criteria=self.scoped_discovery()
        old=(base/'inventory.json').read_bytes()
        trace=Path(self.tmp.name)/'scope-trace.jsonl'
        result=self.cmd('run','test-company','--codex',FAKE,'--max-tasks','2',env={'FAKE_TRACE':str(trace)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual((base/'inventory.json').read_bytes(),old)
        scoped=runner.read_json(runner.inventory_path(base))
        self.assertEqual(set(scoped),{'Test Company','Beta Software'})
        decisions=runner.read_json(runner.screening_path(base))
        self.assertTrue(all(c['decision']=='relevant' and c['evidence'] for c in decisions.values()))
        calls=[json.loads(x) for x in trace.read_text().splitlines()]
        self.assertEqual(len(calls),2)
        self.assertTrue(all(criteria.read_text() in c['prompt'] for c in calls))
        self.assertEqual(self.cmd('set-scope','test-company','--file',str(criteria)).returncode,0)
        criteria.write_text('Different criteria')
        self.assertNotEqual(self.cmd('set-scope','test-company','--file',str(criteria)).returncode,0)

    def test_scoped_discovery_rejects_missing_relevance_before_checkpointing(self):
        base,_=self.scoped_discovery()
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env={'FAKE_MODE':'missing_relevance'})
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('Invalid lightweight screening evidence',self.state()['pause_reason'])
        self.assertFalse(runner.inventory_path(base).exists())

    def test_scope_cannot_change_existing_extraction_or_workspace_work(self):
        self.start()
        criteria=Path(self.tmp.name)/'scope.md';criteria.write_text('Scoped customer stories only.')
        before=copy.deepcopy(self.state())
        self.assertNotEqual(self.cmd('set-scope','test-company','--file',str(criteria)).returncode,0)
        self.assertEqual(self.state(),before)
        self.assertFalse((runner.run_dir('test-company')/'research_scope.json').exists())

    def screening_fixture(self,trace=None):
        env={'FAKE_MODE':'multi_product'}
        if trace:env['FAKE_TRACE']=str(trace)
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE,env=env)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env=env)
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        self.assertEqual(self.state()['phase'],'stage2')
        return runner.run_dir('test-company'),env

    def traced_assignments(self,path):
        return [json.loads(c['prompt'].split('TASK ASSIGNMENT (machine generated):\n')[1].split('\n\nRUNNER EXECUTION OVERRIDE:')[0])
                for c in map(json.loads,path.read_text().splitlines())]

    def test_multi_product_screening_extracts_once_and_keeps_exclusions_out_of_sheet(self):
        trace=Path(self.tmp.name)/'screening-trace.jsonl'
        base,env=self.screening_fixture(trace)
        initial=runner.read_json(runner.screening_path(base))
        excluded=next(c for c in initial.values() if c['provider']=='Beta Software' and c['url'].endswith('/1'))
        self.assertEqual(excluded['decision'],'excluded')
        self.assertIn('separate business line',excluded['reason'])
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        early=runner.read_json(base/'extracted.json')
        self.assertEqual(len(early),1)
        self.assertEqual(self.state()['phase'],'stage2')
        self.assertFalse(self.state().get('workspace_pending'))
        self.assertFalse(self.state().get('workspace_sheet'))
        early_id=next(iter(early))
        result=self.pump(env=env)
        self.assertEqual(result['phase'],'complete')
        self.assertEqual(runner.read_json(base/'extracted.json')[early_id],early[early_id])
        self.assertEqual(len(self.cells),3)
        self.assertEqual(len(set(result['workspace_verified_ids'])),3)
        self.assertEqual(runner.read_json(base/'finalized_sheet.json')['screening_summary'],
                         {'relevant':3,'excluded':2,'unresolved':1})
        decisions=runner.read_json(runner.screening_path(base))
        beta={c['url'].rsplit('/',1)[-1]:c for c in decisions.values() if c['provider']=='Beta Software'}
        self.assertEqual({k:v['decision'] for k,v in beta.items()},
                         {'0':'relevant','1':'excluded','2':'relevant','3':'excluded','4':'unresolved'})
        self.assertEqual(beta['3']['basis'],'substantive')
        calls=self.traced_assignments(trace)
        discovery=next(c for c in calls if c.get('approved_provider')=='Beta Software')
        self.assertEqual(discovery['competing_product']['product'],'Beta Platform')
        reviews=[c['review_case']['url'] for c in calls if c.get('task')=='review_case']
        self.assertEqual(len(reviews),3)
        self.assertFalse(any(url.endswith('/1') for url in reviews))
        stage3=[c for c in calls if 'assigned_cases' in c]
        self.assertTrue(stage3)
        self.assertTrue(all(c['id']!=early_id for task in stage3 for c in task['assigned_cases']))
        self.assertTrue(all(not any(c['provider']=='Beta Software' and c['url'].endswith('/'+i)
                                   for i in ('1','2','3','4')) for task in stage3 for c in task['assigned_cases']))

    def test_stage2_early_records_append_to_existing_sheet_before_more_research(self):
        base,env=self.screening_fixture()
        state=self.state();target=runner.read_json(base/'inventory.json')['Test Company'][0]
        record={'provider':target['provider'],'source_url':target['url'],'customer':'Acme',
                'people':'Unavailable in synthetic source.','company_profile':'Synthetic vendor.',
                'buying_situation':'Synthetic scoped need.','status':'complete','note':''}
        runner.persist_records(base,[target],[record])
        state.update(workspace_sheet={'id':'offline-sheet','url':'https://docs.google.com/spreadsheets/d/offline-sheet/edit',
                                     'tab':'Case studies','sheet_id':7,'row_count':1000},
                     sheet_url='https://docs.google.com/spreadsheets/d/offline-sheet/edit',
                     workspace_header_verified=True,workspace_verified_ids=[target['id']])
        runner.save(base,state)
        self.cells={1:workspace.rows_for(runner.ordered_records(base))[0]}
        original=list(self.cells[1])
        state=self.pump(env=env,until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_preflight')
        self.assertEqual(state['phase'],'stage2')
        self.assertEqual(state['workspace_pending']['details']['start'],2)
        self.assertEqual(state['workspace_sheet']['id'],'offline-sheet')
        result=self.pump(env=env)
        self.assertEqual(result['phase'],'complete')
        self.assertEqual(self.cells[1],original)
        self.assertEqual(result['workspace_verified_ids'][0],target['id'])
        self.assertEqual(len(self.cells),3)
        self.assertEqual(self.write_count,2)

    def test_stage2_review_receipt_replays_after_interrupted_commit_without_new_read(self):
        base,_=self.screening_fixture()
        real_atomic=runner.atomic_json
        def interrupted(path,value):
            if path==runner.screening_path(base) and any(c.get('basis')=='substantive' for c in value.values()):
                raise OSError('Synthetic interruption after extraction, before screening commit')
            return real_atomic(path,value)
        with patch.object(runner,'codex_call',wraps=runner.codex_call) as worker:
            with patch.object(runner,'atomic_json',side_effect=interrupted):
                with self.assertRaises(OSError):runner.step(base,runner.read_state(base),60,FAKE)
            saved=(base/'extracted.json').read_bytes()
            self.assertEqual(len(runner.read_json(base/'extracted.json')),1)
            self.assertTrue(runner.step(base,runner.read_state(base),60,FAKE))
            self.assertEqual(worker.call_count,1)
        self.assertEqual((base/'extracted.json').read_bytes(),saved)
        self.assertEqual(len(runner.read_json(base/'inventory.json')['Beta Software']),2)

    def test_substantive_review_requires_complete_assigned_record(self):
        base,env=self.screening_fixture()
        env['FAKE_MODE']='review_wrong_identity'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('Unexpected/duplicate extraction',self.state()['pause_reason'])
        self.assertFalse((base/'extracted.json').exists())
        self.assertTrue(any(c['decision']=='needs_review' for c in runner.read_json(runner.screening_path(base)).values()))

    def test_interrupted_discovery_commit_recovers_all_decisions_without_research(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1')
        base=runner.run_dir('test-company');real_atomic=runner.atomic_json
        def interrupted(path,value):
            if path==runner.inventory_path(base):raise OSError('Synthetic interruption after screening ledger')
            return real_atomic(path,value)
        with patch.dict(os.environ,{'FAKE_MODE':'multi_product'}):
            with patch.object(runner,'atomic_json',side_effect=interrupted):
                with self.assertRaises(OSError):runner.step(base,self.state(),60,FAKE)
        decisions=runner.read_json(runner.screening_path(base))
        self.assertEqual(sum(c['provider']=='Beta Software' for c in decisions.values()),5)
        self.assertNotIn('Beta Software',runner.read_json(base/'inventory.json'))
        with patch.object(runner,'codex_call',side_effect=AssertionError('Do not repeat discovery or start another review')):
            # An existing Sheet forces a sync stop after reconciliation, before
            # any next review. No connector is actually called by this fixture.
            state=self.state();state['workspace_sheet']={'id':'offline-sheet'};runner.save(base,state)
            self.assertFalse(runner.step(base,state,60,FAKE))
        restored=runner.read_json(base/'inventory.json')['Beta Software']
        self.assertEqual([c['url'].rsplit('/',1)[-1] for c in restored],['0'])
        key=next(c['discovery_key'] for c in decisions.values() if c['provider']=='Beta Software')
        self.assertEqual(self.state()['jobs'][key]['status'],'complete')

    def test_relevant_review_without_full_record_is_not_marked_complete(self):
        base,env=self.screening_fixture();env['FAKE_MODE']='review_missing_record'
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('requires a complete extraction',self.state()['pause_reason'])
        self.assertFalse((base/'extracted.json').exists())

    def test_legacy_cached_inventory_is_committed_without_researching_again(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        base=runner.run_dir('test-company');state=self.state()
        state.update(phase='stage2',approved_providers=['Test Company'])
        key='inventory_test-company_'+runner.hashlib.sha256(b'test company').hexdigest()[:8]
        state['jobs'][key]={'status':'returned','attempts':1}
        runner.atomic_json(base/'results'/f'{key}.json',{'cases':[{'customer':'Acme','title':'Legacy story','url':f'https://stories.example.com/legacy/{i}'} for i in range(43)]})
        runner.save(base,state)
        with patch.object(runner,'codex_call',side_effect=AssertionError('Legacy discovery must not repeat')):
            self.assertTrue(runner.step(base,state,60,FAKE))
        self.assertEqual(len(runner.read_json(base/'inventory.json')['Test Company']),43)
        self.assertEqual(self.state()['jobs'][key]['attempts'],1)

    def test_stage2_discovery_paginates_45_candidates_into_20_20_5_across_fresh_runs(self):
        trace=Path(self.tmp.name)/'pagination-trace.jsonl'
        env={'FAKE_CASES':'45','FAKE_TRACE':str(trace)}
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE,env=env)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env=env)
        base=runner.run_dir('test-company')
        self.assertEqual(len(runner.read_json(base/'inventory.json')['Test Company']),20)
        progress=runner.read_json(runner.discovery_path(base))['Test Company']
        self.assertEqual((progress['page'],progress['cursor'],progress['complete']),(2,'20',False))
        for _ in range(5):
            self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        inventory=runner.read_json(base/'inventory.json')
        self.assertEqual({p:len(c) for p,c in inventory.items()},{'Test Company':45,'Beta Software':45})
        progress=runner.read_json(runner.discovery_path(base))
        self.assertTrue(all(p['complete'] for p in progress.values()))
        calls=[c for c in self.traced_assignments(trace) if c.get('task')=='discover']
        self.assertEqual(len(calls),6)
        for provider in ('Test Company','Beta Software'):
            pages=[c for c in calls if c['approved_provider']==provider]
            self.assertEqual([c['page'] for c in pages],[1,2,3])
            self.assertEqual([c['cursor'] for c in pages],['','20','40'])
            self.assertEqual([len(c['known_case_urls']) for c in pages],[0,20,40])
            self.assertTrue(all(c['max_cases']==20 for c in pages))
        receipts=[runner.read_json(p) for p in (base/'results').glob('inventory_*.json')]
        self.assertEqual(sorted(len(r['cases']) for r in receipts),[5,5,20,20,20,20])
        self.assertEqual(runner.get_schema(2)['properties']['cases']['maxItems'],20)
        self.pump(until=lambda s:s['phase']=='stage4',env=env)
        self.assertEqual(len(self.cells),90)
        self.assertEqual(len(set(self.state()['workspace_verified_ids'])),90)

    def test_stage2_rejects_oversized_discovery_page_without_committing_candidates(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,env={'FAKE_MODE':'oversized_discovery'})
        base=runner.run_dir('test-company')
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('20-candidate batch limit',self.state()['pause_reason'])
        self.assertFalse((base/'inventory.json').exists())
        self.assertFalse(runner.screening_path(base).exists())
        self.assertFalse(runner.read_json(runner.discovery_path(base))['Test Company']['complete'])

    def test_stage2_rejects_stalled_continuation_without_committing_candidates(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,env={'FAKE_MODE':'stalled_cursor'})
        base=runner.run_dir('test-company')
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertIn('continuation did not advance',self.state()['pause_reason'])
        self.assertFalse((base/'inventory.json').exists())
        self.assertFalse(runner.screening_path(base).exists())

    def test_stage2_page_receipt_replay_preserves_reviews_and_advances_once(self):
        trace=Path(self.tmp.name)/'page-replay-trace.jsonl'
        env={'FAKE_MODE':'multi_page_review','FAKE_TRACE':str(trace)}
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE,env=env)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1',env=env)
        base=runner.run_dir('test-company');real_atomic=runner.atomic_json
        def interrupted(path,value):
            if path==runner.discovery_path(base) and value.get('Beta Software',{}).get('page')==2:
                raise OSError('Synthetic interruption before continuation commit')
            return real_atomic(path,value)
        with patch.dict(os.environ,env):
            with patch.object(runner,'atomic_json',side_effect=interrupted):
                with self.assertRaises(OSError):runner.step(base,self.state(),60,FAKE)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['page'],1)
        runner.pause_state(base,self.state(),'Synthetic interruption before continuation commit')
        self.cmd('app','Resume Test Company','--codex',FAKE,'--max-tasks','1',env=env)
        early=runner.read_json(base/'extracted.json');early_id=next(iter(early))
        self.pump(until=lambda s:s['phase']=='stage4',env=env)
        self.assertEqual(runner.read_json(base/'extracted.json')[early_id],early[early_id])
        decisions=runner.read_json(runner.screening_path(base))
        self.assertEqual(decisions[early_id]['basis'],'substantive')
        self.assertEqual(decisions[early_id]['decision'],'relevant')
        calls=self.traced_assignments(trace)
        pages=[c['page'] for c in calls if c.get('approved_provider')=='Beta Software']
        self.assertEqual(pages,[1,2])
        reviewed=[c['review_case']['id'] for c in calls if c.get('task')=='review_case']
        self.assertEqual(len(reviewed),len(set(reviewed)))
        self.assertTrue(all(c['id']!=early_id for task in calls for c in task.get('assigned_cases',[])))
        self.assertTrue(runner.read_json(runner.discovery_path(base))['Beta Software']['complete'])

    def test_existing_paused_run_preserves_completed_appsflyer_discovery_and_extractions(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        base=runner.run_dir('test-company');state=self.state()
        landscape=runner.read_json(base/'landscape.json')
        landscape['competitors'].append({'name':'AppsFlyer','product':'Synthetic Attribution Product',
                                        'reason':'Synthetic shared need.','sources':['https://example.com/synthetic'],'confidence':'confirmed'})
        runner.atomic_json(base/'landscape.json',landscape)
        state.update(phase='paused_error',paused_from='stage2',pause_reason='Synthetic interruption',
                     approved_providers=['Test Company','AppsFlyer','Beta Software'])
        legacy={'id':runner.case_id('AppsFlyer','https://example.com/synthetic-completed'),
                'provider':'AppsFlyer','customer':'Synthetic Customer','title':'Synthetic completed story',
                'url':'https://example.com/synthetic-completed','relevance':{'problem':'Synthetic need','solution':'Synthetic intervention','result':'Synthetic result'}}
        runner.atomic_json(base/'inventory.json',{'Test Company':[],'AppsFlyer':[legacy]})
        key='inventory_appsflyer_e25a0408';state['jobs'][key]={'status':'complete','attempts':1}
        runner.save(base,state)
        record={'provider':'AppsFlyer','source_url':legacy['url'],'customer':legacy['customer'],
                'people':'Not reported in synthetic source.','company_profile':'Synthetic company.',
                'buying_situation':'Synthetic documented need.','status':'complete','note':''}
        runner.persist_records(base,[legacy],[record])
        before=(base/'extracted.json').read_bytes();old_job=copy.deepcopy(self.state()['jobs'][key])
        trace=Path(self.tmp.name)/'legacy-resume-trace.jsonl'
        self.cmd('app','Resume Test Company','--codex',FAKE,'--max-tasks','1',env={'FAKE_TRACE':str(trace)})
        self.assertEqual(self.state()['jobs'][key],old_job)
        self.assertEqual((base/'extracted.json').read_bytes(),before)
        self.assertEqual(runner.read_json(base/'inventory.json')['AppsFlyer'],[legacy])
        self.assertEqual(self.traced_assignments(trace)[0]['approved_provider'],'Beta Software')
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        self.assertFalse(any(c.get('approved_provider')=='AppsFlyer' for c in self.traced_assignments(trace)))
        self.assertFalse(any(c['provider']=='AppsFlyer' for task in self.traced_assignments(trace) for c in task.get('assigned_cases',[])))

    def test_explicit_provider_redo_archives_only_that_provider_and_uses_new_paged_cache(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        self.cmd('app','Approve these competitors: Beta Software','--codex',FAKE,'--max-tasks','1')
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1')
        base=runner.run_dir('test-company')
        before=runner.read_json(base/'inventory.json');old_jobs=copy.deepcopy(self.state()['jobs'])
        runner.pause_state(base,self.state(),'Synthetic interruption')
        result=self.cmd('redo-provider','test-company','--provider','Beta Software')
        self.assertEqual(result.returncode,0,result.stderr)
        page=runner.read_json(runner.discovery_path(base))['Beta Software'];revision=page['revision']
        self.assertTrue(page['reset_pending'])
        self.assertEqual(runner.read_json(Path(page['history']))['inventory'],before['Beta Software'])
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(self.cmd('redo-provider','test-company','--provider','Beta Software').returncode,0)
        self.assertEqual(len(list((base/'history').glob('*.json'))),1)
        trace=Path(self.tmp.name)/'redo-trace.jsonl';env={'FAKE_CASES':'25','FAKE_TRACE':str(trace)}
        self.cmd('app','Resume Test Company','--codex',FAKE,'--max-tasks','1',env=env)
        inventory=runner.read_json(base/'inventory.json')
        self.assertEqual(inventory['Test Company'],before['Test Company'])
        self.assertEqual(len(inventory['Beta Software']),20)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['revision'],revision)
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        self.assertEqual(len(runner.read_json(base/'inventory.json')['Beta Software']),25)
        page=runner.read_json(runner.discovery_path(base))['Beta Software']
        self.assertTrue(page['complete']);self.assertEqual(page['revision'],revision)
        self.assertTrue(all(self.state()['jobs'][k]==v for k,v in old_jobs.items()))
        calls=self.traced_assignments(trace)
        self.assertEqual([c['approved_provider'] for c in calls],['Beta Software','Beta Software'])
        self.assertEqual([c['cursor'] for c in calls],['','20'])
        self.assertTrue(any('_redo_'+revision in k for k in self.state()['jobs']))

    def test_provider_redo_cannot_discard_existing_extraction_or_publication(self):
        self.start();before=copy.deepcopy(self.state())
        result=self.cmd('redo-provider','test-company','--provider','Beta Software')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.state(),before)
        self.assertFalse((runner.run_dir('test-company')/'history').exists())

    def revised_fixture(self,competitor='Gamma Software'):
        self.start();self.assertEqual(self.pump()['phase'],'complete')
        base=runner.run_dir('test-company')
        self.original_records=runner.read_json(base/'extracted.json')
        self.original_jobs=copy.deepcopy(self.state()['jobs'])
        self.original_sheet=copy.deepcopy(self.state()['workspace_sheet'])
        trace=Path(self.tmp.name)/'revision-trace.jsonl'
        result=self.cmd('app','Rerun Stage 1 for Test Company','--id','test-company','--codex',FAKE,
                        env={'FAKE_COMPETITOR':competitor,'FAKE_PRODUCT':'Revised synthetic integration product.','FAKE_TRACE':str(trace)})
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.state()['phase'],'awaiting_approval')
        return base,trace

    def test_product_understanding_reaches_each_fresh_research_assignment(self):
        trace=Path(self.tmp.name)/'product-trace.jsonl'
        base,env=self.screening_fixture(trace)
        self.pump(until=lambda s:s['phase']=='stage4',env=env)
        product=runner.product_understanding(base)
        assignments=self.traced_assignments(trace)[1:]
        self.assertTrue(any(x.get('task')=='review_case' for x in assignments))
        self.assertTrue(any('assigned_cases' in x for x in assignments))
        self.assertTrue(all(x['product_understanding']==product for x in assignments))
        self.assertTrue(all(x['pdf_access_policy']==runner.PDF_ACCESS_POLICY for x in assignments))
        self.assertEqual(runner.PDF_ACCESS_POLICY['max_attempts'],1)
        self.assertFalse(runner.PDF_ACCESS_POLICY['fallbacks_allowed'])
        self.assertEqual(runner.provider_scope(base,self.state(),'Test Company')['product'],product['summary'])
        saved=runner.read_json(base/'product_understanding.json');saved['summary']='tampered'
        runner.atomic_json(base/'product_understanding.json',saved)
        with self.assertRaises(runner.RunError):runner.product_understanding(base)

    def test_stage1_revision_preserves_active_dataset_and_waits_for_approval(self):
        base,trace=self.revised_fixture()
        state=self.state();revision=state['landscape_revision']
        self.assertEqual(state['workspace_sheet'],self.original_sheet)
        self.assertEqual(runner.read_json(base/'extracted.json'),self.original_records)
        self.assertEqual(state['jobs']|self.original_jobs,state['jobs'])
        self.assertEqual(runner.read_json(base/'landscape.json')['competitors'][0]['name'],'Beta Software')
        self.assertEqual(runner.product_understanding(base)['summary'],'Synthetic integration product.')
        self.assertEqual(runner.read_json(Path(revision['proposal']))['competitors'][0]['name'],'Gamma Software')
        self.assertTrue((base/'analysis_4.json').exists())
        self.assertEqual(len(self.traced_assignments(trace)),1)
        import zipfile
        with zipfile.ZipFile(Path(revision['backup'])/'run.zip') as archive:
            self.assertEqual(json.loads(archive.read('extracted.json')),self.original_records)
            self.assertEqual(json.loads(archive.read('state.json'))['phase'],'complete')
        self.assertIn('STOP: awaiting_approval',self.cmd('run','test-company','--codex',FAKE).stdout)
        self.assertEqual(runner.read_json(base/'extracted.json'),self.original_records)

    def test_approved_revision_reuses_records_and_reconciles_original_sheet(self):
        base,trace=self.revised_fixture()
        self.assertEqual(self.cmd('approve','test-company','--names','Gamma Software').returncode,0)
        state=self.pump(until=lambda s:s['phase']=='stage2',env={'FAKE_TRACE':str(trace)})
        records=runner.read_json(base/'extracted.json')
        target={cid:r for cid,r in self.original_records.items() if r['provider']=='Test Company'}
        self.assertEqual(records,target)
        self.assertEqual(state['workspace_sheet'],self.original_sheet)
        self.assertEqual(state['workspace_verified_ids'],list(target))
        self.assertEqual(self.cells[1],workspace.rows_for(list(target.values()))[0])
        self.assertEqual(self.cells[2],['']*5)
        self.assertEqual(state['last_dataset_backup']['id'],'offline-sheet-backup')
        self.assertFalse((base/'analysis_4.json').exists());self.assertFalse((base/'finalized_sheet.json').exists())
        self.assertFalse(state['document_verified']);self.assertNotIn('workspace_document',state)
        self.assertTrue(runner.read_json(runner.discovery_path(base))['Test Company']['complete'])
        self.assertTrue(all(state['jobs'][k]==v for k,v in self.original_jobs.items()))
        calls=self.traced_assignments(trace)
        self.assertEqual(calls[1]['task'],'reconcile_cases')
        self.assertEqual(calls[1]['product_understanding'],runner.product_understanding(base))
        self.assertEqual(runner.product_understanding(base)['summary'],'Revised synthetic integration product.')
        self.assertEqual(len(calls),2)
        # Continue fresh executions: only the newly included provider is researched.
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        calls=self.traced_assignments(trace)[2:]
        self.assertTrue(any(c.get('approved_provider')=='Gamma Software' for c in calls))
        self.assertFalse(any(c.get('approved_provider') in ('Test Company','Beta Software') for c in calls))
        self.assertFalse(any(c['provider']=='Test Company' for task in calls for c in task.get('assigned_cases',[])))
        self.assertEqual(len(self.state()['workspace_verified_ids']),2)
        self.assertEqual(len(set(self.state()['workspace_verified_ids'])),2)

    def test_reconciliation_conflict_preserves_user_sheet_edits(self):
        self.revised_fixture()
        self.cmd('approve','test-company','--names','Gamma Software')
        self.cells[1]=['user edit']*5;before=self.write_count
        state=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_reconcile_backup')
        self.assertNotEqual(self.dispatch(state['workspace_pending']).returncode,0)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(self.write_count,before);self.assertEqual(self.cells[1],['user edit']*5)
        self.assertEqual(self.state()['workspace_sheet'],self.original_sheet)

    def test_lost_reconciliation_write_receipt_is_recovered_by_readback(self):
        self.revised_fixture();self.cmd('approve','test-company','--names','Gamma Software')
        state=self.pump(until=lambda s:s.get('workspace_pending',{}).get('kind')=='sheet_reconcile_write')
        pending=state['workspace_pending']
        self.cmd('workspace','test-company','begin','--request-id',pending['id'])
        self.google(pending,'test-company');writes=self.write_count
        retried=self.cmd('workspace','test-company','retry','--request-id',pending['id'])
        self.assertEqual(retried.returncode,0,retried.stderr)
        self.assertEqual(self.state()['workspace_pending']['kind'],'sheet_reconcile_preflight')
        self.pump(until=lambda s:s['phase']=='stage2')
        self.assertEqual(self.write_count,writes)
        self.assertEqual(len(self.state()['workspace_verified_ids']),1)

    def test_stage1_revision_quota_preserves_prior_work_and_does_not_retry(self):
        self.start();base=runner.run_dir('test-company');before=(base/'extracted.json').read_bytes() if (base/'extracted.json').exists() else None
        result=self.cmd('app','Rerun Stage 1 for Test Company','--codex',FAKE,env={'FAKE_MODE':'quota_hit'})
        self.assertEqual(result.returncode,0,result.stderr)
        state=self.state();self.assertEqual(state['phase'],'paused_quota')
        job='stage1_revision_'+state['landscape_revision']['id']
        self.assertEqual(state['jobs'][job]['attempts'],1)
        self.assertEqual((base/'extracted.json').read_bytes() if (base/'extracted.json').exists() else None,before)
        self.assertIn('HALTED',self.cmd('run','test-company','--codex',FAKE).stdout)
        self.assertEqual(self.state()['jobs'][job]['attempts'],1)

    def test_reconciliation_batches_saved_evidence_and_disables_tools(self):
        self.start(env={'FAKE_CASES':'25'});self.pump()
        trace=Path(self.tmp.name)/'saved-evidence.jsonl'
        self.cmd('app','Rerun Stage 1 for Test Company','--codex',FAKE)
        self.cmd('approve','test-company','--names','Beta Software')
        self.pump(until=lambda s:s['phase']=='stage2',env={'FAKE_TRACE':str(trace)})
        calls=[json.loads(x) for x in trace.read_text().splitlines()]
        assignments=self.traced_assignments(trace)
        self.assertEqual([len(x['saved_cases']) for x in assignments],[20,20,10])
        self.assertTrue(all('--ignore-user-config' in c['args'] and 'web_search="disabled"' in c['args'] for c in calls))
        self.assertEqual(len(self.state()['workspace_verified_ids']),50)
        self.assertEqual(len(runner.read_json(runner.run_dir('test-company')/'extracted.json')),50)

    def test_revision_preserves_early_records_locally_then_syncs_without_reextraction(self):
        base,env=self.screening_fixture()
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        records=runner.read_json(base/'extracted.json');self.assertEqual(len(records),1)
        self.assertNotIn('workspace_sheet',self.state())
        self.cmd('app','Rerun Stage 1 for Test Company','--codex',FAKE)
        self.cmd('approve','test-company','--names','Beta Software')
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1')
        runner.step(base,self.state(),60,FAKE) # observe local commit before new research
        self.assertEqual(self.state()['phase'],'stage2')
        self.assertEqual(runner.read_json(base/'extracted.json'),records)
        self.assertNotIn('workspace_sheet',self.state())
        trace=Path(self.tmp.name)/'early-revision.jsonl'
        self.pump(until=lambda s:s['phase']=='stage4',env=dict(env,FAKE_TRACE=str(trace)))
        assigned=[c['id'] for task in self.traced_assignments(trace) for c in task.get('assigned_cases',[])]
        self.assertFalse(set(records)&set(assigned))
        self.assertTrue(set(records)<=set(self.state()['workspace_verified_ids']))

    def test_revision_excludes_irrelevant_case_of_retained_provider_with_recoverable_record(self):
        base,_=self.revised_fixture(competitor='Beta Software')
        inventory=runner.read_json(base/'inventory.json')
        cid=inventory['Beta Software'][0]['id'];inventory['Beta Software'][0]['customer']='Out of scope'
        runner.atomic_json(base/'inventory.json',inventory)
        self.cmd('approve','test-company','--names','Beta Software')
        self.pump(until=lambda s:s['phase']=='stage2')
        self.assertNotIn(cid,runner.read_json(base/'extracted.json'))
        decision=runner.read_json(runner.screening_path(base))[cid]
        self.assertEqual(decision['decision'],'excluded');self.assertTrue(decision['reason'])
        plan=runner.read_json(Path(self.state()['landscape_revision']['plan']))
        self.assertEqual(plan['records'][cid],self.original_records[cid])
        self.assertEqual(self.cells[2],['']*5)

    def test_relevance_review_reuses_saved_complete_record(self):
        base,_=self.revised_fixture(competitor='Beta Software')
        self.cmd('approve','test-company','--names','Beta Software')
        self.pump(until=lambda s:s['phase']=='stage2',env={'FAKE_MODE':'saved_needs_review'})
        self.assertEqual(runner.read_json(base/'extracted.json'),{})
        trace=Path(self.tmp.name)/'saved-review.jsonl'
        self.pump(until=lambda s:s['phase']=='stage4',env={'FAKE_TRACE':str(trace)})
        self.assertEqual(runner.read_json(base/'extracted.json'),self.original_records)
        calls=self.traced_assignments(trace)
        self.assertEqual(len(calls),2)
        self.assertTrue(all(c['task']=='review_case' and c['saved_record'] for c in calls))

    def test_parent_vendor_name_reuses_existing_product_provider_identity(self):
        base,_=self.revised_fixture(competitor='Beta Parent')
        path=Path(self.state()['landscape_revision']['proposal']);proposal=runner.read_json(path)
        proposal['competitors'][0]['product']='Beta Software mobile measurement'
        runner.atomic_json(path,proposal) # synthetic proposal fixture only
        result=self.cmd('approve','test-company','--names','Beta Parent')
        self.assertEqual(result.returncode,0,result.stderr)
        state=self.pump(until=lambda s:s['phase']=='stage2')
        self.assertEqual(state['approved_providers'],['Test Company','Beta Software'])
        self.assertEqual(runner.read_json(base/'extracted.json'),self.original_records)
        self.assertEqual(runner.read_json(runner.discovery_path(base))['Beta Software']['complete'],True)
        plan=runner.read_json(Path(state['landscape_revision']['plan']))
        self.assertEqual(plan['provider_identities']['Beta Parent'],'Beta Software')
        self.assertEqual(state['workspace_verified_ids'],list(self.original_records))

    def test_provider_identity_requires_matching_product_and_source(self):
        self.cmd('app','Research Test Company — https://example.com','--codex',FAKE)
        base=runner.run_dir('test-company');state=self.state();state['approved_providers']+=['Beta Software']
        proposal=runner.read_json(base/'landscape.json')
        proposal['competitors'][0].update(name='Beta Parent',product='Beta Software measurement',sources=['https://different.example/product'])
        _,approved,identities=runner.canonical_universe(base,state,proposal,['Test Company','Beta Parent'])
        self.assertEqual(approved,['Test Company','Beta Parent']);self.assertEqual(identities,{})
        proposal['competitors'][0].update(product='Unrelated CRM',sources=['https://beta.example.com/product'])
        _,approved,identities=runner.canonical_universe(base,state,proposal,['Test Company','Beta Parent'])
        self.assertEqual(approved,['Test Company','Beta Parent']);self.assertEqual(identities,{})

    def exclusion_fixture(self):
        base,env=self.screening_fixture()
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        records=runner.read_json(base/'extracted.json');cid=next(iter(records))
        return base,env,cid,records[cid]

    def test_selective_exclusion_archives_record_preserves_progress_and_prevents_publication(self):
        base,env,cid,record=self.exclusion_fixture()
        runner.pause_state(base,self.state(),'Synthetic quota reached.','quota')
        jobs=copy.deepcopy(self.state()['jobs']);progress=runner.discovery_path(base).read_bytes()
        result=self.cmd('exclude-case','test-company','--case-id',cid,'--reason','Synthetic unapproved business line.')
        self.assertEqual(result.returncode,0,result.stderr)
        history=runner.read_json(base/'history'/f'exclude_case_{cid}.json')
        self.assertEqual(history['record'],record);self.assertTrue(history['committed'])
        self.assertTrue((Path(history['backup'])/'run.zip').exists())
        self.assertNotIn(cid,runner.read_json(base/'extracted.json'))
        self.assertEqual(self.state()['phase'],'paused_quota')
        self.assertEqual(self.state()['jobs'],jobs)
        self.assertEqual(runner.discovery_path(base).read_bytes(),progress)
        self.assertEqual(runner.read_json(runner.screening_path(base))[cid]['decision'],'excluded')
        self.assertEqual(self.cmd('exclude-case','test-company','--case-id',cid,'--reason','Synthetic unapproved business line.').returncode,0)
        self.assertEqual(runner.read_json(base/'history'/f'exclude_case_{cid}.json'),history)
        self.assertEqual(self.cmd('resume','test-company','--confirm-reset').returncode,0)
        self.pump(until=lambda s:s['phase']=='stage4',env=env)
        self.assertNotIn(cid,self.state()['workspace_verified_ids'])
        self.assertFalse(any(c['id']==cid for cases in runner.read_json(runner.inventory_path(base)).values() for c in cases))

    def test_selective_exclusion_recovers_interrupted_commit_before_research(self):
        base,env,cid,record=self.exclusion_fixture()
        import argparse
        original=runner.atomic_json
        def interrupted(path,data):
            if path==runner.inventory_path(base):raise OSError('Synthetic interrupted exclusion commit')
            original(path,data)
        with patch.object(runner,'atomic_json',side_effect=interrupted):
            with self.assertRaises(OSError):
                runner.exclude_case(argparse.Namespace(id='test-company',case_id=cid,reason='Synthetic wrong product.'))
        self.assertFalse(runner.read_json(base/'history'/f'exclude_case_{cid}.json')['committed'])
        self.assertIn(cid,runner.read_json(base/'extracted.json'))
        self.cmd('run','test-company','--codex',FAKE,'--max-tasks','1',env=env)
        self.assertTrue(runner.read_json(base/'history'/f'exclude_case_{cid}.json')['committed'])
        self.assertNotIn(cid,runner.read_json(base/'extracted.json'))

    def test_selective_exclusion_cannot_modify_published_or_batched_work(self):
        self.start();before=copy.deepcopy(self.state())
        result=self.cmd('exclude-case','test-company','--case-id','0123456789abcdef','--reason','Synthetic wrong product.')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual(self.state(),before)

    def test_observed_pdf_failure_is_saved_without_reopening_and_survives_resume(self):
        base,env=self.screening_fixture()
        ledger=runner.read_json(runner.screening_path(base))
        oldid=next(cid for cid,c in ledger.items() if c['decision']=='needs_review')
        case=ledger.pop(oldid);case['url']='https://stories.example.com/failed.pdf'
        case['id']=runner.case_id(case['provider'],case['url']);cid=case['id'];ledger[cid]=case
        runner.atomic_json(runner.screening_path(base),ledger)
        runner.pause_state(base,self.state(),'Synthetic interruption after first PDF failure.')
        jobs=copy.deepcopy(self.state()['jobs']);progress=runner.discovery_path(base).read_bytes()
        args=('mark-pdf-failed','test-company','--case-id',cid,'--reason','First PDF attempt returned no readable content.')
        result=self.cmd(*args);self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(self.state()['phase'],'paused_error')
        self.assertEqual(self.state()['jobs'],jobs);self.assertEqual(runner.discovery_path(base).read_bytes(),progress)
        self.assertEqual(runner.read_json(runner.screening_path(base))[cid]['decision'],'unresolved')
        history=runner.read_json(base/'history'/f'pdf_failure_{cid}.json')
        self.assertTrue(history['committed']);self.assertEqual(history['decision'],'unresolved')
        self.assertEqual(self.cmd(*args).returncode,0)
        self.assertEqual(runner.read_json(base/'history'/f'pdf_failure_{cid}.json'),history)
        trace=Path(self.tmp.name)/'pdf-resume.jsonl'
        self.cmd('app','Resume Test Company','--codex',FAKE,env=dict(env,FAKE_TRACE=str(trace)))
        self.pump(until=lambda s:s['phase']=='stage4',env=dict(env,FAKE_TRACE=str(trace)))
        self.assertTrue(all(c.get('review_case',{}).get('id')!=cid for c in self.traced_assignments(trace)))
        self.assertTrue(all(case['id']!=cid for task in self.traced_assignments(trace) for case in task.get('assigned_cases',[])))
        self.assertNotIn(cid,self.state()['workspace_verified_ids'])

    def test_pdf_failure_cannot_replace_a_completed_record(self):
        base,env,cid,record=self.exclusion_fixture()
        before=(base/'extracted.json').read_bytes();state=copy.deepcopy(self.state())
        result=self.cmd('mark-pdf-failed','test-company','--case-id',cid,'--reason','Synthetic PDF failure.')
        self.assertNotEqual(result.returncode,0)
        self.assertEqual((base/'extracted.json').read_bytes(),before);self.assertEqual(self.state(),state)

    def test_pdf_rule_is_an_execution_override_for_each_research_stage(self):
        for stage,context in ((1,{}),(2,{'task':'discover'}),(2,{'task':'review_case'}),(3,{})):
            prompt=runner.prompt_for(stage,context)
            override=prompt.split('RUNNER EXECUTION OVERRIDE:',1)[1].split('OUTPUT CONTRACT:',1)[0]
            self.assertIn('ONE access attempt per PDF',override)
            self.assertIn('stop that case immediately',override)
            self.assertIn('overrides PDF-skill',override)

    def test_stage3_pdf_failure_is_saved_and_other_assigned_case_continues(self):
        self.start();base=runner.run_dir('test-company')
        inventory=runner.read_json(runner.inventory_path(base));case=inventory['Test Company'][0]
        case.update(url='https://stories.example.com/first-fails.pdf')
        case['id']=runner.case_id(case['provider'],case['url']);cid=case['id']
        runner.atomic_json(runner.inventory_path(base),inventory)
        runner.atomic_json(base/'batches.json',runner.compile_batches(inventory))
        trace=Path(self.tmp.name)/'stage3-pdf.jsonl';env={'FAKE_MODE':'pdf_single_failure','FAKE_TRACE':str(trace)}
        state=self.pump(until=lambda s:s['phase']=='stage4',env=env)
        self.assertEqual(state['phase'],'stage4')
        records=runner.read_json(base/'extracted.json')
        self.assertEqual(records[cid]['status'],'inaccessible')
        self.assertEqual(sum(r['status']=='complete' for r in records.values()),1)
        snapshot=runner.read_json(base/'finalized_sheet.json')
        self.assertEqual(snapshot['unavailable'],1);self.assertEqual(snapshot['complete'],1)
        assigned=[c['id'] for task in self.traced_assignments(trace) for c in task.get('assigned_cases',[])]
        self.assertEqual(assigned.count(cid),1)

if __name__=='__main__':unittest.main()
