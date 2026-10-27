"""Offline regressions for fresh-run report acceptance and publication."""
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import runner
import report_quality as quality
import report_roles
import semantic_synthesis as synthesis
import taxonomy_first
import workspace as ws
import document_tabs as tabs
import test_report_editorial as editorial_fixtures
import test_document_tabs as native_fixtures
import test_publication_grid as sheet_fixtures


def fixture():
    md,db,agg,_=editorial_fixtures.EditorialCountTests().fixture()
    db.update(case_ids=['a','b','c','d'],complete=4,unavailable=0,
              sheet={'id':'sheet','url':'https://example.invalid/sheet'})
    db['rows']=[list(r) for r in db['rows']]
    db['rows'][0][2]='Ada, Founder.'
    obs={'case_id':'a','profile_id':'p1','provider':'Synthetic','people':['Ada'],
         'strength':'explicit','semantic_kind':'descriptive','evidence':'Ada, Founder.',
         'involvement':'Implementation; purchasing authority unknown.'}
    agg['dimensions']['stakeholders']=[{'name':'Management','profile_count':1,'observations':[obs]}]
    for dim,nodes in agg['dimensions'].items():
        for i,n in enumerate(nodes):
            n.update(id=f'{dim}_{i}',parent_id='')
            n.setdefault('observations',[]);n.setdefault('semantic_kinds',{})
    db['sha256']=ws.digest(db)
    md=md.replace('Company profiles. People involved. Buying situations. Caveat.',
        'Eligible cases: 4; Preserved profiles: 4; Providers: 1; Inaccessible cases: 0.\n'
        '## Company profiles\nSoftware: 3 (75%).\n## People involved\n'
        'Founders and general management: 1 (25%).\n## Buying situations\n'
        'Engineering bottleneck: 2 (50%).\n## Caveat\nPublished cases are selective.')
    md=md.replace('| Founders |','| Founders and general management |')
    return md,db,agg,report_roles.derive(db,agg)


class FreshReportReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.md,self.db,self.agg,self.roles=fixture()

    def api(self,markdown=None):
        self.invocations=[]
        def invoke(base,state,stage,key,context,timeout,cli):
            self.invocations.append(runner.prompt_for(stage,context))
            return {'markdown':self.md if markdown is None else markdown}
        return SimpleNamespace(invoke=invoke,atomic_json=runner.atomic_json,
                               checkpoint_job=Mock(),save=Mock())

    def test_effective_synthesis_and_conditional_resolver_prompts(self):
        api=self.api()
        synthesis.report(api,self.base,{'company':'Synthetic'},self.db,self.agg,1,'never-launched')
        prompt=self.invocations[0]
        for phrase in ('Do NOT recommend','functional_role_frequencies','What it sells / does',
                       'Post-adoption outcomes','Eligible cases: N','Inaccessible cases: N'):
            self.assertIn(phrase,prompt)
        resolver=runner.prompt_for(5,{'analysis_task':'resolve_company_profiles','profiles':[]})
        self.assertIn('Choose exactly',resolver)
        for phrase in ('qualitative GTM','Label GTM','For analysis_narrative','For report_overview'):
            self.assertNotIn(phrase,resolver)
        legacy=(runner.ROOT/'prompts/analysis_worker.md').read_text()
        self.assertNotIn('qualitative GTM',legacy);self.assertNotIn('Label GTM',legacy)

    def test_actual_acceptance_rejects_counts_and_keeps_draft(self):
        for change in (lambda s:s.replace('Software | 3 | 75%','Software | 2 | 50%'),
                       lambda s:s.replace('| Synthetic | 4 |','| Synthetic | 3 |'),
                       lambda s:s.replace('Founder | 1 | 25%','Founder | 2 | 50%'),
                       lambda s:s.replace('Eligible cases: 4','Eligible cases: 5')):
            api=self.api(change(self.md))
            with self.subTest(change=change),self.assertRaisesRegex(ws.WorkspaceError,'Report reconciliation failed:.*Draft preserved'):
                synthesis.report(api,self.base,{'company':'Synthetic'},self.db,self.agg,1,'never-launched')
            api.checkpoint_job.assert_not_called();api.save.assert_not_called()
            draft=json.loads(next((self.base/'report_drafts').glob('*.json')).read_text())
            self.assertEqual(draft['markdown'],change(self.md))
            self.assertFalse((self.base/'report.json').exists())
            self.assertFalse((self.base/'workspace').exists())

    def test_overview_category_and_percentage_must_match_supporting_table(self):
        for changed in (self.md.replace('Software: 3 (75%)','Software: 2 (50%)'),
                        self.md.replace('Software: 3 (75%)','Software: 3 (70%)'),
                        self.md.replace('Providers: 1','Providers: 2')):
            with self.subTest(changed=changed),self.assertRaisesRegex(ws.WorkspaceError,'Overview'):
                quality.validate(changed,self.db,self.agg,self.roles,require_overview=True)

    def test_missing_summary_coverage_is_actionable(self):
        with self.assertRaisesRegex(ws.WorkspaceError,'Overview missing verifiable coverage figure: Providers'):
            quality.validate(self.md.replace('Providers: 1; ',''),self.db,self.agg,self.roles,require_overview=True)

    def test_duplicate_table_not_silently_collapsed(self):
        extra='\n| Provider | Eligible case entries |\n|---|---|\n| Synthetic | 4 |\n'
        with self.assertRaisesRegex(ws.WorkspaceError,'Missing/duplicate editorial table'):
            quality.validate(self.md+extra,self.db,self.agg,self.roles)

    def test_overlapping_roles_and_situations_need_not_sum_to_denominator(self):
        # Each named customer person has two explicit titles: the group union
        # counts are reproducible, and overlap legitimately exceeds 100%.
        obs=[]
        for i,(cid,name) in enumerate(zip(self.db['case_ids'],['Ada','Ben','Cal','Dan'])):
            self.db['rows'][i][2]=name+', Founder and CTO.'
            obs.append({'case_id':cid,'profile_id':cid,'people':[name]})
        self.agg['dimensions']['stakeholders'][0]['observations']=obs
        roles=report_roles.derive(self.db,self.agg)
        md=self.md.replace('| Founders and general management | Founder | 1 | 25% |',
           '| Founders and general management | Founder | 4 | 100% |\n| Engineering / technology leadership | CTO | 4 | 100% |')
        md=md.replace('Founders and general management: 1 (25%)','Founders and general management: 4 (100%)')
        self.agg['dimensions']['buying_situations'].append({'name':'Another pressure','profile_count':4,'semantic_kinds':{'trigger':{'profile_count':4}}})
        md=md.replace('| Engineering bottleneck | Delivery constraint | 2 | 50% |',
            '| Engineering bottleneck | Delivery constraint | 2 | 50% |\n| Another pressure | Observed | 4 | 100% |')
        self.assertEqual(quality.validate(md,self.db,self.agg,roles,require_overview=True)['profiles'],4)

    def test_rounding_tolerance_respects_displayed_precision(self):
        self.agg['distinct_profiles']=3;self.roles['denominator']=3
        self.agg['dimensions']['company_category'][0]['profile_count']=2
        md=self.md.replace('Software | 3 | 75%','Software | 2 | 67%').replace('Unknown | 1 | 25%','Unknown | 1 | 33.3%')
        md=md.replace('Profiles | 4 | 100%','Profiles | 3 | 100%').replace('Founder | 1 | 25%','Founder | 1 | 33.33%')
        md=md.replace('2 | 50%','2 | 66.67%').replace('1 | 25%','1 | 33.33%')
        md=md.replace('Preserved profiles: 4','Preserved profiles: 3').replace('Software: 3 (75%)','Software: 2 (67%)').replace('1 (25%)','1 (33.33%)').replace('2 (50%)','2 (66.67%)')
        self.assertEqual(quality.validate(md,self.db,self.agg,self.roles,require_overview=True)['profiles'],3)
        with self.assertRaises(ws.WorkspaceError):quality.validate(md.replace('2 | 67%','2 | 65%'),self.db,self.agg,self.roles)

    def test_zero_scaffolding_and_missing_titles_are_valid(self):
        self.agg['dimensions']['company_category'].append({'name':'Other','profile_count':0})
        self.roles['groups'].append({'group':'Unknown / insufficient evidence','count':0})
        self.assertEqual(quality.validate(self.md,self.db,self.agg,self.roles)['functional_title_coverage'],1)

    def test_no_recognized_titles_or_triggers_is_not_invalid_evidence(self):
        self.agg['dimensions']['stakeholders'][0]['observations']=[]
        self.agg['dimensions']['buying_situations'][0]['semantic_kinds']['trigger']['profile_count']=0
        roles=report_roles.derive(self.db,self.agg)
        md=self.md.replace('| Founders and general management | Founder | 1 | 25% |\n','')
        md=md.replace('| Engineering bottleneck | Delivery constraint | 2 | 50% |\n','')
        md=md.replace('Founders and general management: 1 (25%).','No recognized formal titles.')
        md=md.replace('Engineering bottleneck: 2 (50%).','Original triggers are not established.')
        self.assertEqual(quality.validate(md,self.db,self.agg,roles,require_overview=True)['functional_title_coverage'],0)

    def test_offline_fresh_report_through_native_publication_simulation(self):
        state={'id':'synthetic','company':'Synthetic','created_at':'synthetic','phase':'finalize_sheet','jobs':{},
               'approved_providers':['Synthetic'],
               'analysis_policy':dict(taxonomy_first.POLICY),
               'workspace_policy':{'native_doc_tabs':1,'complete_only':True,'sync_batch_size':100}}
        records=[dict(id=cid,provider=row[0].split('\n')[0],source_url=row[0].split('\n')[1],
                      customer=row[1],people=row[2],company_profile=row[3],buying_situation=row[4],status='complete',note='')
                 for cid,row in zip(self.db['case_ids'],self.db['rows'])]
        # Simulate the native single-tab Sheet bridge using the existing grid
        # fixture, including blank preflight, write, readback and final snapshot.
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        self.assertEqual(state.pop('workspace_pending')['kind'],'sheet_create')
        state['workspace_sheet']={'id':'synthetic-sheet','url':self.db['sheet']['url']}
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        metadata=sheet_fixtures.PublicationGridTests.metadata(self)
        ws.apply_response(self.base,state,state['workspace_pending'],metadata,runner.atomic_json)
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        grid=lambda rows,start=0:sheet_fixtures.PublicationGridTests.grid(self,rows,start)
        ws.apply_response(self.base,state,state['workspace_pending'],grid([ws.HEADERS]),runner.atomic_json)
        ws.ensure_sync(self.base,state,records,runner.atomic_json)
        ws.apply_response(self.base,state,state['workspace_pending'],grid([['']*5]*4,1),runner.atomic_json)
        self.assertEqual(state['workspace_pending']['kind'],'sheet_write')
        update=state['workspace_pending']['arguments']['requests'][0]['updateCells']
        self.assertEqual(update['range']['endColumnIndex'],5)
        ws.apply_response(self.base,state,state['workspace_pending'],{},runner.atomic_json)
        ws.apply_response(self.base,state,state['workspace_pending'],grid(ws.rows_for(records),1),runner.atomic_json)
        self.assertEqual(state['workspace_verified_ids'],self.db['case_ids'])
        ws.finalize(self.base,state,records,runner.atomic_json)
        p=state['workspace_pending']
        ws.apply_response(self.base,state,p,grid(p['details']['rows']),runner.atomic_json)
        self.assertTrue(ws.finalize(self.base,state,records,runner.atomic_json))
        self.db=ws.frozen_database(self.base,state)
        self.assertEqual(self.db['headers'],ws.HEADERS)
        self.assertTrue(all(len(r)==5 for r in self.db['rows']))
        self.assertEqual(self.db['sheet']['tab'],'Case studies')
        runner.atomic_json(taxonomy_first.home(self.base,self.db)/'aggregation.json',self.agg)
        seen=[]
        def fake_invoke(base,state,stage,key,context,timeout,cli):
            seen.append(runner.prompt_for(stage,context))
            state['jobs'][key]={'status':'returned','attempts':1}
            return {'markdown':self.md}
        with patch.object(runner,'invoke',side_effect=fake_invoke),patch('analysis_compact.classify_step',return_value=True):
            for stage in range(4,8):
                self.assertEqual(state['phase'],f'stage{stage}')
                self.assertTrue(runner.step(self.base,state,1,'never-launched'))
        self.assertEqual(len(seen),1)  # One report reused for Stages 4–7.
        self.assertEqual(state['phase'],'publish_report')
        runner.step(self.base,state,1,'never-launched')
        pending=state.pop('workspace_pending')
        self.assertEqual(pending['kind'],'doc_create')
        self.assertEqual(pending['arguments']['upload_mode'],'native_google_docs')
        # Native readback fixture; all connector interactions stay local.
        tab=lambda md,name,tid,scaffold=False: native_fixtures.DocumentTabTests.tab(self,md,name,tid,scaffold)
        state.update(workspace_document={'id':'doc','url':'https://example.invalid/doc'},document_layout_done=True)
        original=tab(self.md,'Tab 1','t.0')
        data={'documentId':'doc','revisionId':'rev','tabs':[original]}
        ws.apply_response(self.base,state,{'kind':'doc_verify','details':{}},data,runner.atomic_json)
        self.assertEqual(state.pop('workspace_pending')['kind'],'doc_tabs_add')
        sections=tabs.sections(self.md)
        data['tabs'] += [tab('',name,f't.{i}') for i,name in enumerate(tabs.TITLES[1:],1)]
        tabs.organize(self.base,state,data,runner.atomic_json)
        self.assertEqual(state.pop('workspace_pending')['kind'],'doc_tabs_write')
        data['tabs'][1:]=[tab(s,n,f't.{i}',scaffold=True) for i,(s,n) in enumerate(zip(sections[1:],tabs.TITLES[1:]),1)]
        tabs.organize(self.base,state,data,runner.atomic_json)
        self.assertEqual(state.pop('workspace_pending')['kind'],'doc_tabs_fill')
        data['tabs'][1:]=[tab(s,n,f't.{i}') for i,(s,n) in enumerate(zip(sections[1:],tabs.TITLES[1:]),1)]
        tabs.organize(self.base,state,data,runner.atomic_json)
        finish=state.pop('workspace_pending')
        boundary=next(r['deleteContentRange']['range']['startIndex'] for r in finish['arguments']['requests'] if 'deleteContentRange'in r)
        data['tabs'][0]['body']['content']=[e for e in original['body']['content'] if e['startIndex']<boundary]
        data['tabs'][0]['title']='Overview'
        self.assertTrue(tabs.organize(self.base,state,data,runner.atomic_json))
        self.assertEqual(state['phase'],'complete')
        self.assertTrue(all(tabs.matches(t,s) for t,s in zip(data['tabs'],sections)))
        self.assertEqual(tabs.compact(''.join(tabs.text(tabs.body(t)) for t in data['tabs'])),tabs.compact(tabs.expected(self.md)))
        self.assertTrue(tabs.organize(self.base,state,data,runner.atomic_json))
        self.assertNotIn('workspace_pending',state)


if __name__=='__main__':unittest.main()
