import copy
import unittest
import semantic_synthesis as ss
import analysis_pipeline as ap
from test_analysis_pipeline import fixture, record, observation
import workspace
import synthesis_publication as sp
import runner
import tempfile
from pathlib import Path


class GlobalSynthesisTests(unittest.TestCase):
    def setup_data(self):
        db=fixture(4);records={cid:record(cid) for cid in db['case_ids']}
        records['0']['buying_situations']=[observation('Conflicting dashboards','Needed measurement')]
        records['1']['buying_situations']=[observation('Fragmented attribution','Needed measurement')]
        records['2']['buying_situations']=[observation('Referral friction','deep linking')]
        records['3']['buying_situations']=[observation('Growth ambition','Needed measurement')]
        return db,records,ap.profile_index(db,records)

    def maps(self,db,records,index):
        cats={d:ss.catalog(db,records,index,d) for d in ss.DIMS};maps={}
        for dim,cat in cats.items():
            if dim=='buying_situations':
                ids={x['label']:x['id'] for x in cat['labels']}
                nodes=[dict(id='measurement',parent_id='',name='Measurement reliability',definition='Untrustworthy acquisition measurement',distinction='Excludes routing friction',kind='trigger',members=[]),
                    dict(id='conflict',parent_id='measurement',name='Conflicting reports',definition='Reports disagree',distinction='Different reports',kind='trigger',members=[ids['Conflicting dashboards']]),
                    dict(id='fragment',parent_id='measurement',name='Fragmented data',definition='No unified source',distinction='Data fragmentation',kind='trigger',members=[ids['Fragmented attribution']]),
                    dict(id='referral',parent_id='',name='Referral friction',definition='Referrals lose context',distinction='Journey issue not measurement',kind='trigger',members=[ids['Referral friction']]),
                    dict(id='growth',parent_id='',name='Growth goal',definition='Generic ambition',distinction='No causal pressure',kind='goal',members=[ids['Growth ambition']])]
            else:
                nodes=[dict(id='all',parent_id='',name=dim,definition='Synthetic homogeneous fixture',distinction='Fixture only',kind='descriptive',members=[x['id'] for x in cat['labels']])]
            maps[dim]={'nodes':nodes,'observation_overrides':[],'review_notes':'All batches reviewed.'}
        return cats,maps

    def test_cross_batch_related_children_roll_up_by_unique_profile(self):
        db,records,index=self.setup_data();cats,maps=self.maps(db,records,index)
        # Cases 0,1,2 are the SAME customer; two independently discovered
        # measurement labels must not produce two customers in the parent.
        agg=ss.aggregate(db,records,index,cats,maps)
        b={n['id']:n for n in agg['dimensions']['buying_situations']}
        self.assertEqual(b['conflict']['profile_count'],1)
        self.assertEqual(b['fragment']['profile_count'],1)
        self.assertEqual(b['measurement']['profile_count'],1)
        self.assertEqual(len(b['measurement']['case_ids']),2)
        self.assertEqual(b['measurement']['percent'],50)
        self.assertEqual(b['measurement']['providers'],{'Provider 0':1,'Provider 1':1})
        # Referral stays distinct, but the same profile may have both situations.
        self.assertEqual(b['referral']['profile_ids'],b['measurement']['profile_ids'])
        self.assertNotEqual(b['referral']['id'],b['measurement']['id'])
        self.assertEqual(b['growth']['semantic_kinds']['goal']['profile_count'],1)
        self.assertNotIn('trigger',b['growth']['semantic_kinds'])

    def test_complete_immutable_evidence_catalog_and_semantic_overrides(self):
        db,records,index=self.setup_data();before=copy.deepcopy(records);cats,maps=self.maps(db,records,index)
        maps['buying_situations']['observation_overrides']=[{'ref':'0:0','kind':'uncertain','reason':'Saved chronology does not establish adoption motivation.'}]
        agg=ss.aggregate(db,records,index,cats,maps)
        self.assertEqual(records,before)
        self.assertEqual(set(agg['record_ids']),set(db['case_ids']))
        b=next(x for x in agg['dimensions']['buying_situations'] if x['id']=='conflict')
        self.assertEqual(b['semantic_kinds']['uncertain']['profile_count'],1)
        self.assertEqual(b['observations'][0]['evidence'],'Needed measurement')

    def test_evidence_specific_annotation_corrects_label_without_mutating_original(self):
        db,r,i=self.setup_data();before=copy.deepcopy(r);cats,maps=self.maps(db,r,i)
        # A saved broad label is corrected only for its evidence-specific record.
        maps['buying_situations']['observation_annotations']=[{
            'ref':'0:0','node_ids':['referral'],'evidence':'Needed measurement',
            'reason':'Synthetic semantic review fixture.'}]
        agg=ss.aggregate(db,r,i,cats,maps)
        b={n['id']:n for n in agg['dimensions']['buying_situations']}
        self.assertEqual(b['conflict']['profile_count'],0)
        self.assertEqual(b['referral']['profile_count'],1)
        self.assertEqual(r,before)
        maps['buying_situations']['observation_annotations'][0]['node_ids']=['growth']
        goal=next(n for n in ss.aggregate(db,r,i,cats,maps)['dimensions']['buying_situations'] if n['id']=='growth')
        self.assertEqual(goal['semantic_kinds']['goal']['profile_count'],2)
        self.assertNotIn('trigger',goal['semantic_kinds'])
        maps['buying_situations']['observation_annotations'][0]['evidence']='Invented quote'
        with self.assertRaisesRegex(workspace.WorkspaceError,'differs from frozen'):
            ss.aggregate(db,r,i,cats,maps)

    def test_missing_duplicate_labels_and_cycles_rejected(self):
        db,r,i=self.setup_data();cats,maps=self.maps(db,r,i);cat=cats['buying_situations']
        for mode in ('missing','duplicate','cycle'):
            bad=copy.deepcopy(maps['buying_situations'])
            if mode=='missing':bad['nodes'][1]['members']=[]
            if mode=='duplicate':bad['nodes'][2]['members']+=bad['nodes'][1]['members']
            if mode=='cycle':bad['nodes'][0]['parent_id']='conflict'
            with self.assertRaises(workspace.WorkspaceError):ss.validate_map(cat,bad)

    def test_exclusive_company_counts_and_unknown_profiles(self):
        db,r,i=self.setup_data();cats,maps=self.maps(db,r,i)
        agg=ss.aggregate(db,r,i,cats,maps)
        roots=[n for n in agg['dimensions']['company_category'] if not n['parent_id']]
        self.assertEqual(sum(n['profile_count'] for n in roots),len(i['profiles']))
        self.assertEqual(len(i['profiles']),2)  # anonymous stays separate

    def test_outcomes_never_become_triggers_and_large_tables_rejected(self):
        db,r,i=self.setup_data();r['0']['buying_situations'][0]['evidence_strength']='outcome_only'
        cats,maps=self.maps(db,r,i);agg=ss.aggregate(db,r,i,cats,maps)
        node=next(x for x in agg['dimensions']['buying_situations'] if x['id']=='conflict')
        self.assertNotIn('trigger',node['semantic_kinds'])
        self.assertEqual(node['semantic_kinds']['outcome']['profile_count'],1)
        text='\n\n'.join('# '+x for x in workspace.REPORT_SECTIONS)+'\n\n'+'\n'.join('| x |' for _ in range(25))
        with self.assertRaisesRegex(workspace.WorkspaceError,'table is too large'):ss.validate_report(text)

    def test_completed_global_maps_reused_after_interruption(self):
        db,r,i=self.setup_data();cats,maps=self.maps(db,r,i)
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);calls=[]
            class API:
                atomic_json=staticmethod(runner.atomic_json)
                checkpoint_job=staticmethod(lambda *a:None)
                save=staticmethod(lambda *a:None)
                @staticmethod
                def invoke(base,state,stage,key,ctx,*args):
                    calls.append(ctx['dimension'])
                    if len(calls)==2:raise RuntimeError('Synthetic interruption')
                    return maps[ctx['dimension']]
            with self.assertRaisesRegex(RuntimeError,'interruption'):ss.ensure(API,base,{},db,r,i,1,'fake')
            self.assertTrue((ss.home(base,db)/'buying_situations.json').exists())
            calls.clear()
            API.invoke=staticmethod(lambda base,state,stage,key,ctx,*args:(calls.append(ctx['dimension']) or maps[ctx['dimension']]))
            ss.ensure(API,base,{},db,r,i,1,'fake')
            self.assertNotIn('buying_situations',calls)
            self.assertEqual(len(calls),4)

    def test_publication_cleanup_preserves_frozen_checksum_ids_and_five_cells(self):
        db,r,i=self.setup_data();db['rows'][1][4]='INACCESSIBLE — saved failure';db['complete']-=1;db['unavailable']=1
        before=copy.deepcopy(db);original=[db['headers']]+db['rows']+[['']*5 for _ in range(3)]
        req=sp.sheet_cleanup_requests(db,original,8,7)
        self.assertEqual(req,[{'deleteDimension':{'range':{'sheetId':7,'dimension':'ROWS','startIndex':2,'endIndex':3}}}])
        cleaned=copy.deepcopy(original);del cleaned[2]
        p=sp.projection(db);sp.verify_projection(p,cleaned,7)
        self.assertEqual(db,before);self.assertEqual(len(p['rows']),3);self.assertEqual(len(p['inaccessible_audit']),1)
        self.assertEqual(p['source_database_sha256'],db['sha256'])
        modified=copy.deepcopy(original);modified[1][1]='Unexpected edit'
        with self.assertRaisesRegex(workspace.WorkspaceError,'refusing cleanup'):sp.sheet_cleanup_requests(db,modified,8,7)

    def test_native_replacement_uses_utf16_revision_guard_and_compact_tables(self):
        old={'documentId':'same-doc','revisionId':'old-rev','tabs':[{'tabId':'t','body':{'content':[{'startIndex':1,'endIndex':50,'paragraph':{}}]}}]}
        md='\n\n'.join('# '+s+'\nEvidence 😀.'+ ('\n\n| Group | Count |\n| --- | ---: |\n| A | 1 |' if s=='Company profiles' else '') for s in workspace.REPORT_SECTIONS)
        plan,tables=sp.document_replace_plan(old,md)
        self.assertEqual(plan['document_id'],'same-doc');self.assertEqual(plan['write_control'],{'requiredRevisionId':'old-rev'})
        self.assertEqual(len(tables),1);self.assertEqual(tables[0]['rows'],[['Group','Count'],['A','1']])
        self.assertEqual(sp.u16('😀'),2)

    def test_editorial_context_keeps_all_counts_without_repeating_deep_examples(self):
        db,r,i=self.setup_data();cats,maps=self.maps(db,r,i)
        maps['buying_situations']['nodes'][1]['parent_id']='fragment'
        agg=ss.aggregate(db,r,i,cats,maps);ctx=ss.report_context(db,agg)
        source={n['id']:n for n in agg['dimensions']['buying_situations'] if n['profile_count']}
        delivered={n['id']:n for n in ctx['global_hierarchy']['buying_situations']}
        self.assertEqual(set(source),set(delivered))
        for nid,node in source.items():self.assertEqual(delivered[nid]['profile_count'],node['profile_count'])
        self.assertEqual(delivered['conflict']['examples'],[])
        self.assertTrue(delivered['measurement']['examples'])

    def test_native_table_fill_avoids_unsupported_page_break_property(self):
        # Regression for actual Google Docs INVALID_ARGUMENT: cannot update
        # page-break-before when a range contains paragraphs in a table.
        cells=[{'content':[{'startIndex':n,'endIndex':n+1,'paragraph':{}}]} for n in (12,14,18,20)]
        native={'documentId':'same-doc','revisionId':'guarded','tabs':[{'tabId':'t','body':{'content':[
            {'startIndex':10,'endIndex':24,'table':{'tableRows':[{'tableCells':cells[:2]},{'tableCells':cells[2:]}]}}
        ]}}]}
        plan=sp.table_fill_plan(native,[{'rows':[['Group','Count'],['A','1']]}])
        self.assertEqual(plan['write_control'],{'requiredRevisionId':'guarded'})
        styles=[r['updateParagraphStyle'] for r in plan['requests'] if 'updateParagraphStyle' in r]
        self.assertTrue(styles)
        self.assertTrue(all('pageBreakBefore' not in r['fields'] for r in styles))
        inserts=[r['insertText']['location']['index'] for r in plan['requests'] if 'insertText' in r]
        self.assertEqual(inserts,[20,18,14,12])

    def test_unidentified_stakeholders_are_retained_but_not_counted_as_functions(self):
        db,r,i=self.setup_data();cats,maps=self.maps(db,r,i)
        maps['stakeholders']['nodes'][0]['countable_function']=False
        agg=ss.aggregate(db,r,i,cats,maps)
        self.assertEqual(agg['stakeholder_coverage']['profiles_with_named_stakeholders'],2)
        self.assertEqual(agg['stakeholder_coverage']['profiles_with_identified_functions'],0)
        self.assertEqual(agg['stakeholder_coverage']['profiles_with_only_unidentified_functions'],2)


if __name__=='__main__':unittest.main()
