import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import analysis_compact as ac
import analysis_pipeline as ap
import runner
import workspace
from test_analysis_pipeline import fixture,record


class CompactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.db=fixture(125)
        runner.atomic_json(self.base/'finalized_sheet.json',self.db)
        self.categories={};self.ids={}
        for dim in ac.DIMS:
            observations=[record('0')[dim]] if dim=='company_category' else record('0')[dim]
            for obs in observations:
                cid=ac.category_id(dim,obs['label'],obs['definition']);self.ids[obs['label']]=cid
                self.categories[cid]={'dimension':dim,'name':obs['label'],'definition':obs['definition'],'origin':'preliminary'}
        ac.save_registry(self.base,self.db,{'database_sha256':self.db['sha256'],'categories':self.categories,'legacy_case_ids':[], 'legacy_map':{d:{} for d in ac.DIMS}},runner.atomic_json)
        self.manifest={'run_dir':str(self.base),'database_sha256':self.db['sha256'],'case_ids':self.db['case_ids'],'key':'test','checkpoint_group_size':5}
    def tearDown(self):self.tmp.cleanup()
    def compact(self,cid):
        r=record(cid);out={k:r[k] for k in ('id','anonymous','aliases','identity_note','limitations')};out['observations']=[]
        for dim in ac.DIMS:
            for obs in ([r[dim]] if dim=='company_category' else r[dim]):
                cell=next(n for n in range(1,5) if obs['evidence'] in self.db['rows'][int(cid)][n])
                out['observations'].append({'cat':self.ids[obs['label']],'cell':cell,'quote':obs['evidence'],'strength':obs['evidence_strength'],'people':obs['people'],'involvement':obs['involvement']})
        return out
    def save(self,ids):return ac.checkpoint(self.manifest,{'records':[self.compact(cid) for cid in ids]},runner.atomic_json)
    def test_exact_evidence_dedup_and_scope_guards(self):
        self.save(['0','1']);before=(ac.home(self.base,self.db)/'records/0.json').read_bytes()
        self.save(['0','1']);self.assertEqual(before,(ac.home(self.base,self.db)/'records/0.json').read_bytes())
        self.assertEqual(len(ap.classifications(self.base,self.db)),2)
        bad=self.compact('2');bad['observations'][0]['quote']='Invented'
        with self.assertRaisesRegex(workspace.WorkspaceError,'not in'):ac.checkpoint(self.manifest,{'records':[bad]},runner.atomic_json)
        with self.assertRaisesRegex(workspace.WorkspaceError,'next assigned'):self.save(['4'])
        with self.assertRaisesRegex(workspace.WorkspaceError,'bound'):self.save([str(n) for n in range(6)])
        bad=self.compact('2');bad['observations'][0]['cat']='unknown'
        with self.assertRaisesRegex(workspace.WorkspaceError,'Unknown'):ac.checkpoint(self.manifest,{'records':[bad]},runner.atomic_json)
    def test_emergent_categories_and_auditable_references(self):
        row=self.compact('0');row['observations'][0]['cat']='N1'
        ack=ac.checkpoint(self.manifest,{'records':[row],'new_categories':[{'ref':'N1','dimension':'buying_situations','name':'Different trigger','definition':'Meaningfully different trigger'}]},runner.atomic_json)
        self.assertIn('N1',ack['registered_categories'])
        saved=json.loads((ac.home(self.base,self.db)/'records/0.json').read_text())['record']
        self.assertNotIn('quote',saved['observations'][0]);self.assertIn('source_sha256',saved['observations'][0]['evidence_ref'])
        self.assertEqual(ap.classifications(self.base,self.db)['0']['buying_situations'][0]['label'],'Different trigger')
    def test_actual_stdio_worker_interruption_and_resume_skip(self):
        path=self.base/'assignment.json';runner.atomic_json(path,self.manifest)
        proc=subprocess.Popen([sys.executable,str(runner.ROOT/'analysis_checkpoint_server.py'),str(path)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        def request(method,params):
            proc.stdin.write(json.dumps({'jsonrpc':'2.0','id':1,'method':method,'params':params})+'\n');proc.stdin.flush()
            return json.loads(proc.stdout.readline())['result']
        self.assertEqual(request('initialize',{'protocolVersion':'2024-11-05'})['serverInfo']['name'],'analysis_checkpoint')
        self.assertEqual(len(request('tools/list',{})['tools']),1)
        for start in (0,5):
            result=request('tools/call',{'name':'save_records','arguments':{'records':[self.compact(str(n)) for n in range(start,start+5)]}})
            self.assertFalse(result['isError'])
        proc.kill();proc.wait();proc.stdin.close();proc.stdout.close()
        self.assertEqual(len(ap.classifications(self.base,self.db)),10)
        outer=self
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            @staticmethod
            def invoke(base,state,stage,key,ctx,timeout,cli):
                ids=[r['id'] for r in ctx['records']]
                outer.assertEqual(len(ids),60);outer.assertTrue(set(ids).isdisjoint(str(n) for n in range(10)))
                raise RuntimeError('Stop before spending a model call')
        ap._fresh_calls=0
        with self.assertRaisesRegex(RuntimeError,'Stop before'):ac.classify_step(API,self.base,{'analysis_policy':dict(ac.POLICY)},self.db,1,'fake')
    def test_legacy_records_preserved_and_frequency_accounting(self):
        ap.commit(self.base,self.db,['0'],record('0'),runner.atomic_json)
        path=ap.root(self.base,self.db)/'records/0.json';before=path.read_bytes()
        reg=ac.registry(self.base,self.db);reg['legacy_case_ids']=['0'];ac.save_registry(self.base,self.db,reg,runner.atomic_json)
        self.manifest['case_ids']=self.db['case_ids'][1:];self.save(['1','2','3','4'])
        rows=ap.classifications(self.base,self.db);self.assertEqual(path.read_bytes(),before)
        self.assertEqual(len(rows),5)
        # Full final denominator cannot be calculated on an incomplete collection.
        db=fixture(5);index=ap.profile_index(db,rows);self.assertEqual(len(index['profiles']),3)
        tax={d:{ap.label_id(o):{'name':o['label'],'definition':o['definition']} for r in rows.values() for o in r[d]} for d in ap.DIMENSIONS[4]}
        agg=ap.aggregate(db,rows,index,tax,4)
        self.assertEqual([v['profile_count'] for v in agg['dimensions']['buying_situations']],[3,3])
    def test_preliminary_80_preserves_originals_and_final_reconciles_every_label(self):
        import shutil
        shutil.rmtree(ac.home(self.base,self.db))
        for cid in self.db['case_ids'][:80]:ap.commit(self.base,self.db,[cid],record(cid),runner.atomic_json)
        originals={p.name:p.read_bytes() for p in (ap.root(self.base,self.db)/'records').glob('*.json')}
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            checkpoint_job=staticmethod(lambda *a:None)
            save=staticmethod(lambda *a:None)
            @staticmethod
            def invoke(base,state,stage,key,ctx,timeout,cli):
                return {'categories':[{'name':v['label'],'definition':v['definition'],'members':[v['id']]} for v in ctx['labels']]}
        state={'jobs':{},'analysis_policy':dict(ac.POLICY)};ap._fresh_calls=0
        self.assertTrue(ac.prepare(API,self.base,state,self.db,60,'fake'))
        reg=ac.registry(self.base,self.db);self.assertEqual(len(reg['legacy_case_ids']),80)
        self.assertEqual(len(reg['legacy_map']['buying_situations']),2)
        saved=ap.classifications(self.base,self.db)
        for stage in (4,5,6):
            tax=ac.final_taxonomy(API,self.base,state,self.db,stage,saved,60,'fake')
            for dim in ap.DIMENSIONS[stage]:
                expected={ap.label_id(o) for r in saved.values() for o in ([r[dim]] if dim=='company_category' else r[dim])}
                self.assertEqual(set(tax[dim]),expected)
        self.assertEqual(originals,{p.name:p.read_bytes() for p in (ap.root(self.base,self.db)/'records').glob('*.json')})

    def test_runner_transport_60_records_and_failure_after_ten(self):
        import os
        self.manifest['case_ids']=self.db['case_ids'][:60]
        path=self.base/'assignment.json';runner.atomic_json(path,self.manifest)
        context={'analysis_task':'classify_compact','records':[{'id':c,'cells':self.db['rows'][int(c)]} for c in self.manifest['case_ids']],
                 'categories':self.categories,'checkpoint_manifest':str(path),'checkpoint_group_size':5}
        state={'jobs':{}}
        with patch.dict(os.environ,{'FAKE_MODE':'compact_interrupt'}):
            with self.assertRaises(runner.RunError):runner.codex_call(self.base,state,4,'pilot',context,60,str(runner.ROOT/'tests/fake_codex.py'))
        self.assertEqual(len(ap.classifications(self.base,self.db)),10)
        context['records']=context['records'][10:];self.manifest['case_ids']=self.manifest['case_ids'][10:];runner.atomic_json(path,self.manifest)
        with patch.dict(os.environ,{'FAKE_MODE':'ok'}):
            result=runner.codex_call(self.base,state,4,'resume',context,60,str(runner.ROOT/'tests/fake_codex.py'))
        self.assertEqual(len(result['completed_ids']),50)
        self.assertEqual(len(ap.classifications(self.base,self.db)),60)

    def test_per_tool_approval_is_scoped_and_sandbox_preserved(self):
        import os
        path=self.base/'assignment.json';runner.atomic_json(path,dict(self.manifest,case_ids=['0']))
        trace=self.base/'trace.jsonl'
        ctx={'analysis_task':'classify_compact','records':[{'id':'0','cells':self.db['rows'][0]}],
             'categories':self.categories,'checkpoint_manifest':str(path),'checkpoint_group_size':5}
        with patch.dict(os.environ,{'FAKE_MODE':'ok','FAKE_TRACE':str(trace)}):
            runner.codex_call(self.base,{'jobs':{}},4,'scoped',ctx,60,str(runner.ROOT/'tests/fake_codex.py'))
        args=json.loads(trace.read_text().splitlines()[0])['args']
        configs=[args[i+1] for i,v in enumerate(args[:-1]) if v=='-c']
        self.assertIn('mcp_servers.analysis_checkpoint.tools.save_records.approval_mode="approve"',configs)
        self.assertIn('mcp_servers.analysis_checkpoint.enabled_tools=["save_records"]',configs)
        self.assertIn('mcp_servers.analysis_checkpoint.required=true',configs)
        self.assertEqual(args[args.index('--sandbox')+1],'read-only')
        self.assertFalse(any('default_tools_approval_mode' in c for c in configs))
        self.assertFalse(any('danger' in a or 'bypass' in a for a in args))
        self.assertEqual(len(ap.classifications(self.base,self.db)),1)

    def test_explicit_resume_rejects_empty_cache_without_inventing_checkpoints(self):
        ctx={'analysis_task':'classify_compact','records':[{'id':'0','cells':self.db['rows'][0]}]}
        key='failed-empty';state={'phase':'stage4','jobs':{key:{'status':'paused','attempts':1,'error_kind':'validation','response_ready':True}}}
        runner.atomic_json(self.base/'results'/f'{key}.json',{'completed_ids':[]})
        with patch.object(runner,'codex_call',return_value={'completed_ids':['0']}) as fresh:
            result=runner.invoke(self.base,state,4,key,ctx,1,'fake')
        self.assertEqual(result,{'completed_ids':['0']});self.assertEqual(fresh.call_count,1)
        self.assertEqual(state['jobs'][key]['attempts'],2)
        archived=Path(state['jobs'][key]['rejected_responses'][0]['path'])
        self.assertEqual(json.loads(archived.read_text()),{'completed_ids':[]})
        self.assertEqual(len(ap.classifications(self.base,self.db)),0)
        with patch.object(runner,'codex_call') as fresh:
            self.assertEqual(runner.invoke(self.base,state,4,key,ctx,1,'fake'),result)
            fresh.assert_not_called()

    def test_only_exact_checkpoint_tool_permitted(self):
        ctx={'analysis_task':'classify_compact'}
        item={'type':'mcp_tool_call','server':'analysis_checkpoint','tool':'save_records'}
        self.assertTrue(runner.allowed_analysis_item(ctx,item))
        self.assertFalse(runner.allowed_analysis_item({'analysis_task':'analysis_narrative'},item))
        self.assertFalse(runner.allowed_analysis_item(ctx,dict(item,tool='browse')))
        self.assertFalse(runner.allowed_analysis_item(ctx,{'type':'command_execution'}))

if __name__=='__main__':unittest.main()
