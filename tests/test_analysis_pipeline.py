import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import analysis_pipeline as ap
import runner
import research
import workspace


def fixture(count=45):
    rows=[]
    for n in range(count):
        rows.append(['Provider '+str(n%2)+'\nhttps://example.com/case/'+str(n),
                     'Acme' if n<3 else 'Anonymous customer' if n<5 else 'Customer '+str(n),
                     'Chris — CTO; implementation lead.', 'A software company.',
                     'Needed measurement and deep linking. Required dependable support.'])
    data={'sheet':{'url':'https://docs.google.com/spreadsheets/d/test/edit'},'headers':runner.HEADERS,
          'rows':rows,'case_ids':[str(n) for n in range(count)],'inventoried':count,'complete':count,
          'unavailable':0,'provider_counts':{'Provider 0':(count+1)//2,'Provider 1':count//2}}
    data['sha256']=workspace.digest(data)
    return data


def observation(label,evidence,people=None,strength='explicit'):
    return {'label':label,'definition':label+' definition','evidence':evidence,'people':people or [],
            'involvement':'Implementation; purchasing authority unknown.','evidence_strength':strength}


def record(cid):
    return {'id':cid,'anonymous':cid in ('3','4'),'aliases':[],'identity_note':'Only Sheet evidence.',
            'buying_situations':[observation('Measurement','Needed measurement'),observation('Linking','deep linking')],
            'selection_requirements':[observation('Support','dependable support')],
            'company_category':observation('Software','software company'), 'company_characteristics':[],
            'stakeholders':[observation('Engineering','Chris — CTO',['Chris'])], 'limitations':'Authority unavailable.'}


class AnalysisPipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.db=fixture()
    def tearDown(self):self.tmp.cleanup()
    def commit_all(self):
        for cid in self.db['case_ids']:ap.commit(self.base,self.db,self.db['case_ids'],record(cid),runner.atomic_json)
        return ap.classifications(self.base,self.db)
    def test_every_record_bounded_and_no_silent_truncation(self):
        self.db=fixture(466)
        items=[{'id':cid,'cells':row} for cid,row in ap.eligible_rows(self.db).items()]
        batches=list(ap.bounded(items,ap.POLICY))
        self.assertEqual(sum(map(len,batches)),466)
        self.assertTrue(all(len(b)<=20 for b in batches))
        self.assertEqual(len({x['id'] for b in batches for x in b}),466)
        with self.assertRaisesRegex(workspace.WorkspaceError,'no record was truncated'):
            list(ap.bounded([{'evidence':'x'*70000}],ap.POLICY))
        unicode_batches=list(ap.bounded([{'evidence':'界'*9000} for _ in range(3)],ap.POLICY))
        self.assertEqual(list(map(len,unicode_batches)),[2,1])
    def test_dedup_named_profiles_keep_anonymous_separate_and_overlaps(self):
        records=self.commit_all();index=ap.profile_index(self.db,records)
        self.assertEqual(len(index['profiles']),43)
        self.assertEqual(index['case_to_profile']['0'],index['case_to_profile']['2'])
        self.assertNotEqual(index['case_to_profile']['3'],index['case_to_profile']['4'])
        tax={d:{ap.label_id(o):{'name':o['label'],'definition':o['definition']} for r in records.values()
                 for o in ([r[d]] if d=='company_category' else r[d])} for d in ap.DIMENSIONS[4]}
        result=ap.aggregate(self.db,records,index,tax,4)
        self.assertEqual([e['profile_count'] for e in result['dimensions']['buying_situations']],[43,43])
        self.assertEqual(sum(e['profile_count'] for e in result['dimensions']['buying_situations']),86)
        self.assertEqual(result['classified_records'],45)
        self.assertEqual(result['dimensions']['buying_situations'][0]['providers'],{'Provider 0':22,'Provider 1':22})
    def test_quote_identity_immutability_and_checksum_guards(self):
        row=record('0');ap.commit(self.base,self.db,['0'],row,runner.atomic_json)
        path=ap.root(self.base,self.db)/'records/0.json';before=path.stat().st_mtime_ns
        ap.commit(self.base,self.db,['0'],row,runner.atomic_json)
        self.assertEqual(path.stat().st_mtime_ns,before)
        invalid=copy.deepcopy(row);invalid['buying_situations'][0]['evidence']='Invented source claim'
        with self.assertRaisesRegex(workspace.WorkspaceError,'exact quote'):ap.commit(self.base,self.db,['0'],invalid,runner.atomic_json)
        invalid=copy.deepcopy(row);invalid['limitations']='different'
        with self.assertRaisesRegex(workspace.WorkspaceError,'immutable'):ap.commit(self.base,self.db,['0'],invalid,runner.atomic_json)
        with self.assertRaisesRegex(workspace.WorkspaceError,'Unassigned'):ap.commit(self.base,self.db,['1'],row,runner.atomic_json)
        data=json.loads(path.read_text());data['record']['limitations']='tampered';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(workspace.WorkspaceError,'checksum'):ap.classifications(self.base,self.db)

    def test_cross_column_evidence_is_valid_only_within_the_same_sheet_row(self):
        row=record('0')
        row['company_characteristics']=[observation('Measurement requirement','Needed measurement')]
        ap.commit(self.base,self.db,['0'],row,runner.atomic_json)
        other=record('1');other['company_characteristics']=[observation('Invented','Different case fact')]
        self.db['rows'][2][4]+=' Different case fact'
        with self.assertRaisesRegex(workspace.WorkspaceError,'exact quote'):
            ap.commit(self.base,self.db,['1'],other,runner.atomic_json)
    def test_inaccessible_rows_accounted_separately_and_outcomes_not_triggers(self):
        self.db['rows'][-1][4]='INACCESSIBLE — first access failed';self.db['complete']-=1;self.db['unavailable']=1
        records={cid:record(cid) for cid in ap.eligible_rows(self.db)}
        for r in records.values():r['buying_situations'][0]['evidence_strength']='outcome_only'
        index=ap.profile_index(self.db,records)
        tax={d:{ap.label_id(o):{'name':o['label'],'definition':o['definition']} for r in records.values() for o in r[d]} for d in ap.DIMENSIONS[4]}
        agg=ap.aggregate(self.db,records,index,tax,4)
        metric=next(x for x in agg['dimensions']['buying_situations'] if x['name']=='Measurement')
        self.assertEqual(metric['profile_count'],0);self.assertEqual(len(metric['noncounted_case_ids']),44)
        self.assertEqual(len(records),44)
    def test_taxonomy_requires_complete_exact_partition(self):
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            checkpoint_job=staticmethod(lambda *args:None)
            save=staticmethod(lambda *args:None)
            @staticmethod
            def invoke(base,state,stage,key,context,timeout,cli):
                return {'categories':[{'name':'Missing labels','definition':'Bad fixture','members':[]}]}
        ap._fresh_calls=0
        with self.assertRaisesRegex(workspace.WorkspaceError,'Invalid'):
            ap.taxonomy(API,self.base,{'jobs':{}},self.db,4,{'0':record('0')},1,'fake')
    def test_final_result_recovery_reuses_completed_classifications(self):
        home=ap.root(self.base,self.db);key='saved-classification'
        runner.atomic_json(home/'jobs/job.json',{'key':key,'case_ids':['0','1']})
        runner.atomic_json(self.base/'results'/f'{key}.json',{'records':[record('0'),record('1')]})
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            save=staticmethod(lambda *args:None)
            checkpoint_job=staticmethod(lambda *args:None)
            @staticmethod
            def invoke(base,state,stage,key,context,timeout,cli):
                self.assertTrue(set(x['id'] for x in context['records']).isdisjoint({'0','1'}))
                self.assertEqual(len(context['records']),20)
                return {'records':[record(x['id']) for x in context['records']]}
        ap._fresh_calls=0
        ap.classify_step(API,self.base,{'jobs':{}},self.db,1,'fake')
        self.assertEqual(len(ap.classifications(self.base,self.db)),22)

    def test_analysis_assignment_uses_only_native_cells_and_bounded_metadata(self):
        self.db['case_notes']={'0':'Non-Sheet research must never enter analysis.'}
        self.db['screening_summary']={'secret':'source-capture material'}
        class API:
            atomic_json=staticmethod(runner.atomic_json)
            save=staticmethod(lambda *args:None)
            checkpoint_job=staticmethod(lambda *args:None)
            @staticmethod
            def invoke(base,state,stage,key,context,timeout,cli):
                payload=json.dumps(context)
                self.assertNotIn('Non-Sheet',payload);self.assertNotIn('source-capture',payload)
                self.assertEqual(len(context['records']),20)
                return {'records':[record(x['id']) for x in context['records']]}
        ap._fresh_calls=0
        ap.classify_step(API,self.base,{'jobs':{}},self.db,1,'fake')

    def test_stage3_packs_unfinished_cases_across_sparse_saved_batches(self):
        inventory={p:[{'id':p+str(i),'provider':p,'url':'https://example.com/'+p+'/'+str(i),'customer':'Acme'} for i in range(5)] for p in ('A','B','C')}
        runner.atomic_json(self.base/'batches.json',runner.compile_batches(inventory,limit=5))
        state={'phase':'stage3','jobs':{},'company':'Test','approved_providers':['A','B','C'],'research_policy':dict(research.POLICY)}
        runner.save(self.base,state)
        def invoke(base,state,stage,key,context,*args):
            self.assertEqual(len(context['assigned_cases']),15)
            self.assertEqual(set(context['competing_products']),{'A','B','C'})
            return {'records':[{'provider':c['provider'],'source_url':c['url'],'customer':c['customer'],'people':'','company_profile':'','buying_situation':'','status':'inaccessible','note':'Saved failure; no retry.'} for c in context['assigned_cases']]}
        with patch.object(workspace,'ensure_sync',return_value=True),patch.object(runner,'invoke',side_effect=invoke),patch.object(runner,'provider_scope',return_value={}):
            self.assertTrue(runner.step(self.base,state,1,'fake'))
        self.assertEqual(len(runner.read_json(self.base/'extracted.json')),15)


if __name__=='__main__':unittest.main()
