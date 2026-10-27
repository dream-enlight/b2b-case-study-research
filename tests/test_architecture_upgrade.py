"""Bounded offline acceptance tests; no research or Workspace credits."""
import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import analysis_compact as ac
import analysis_pipeline as ap
import performance
import research
import runner
import taxonomy_first as tf
import workspace as ws
from test_analysis_pipeline import fixture
import test_runner as legacy


class ArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.db=fixture(65)
        runner.atomic_json(self.base/'finalized_sheet.json',self.db)
        self.state={'phase':'stage4','jobs':{},'analysis_policy':dict(tf.POLICY)}
    def tearDown(self):self.tmp.cleanup()
    def api(self):
        outer=self
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            checkpoint_job=staticmethod(lambda *a:None)
            save=staticmethod(lambda *a:None)
            @staticmethod
            def invoke(base,state,stage,key,ctx,timeout,cli):
                if ctx['analysis_task']=='taxonomy_build':
                    inputs=ctx['inputs'];categories=[]
                    if 'cells' in inputs[0]:
                        for dim,col in [('company_category',3),('buying_situations',4),('stakeholders',2)]:
                            e={'id':inputs[0]['id'],'cell':col,'quote':inputs[0]['cells'][col]}
                            categories.append({'dimension':dim,'name':dim+' theme','definition':'Business definition '+dim,'kind':'goal' if dim=='buying_situations' else 'descriptive','evidence':[e]})
                    elif ctx['purpose']=='other_review':
                        categories=[{'dimension':'selection_requirements','name':'Service reliability','definition':'Needs dependable support','kind':'requirement','evidence':inputs[0]['evidence']}]
                    else:
                        bydim={}
                        for x in inputs:bydim.setdefault(x['dimension'],{k:v for k,v in x.items() if k!='id'})
                        categories=list(bydim.values())
                    return {'categories':categories,'covered_ids':ctx['input_ids']}
                if ctx['analysis_task']=='taxonomy_remap':return {'assignments':[{'ref':x['id'],'cat':next(iter(ctx['categories']))} for x in ctx['observations']]}
                if ctx['analysis_task']=='global_synthesis_report':
                    outer.report_context=ctx
                    from fake_report import markdown
                    return {'markdown':markdown(ctx)}
                if ctx['analysis_task']=='classify_compact':
                    manifest=ac.read(ctx['checkpoint_manifest'])
                    for i in range(0,len(ctx['records']),5):
                        records=[outer.compact(r['id']) for r in ctx['records'][i:i+5]]
                        ac.checkpoint(manifest,{'records':records},runner.atomic_json)
                    return {'completed_ids':manifest['case_ids']}
                raise AssertionError(ctx['analysis_task'])
        return API
    def prepare(self):
        ap._fresh_calls=0;self.assertTrue(tf.prepare(self.api(),self.base,self.state,self.db,1,'offline'))
    def compact(self,cid,other=False):
        reg=ac.registry(self.base,self.db);cats=reg['categories'];obs=[]
        for dim in ac.DIMS:
            preferred='Other' if dim=='selection_requirements' and other else tf.UNKNOWN if dim in ('selection_requirements','company_characteristics') else dim+' theme'
            cat=next(k for k,c in cats.items() if c['dimension']==dim and c['name']==preferred)
            col={'company_category':3,'company_characteristics':3,'stakeholders':2}.get(dim,4)
            quote='' if preferred==tf.UNKNOWN else 'dependable support' if preferred=='Other' else self.db['rows'][int(cid)][col]
            o={'cat':cat,'cell':col,'quote':quote,'strength':'unclear' if preferred==tf.UNKNOWN else 'explicit','kind':'requirement' if preferred=='Other' else 'goal' if dim=='buying_situations' else 'uncertain' if preferred==tf.UNKNOWN else 'descriptive','detail':'Dependable customer support' if preferred=='Other' else ''}
            if dim=='stakeholders':o['people']=['Chris']
            obs.append(o)
        return {'id':cid,'anonymous':cid in ('3','4'),'observations':obs}
    def save(self,ids,other=False):
        manifest={'run_dir':str(self.base),'database_sha256':self.db['sha256'],'case_ids':ids,'key':'test'+ids[0],'checkpoint_group_size':5}
        return ac.checkpoint(manifest,{'records':[self.compact(cid,other=other) for cid in ids]},runner.atomic_json)
    def test_global_taxonomy_precedes_bounded_consistent_mapping(self):
        self.prepare();reg=ac.registry(self.base,self.db)
        self.assertTrue(reg['taxonomy_first']);self.assertEqual(len(reg['categories']),13)
        ap._fresh_calls=0;self.assertFalse(ac.classify_step(self.api(),self.base,self.state,self.db,1,'offline'))
        self.assertEqual(len(ac.records(self.base,self.db)),60)
        ap._fresh_calls=0;self.assertFalse(ac.classify_step(self.api(),self.base,self.state,self.db,1,'offline'))
        raw=[ac.read(p)['record'] for p in (ac.home(self.base,self.db)/'records').glob('*.json')]
        self.assertEqual(len(raw),65)
        self.assertEqual({tuple(o['cat'] for o in r['observations']) for r in raw},{tuple(o['cat'] for o in raw[0]['observations'])})
        self.assertEqual(reg,ac.registry(self.base,self.db))
    def test_other_unknown_review_and_exact_profile_counts(self):
        self.db=fixture(5);runner.atomic_json(self.base/'finalized_sheet.json',self.db);self.prepare()
        self.save(['0','1','2','3','4'],other=True)
        originals={p.name:p.read_bytes() for p in (ac.home(self.base,self.db)/'records').glob('*.json')}
        ap._fresh_calls=0;markdown=tf.execute(self.api(),self.base,self.state,self.db,1,'offline')
        self.assertIn('# Overview',markdown)
        agg=ac.read(tf.home(self.base,self.db)/'aggregation.json');self.assertEqual(agg['distinct_profiles'],3)
        self.assertEqual(agg['dimensions']['selection_requirements'][0]['name'],'Service reliability')
        self.assertEqual(agg['dimensions']['selection_requirements'][0]['profile_count'],3)
        self.assertEqual(agg['dimensions']['company_characteristics'][0]['name'],tf.UNKNOWN)
        self.assertEqual(agg['buying_evidence_coverage'],{'goal':3})
        self.assertEqual(originals,{p.name:p.read_bytes() for p in (ac.home(self.base,self.db)/'records').glob('*.json')})
        with patch.object(self.api(),'invoke',side_effect=AssertionError('Report should be cached')):
            self.assertEqual(tf.execute(self.api(),self.base,self.state,self.db,1,'offline'),markdown)
    def test_checkpoint_does_not_expand_completed_history(self):
        self.prepare();self.save(['0','1','2','3','4'])
        with patch.object(ac,'records',side_effect=AssertionError('No historical expansion per checkpoint')):
            self.save(['5','6','7','8','9'])
        bad=self.compact('10');bad['observations'][0]['cat']='invented'
        manifest={'run_dir':str(self.base),'database_sha256':self.db['sha256'],'case_ids':['10'],'key':'bad','checkpoint_group_size':5}
        with self.assertRaises(ws.WorkspaceError):ac.checkpoint(manifest,{'records':[bad]},runner.atomic_json)
    def test_other_requires_specific_evidence_and_registry_is_fixed(self):
        self.prepare();r=self.compact('0',other=True);r['observations'][1]['detail']=''
        m={'run_dir':str(self.base),'database_sha256':self.db['sha256'],'case_ids':['0'],'key':'invalid','checkpoint_group_size':5}
        with self.assertRaisesRegex(ws.WorkspaceError,'specific description'):ac.checkpoint(m,{'records':[r]},runner.atomic_json)
        with self.assertRaisesRegex(ws.WorkspaceError,'Fixed taxonomy'):ac.checkpoint(m,{'records':[r],'new_categories':[{}]},runner.atomic_json)
    def test_hierarchical_taxonomy_covers_later_batches(self):
        self.state['analysis_policy']['taxonomy_input_bytes']=3500
        self.prepare()
        leaves=list((tf.home(self.base,self.db)/'initial').glob('0_*.json'))
        self.assertGreater(len(leaves),1)
        self.assertEqual(sorted(cid for p in leaves for cid in ac.read(p)['input_ids']),sorted(self.db['case_ids']))
        reg=ac.registry(self.base,self.db);self.assertTrue(reg['taxonomy_first'])
    def test_research_context_is_assignment_scoped_and_failure_is_durable(self):
        for n in range(25):research.remember(self.base,runner.atomic_json,capture={'url':f'https://example.com/{n}','coverage':'full_text','text':'Case '+str(n)},provider='Vendor')
        pdf='https://example.com/failed.pdf';research.remember(self.base,runner.atomic_json,capture={'url':pdf,'coverage':'failed','text':'First access failed'},provider='Other')
        ctx=research.context(self.base,[{'url':'https://example.com/24'}],'Vendor')
        self.assertEqual(set(ctx['sources']),{'https://example.com/24'});self.assertEqual(ctx['completed_searches'],{})
        self.assertIn(pdf,ctx['known_access_failures'])
    def test_synthetic_whole_dataset_budget(self):
        db=fixture(145)
        before=ws.digest(db)
        items=[{'id':cid,'cells':row} for cid,row in ap.eligible_rows(db).items()]
        batches=list(ap.bounded(items,tf.POLICY))
        self.assertEqual(sum(map(len,batches)),db['complete'])
        self.assertTrue(all(len(b)<=60 for b in batches))
        self.db=db;runner.atomic_json(self.base/'finalized_sheet.json',db)
        self.prepare()
        leaves=list((tf.home(self.base,db)/'initial').glob('0_*.json'))
        self.assertEqual(sorted(cid for f in leaves for cid in ac.read(f)['input_ids']),sorted(ap.eligible_rows(db)))
        self.assertEqual(before,ws.digest(db))
    def test_taxonomy_rejects_unassigned_evidence_and_missing_coverage(self):
        class Bad:
            atomic_json=staticmethod(runner.atomic_json)
            save=staticmethod(lambda *a:None)
            checkpoint_job=staticmethod(lambda *a:None)
            @staticmethod
            def invoke(*args):return {'categories':[],'covered_ids':[]}
        ap._fresh_calls=0
        with self.assertRaisesRegex(ws.WorkspaceError,'omitted'):
            tf.build(Bad,self.base,self.state,self.db,[{'id':'0','cells':self.db['rows'][0]}],'invalid',1,'offline')
    def test_complete_only_publication_plans_large_stable_groups(self):
        records=[{'id':str(n),'provider':'Vendor','source_url':'https://example.com/'+str(n),'customer':'C'+str(n),'people':'Unknown','company_profile':'Software','buying_situation':'Need','status':'inaccessible' if n==9 else 'complete','note':'Failed first access'} for n in range(105)]
        state={'phase':'stage3','workspace_policy':{'complete_only':True,'sync_batch_size':100},'workspace_sheet':{'id':'sheet','sheet_id':7,'tab':'Case studies','row_count':1000},'workspace_header_verified':True}
        ws.ensure_sync(self.base,state,records[:40],runner.atomic_json,flush=False)
        self.assertNotIn('workspace_pending',state)
        ws.ensure_sync(self.base,state,records,runner.atomic_json,flush=False)
        pending=state['workspace_pending'];self.assertEqual(len(pending['details']['rows']),100)
        self.assertNotIn('9',pending['details']['ids']);self.assertEqual(pending['details']['start'],1)
        self.assertTrue(all(len(row)==5 for row in pending['details']['rows']))
    def test_publication_expands_grid_without_replacing_sheet(self):
        records=[{'id':str(n),'provider':'Vendor','source_url':'https://example.com/'+str(n),'customer':'C','people':'Unknown','company_profile':'Software','buying_situation':'Need','status':'complete','note':''} for n in range(105)]
        state={'phase':'stage3','workspace_policy':{'complete_only':True,'sync_batch_size':100},'workspace_sheet':{'id':'sheet','sheet_id':7,'tab':'Case studies','row_count':100},'workspace_header_verified':True}
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        pending=state['workspace_pending'];self.assertEqual(pending['kind'],'sheet_resize')
        self.assertEqual(pending['details']['row_count'],200)
        ws.apply_response(self.base,state,pending,{'spreadsheetId':'sheet','replies':[]},runner.atomic_json)
        self.assertEqual(state['workspace_sheet']['id'],'sheet')
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        self.assertEqual(state['workspace_pending']['kind'],'sheet_preflight')

    def test_actual_source_bytes_bound_assignment_without_truncating(self):
        cases=[{'id':str(n),'url':'https://example.com/'+str(n)} for n in range(3)]
        for c in cases:research.remember(self.base,runner.atomic_json,capture={'url':c['url'],'coverage':'full_text','text':'x'*15000})
        settings=dict(research.POLICY,max_context_bytes=45000)
        self.assertEqual(len(research.assignment_cases(self.base,cases,settings)),2)
        self.assertEqual(len(research.context(self.base,cases[:1])['sources'][cases[0]['url']]['text']),15000)

    def test_new_failure_updates_current_worker_guard_immediately(self):
        context={'approved_provider':'Vendor','evidence_memory':{'known_access_failures':{}}}
        runner.commit_worker_message(self.base,{'dataset_revision':None},'test',context,
            {'source_capture':{'url':'https://example.com/a.pdf','coverage':'failed','text':'First attempt failed'}},'offline')
        self.assertIn('https://example.com/a.pdf',context['evidence_memory']['known_access_failures'])

    def test_inventory_history_stays_bounded_without_losing_local_index(self):
        urls=['https://example.com/case/'+str(n) for n in range(10000)]
        window=research.inventory_window(urls,research.POLICY)
        self.assertEqual(len(window),200);self.assertEqual(window[-1],urls[-1]);self.assertEqual(len(urls),10000)
        self.assertLess(len(json.dumps(window).encode()),research.POLICY['max_context_bytes']//4)

    def test_metrics_missing_tokens_and_repeated_sources(self):
        event=json.dumps({'type':'item.completed','item':{'type':'web_search','action':{'type':'open','url':'https://example.com/a'}}})
        performance.worker(self.base,2,'one',1,event,False);performance.worker(self.base,2,'two',2,event,True)
        totals=performance.summary(self.base)['2'];self.assertEqual(totals['executions'],2);self.assertEqual(totals['repeated_reads'],1);self.assertIsNone(totals['output_tokens'])


class OfflineEndToEnd(unittest.TestCase):
    setUp=legacy.RunnerTests.setUp
    tearDown=legacy.RunnerTests.tearDown
    cmd=legacy.RunnerTests.cmd
    state=legacy.RunnerTests.state
    def google(self,p,rid):
        # Reuse the existing native-tab fixture for modern report publication;
        # the legacy connector fixture predates the five-tab contract.
        kind=p['kind']
        if kind.startswith('doc_tabs_'):
            import document_tabs
            from test_document_tabs import DocumentTabTests
            if kind!='doc_tabs_inspect':
                self.native_stage=kind
                return {'documentId':'offline-doc','replies':[]}
            markdown=(runner.run_dir(rid)/'report.md').read_text()
            sections=document_tabs.sections(markdown)
            stage=getattr(self,'native_stage','')
            tab=lambda md,name,tid,scaffold=False:DocumentTabTests.tab(self,md,name,tid,scaffold)
            root=tab(sections[0] if stage=='doc_tabs_finish' else markdown,
                     'Overview' if stage=='doc_tabs_finish' else 'Tab 1','t.0')
            details=[tab('' if stage=='doc_tabs_add' else section,name,'t.'+str(i),
                         scaffold=stage=='doc_tabs_write')
                     for i,(section,name) in enumerate(zip(sections[1:],document_tabs.TITLES[1:]),1)]
            return {'documentId':'offline-doc','revisionId':'offline-revision','tabs':[root]+details}
        return legacy.RunnerTests.google(self,p,rid)
    dispatch=legacy.RunnerTests.dispatch
    pump=legacy.RunnerTests.pump
    traced_assignments=legacy.RunnerTests.traced_assignments
    modern=True
    def test_bounded_new_run_smoke_with_fake_workspace_only(self):
        trace=Path(self.tmp.name)/'trace.jsonl';env={'FAKE_TRACE':str(trace),'FAKE_MODE':'multi_product','FAKE_CASES':'2'}
        self.cmd('app','Research Test Company — https://example.com','--codex',legacy.FAKE,env=env)
        self.assertEqual(self.state()['phase'],'awaiting_approval')
        self.cmd('app','Approve these competitors: Beta Software','--codex',legacy.FAKE,env=env)
        s=self.pump(env=env);self.assertEqual(s['phase'],'complete',s.get('pause_reason'))
        assignments=self.traced_assignments(trace)
        reviews=[x for x in assignments if x.get('task')=='review_batch']
        self.assertEqual(sum(len(x['review_cases']) for x in reviews),3)
        deep_urls={c['url'] for x in reviews for c in x['review_cases']}
        extractions=[x for x in assignments if x.get('task')=='extract_batch']
        self.assertTrue(all(c['url'] not in deep_urls for x in extractions for c in x['assigned_cases']))
        self.assertEqual(sum(x.get('analysis_task')=='global_synthesis_report' for x in assignments),1)
        self.assertFalse(any(x.get('analysis_task') in ('global_semantic_map','normalize_categories','analysis_narrative') for x in assignments))
        self.assertEqual(len(s['approved_providers']),2);self.assertTrue(s['document_verified'])
        self.assertEqual(s['workspace_policy']['sync_batch_size'],100)
        db=runner.read_json(runner.run_dir('test-company')/'finalized_sheet.json')
        agg=ac.read(tf.home(runner.run_dir('test-company'),db)/'aggregation.json')
        self.assertIn(tf.OTHER,[x['name'] for x in agg['dimensions']['selection_requirements']])
        self.assertIn(tf.UNKNOWN,[x['name'] for x in agg['dimensions']['company_characteristics']])
        self.assertEqual(performance.summary(runner.run_dir('test-company'))['1']['human_interventions'],1)
    def test_100_metadata_candidates_do_not_launch_100_deep_reads(self):
        env={'FAKE_CASES':'100'}
        self.cmd('app','Research Test Company — https://example.com','--codex',legacy.FAKE,env=env)
        self.cmd('app','Approve these competitors: Beta Software','--codex',legacy.FAKE,'--max-tasks','1',env=env)
        base=runner.run_dir('test-company');s=self.state();ledger=runner.read_json(runner.screening_path(base))
        self.assertEqual(len(ledger),100);self.assertEqual(s['research_policy']['review_batch_size'],20)
        self.assertFalse((base/'extracted.json').exists());self.assertFalse((base/'research/batches').exists())
        self.assertEqual(runner.coverage_plan(base,s)['action'],'discover')
    def test_source_budget_yields_completed_prefix_without_quota_retry(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        base=runner.run_dir('test-company');s=self.state();s.update(phase='stage2',approved_providers=['Test Company']);s['research_policy']['max_source_attempts']=1;runner.save(base,s)
        cases=[{'id':str(n),'provider':'Test Company','url':'https://example.com/case/'+str(n),'customer':'Customer '+str(n),'title':'Story'} for n in range(3)]
        import os
        with patch.dict(os.environ,{'FAKE_MODE':'batch_budget'}),patch.object(runner,'provider_scope',return_value={'product':'Test'}):
            self.assertTrue(runner.run_review_batch(base,s,{'cases':cases,'provider':'Test Company'},10,legacy.FAKE))
        self.assertEqual(s['phase'],'stage2');self.assertEqual(len(runner.read_json(base/'extracted.json')),2)
        self.assertFalse(runner.case_receipt_path(base,s,'2').exists())
        self.assertEqual(sum(j['attempts'] for j in s['jobs'].values()),1)

    def test_known_failed_pdf_short_circuits_without_worker(self):
        self.cmd('init','--company','Test Company','--website','https://example.com')
        base=runner.run_dir('test-company');s=self.state();c={'id':'pdf','provider':'Test Company','url':'https://example.com/case.pdf','customer':'Unknown','title':'PDF'}
        research.remember(base,runner.atomic_json,capture={'url':c['url'],'coverage':'failed','text':'First attempt failed'},provider=c['provider'])
        with patch.object(runner,'provider_scope',return_value={'product':'Test'}),patch.object(runner,'invoke',side_effect=AssertionError('Known failure must not launch worker')):
            self.assertTrue(runner.run_review_batch(base,s,{'cases':[c],'provider':'Test Company'},1,'offline'))
        self.assertEqual(runner.read_json(runner.screening_path(base))['pdf']['decision'],'unresolved')

if __name__=='__main__':unittest.main()
