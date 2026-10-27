import copy
import json
import unittest

import runner
import workspace as ws
import document_tabs as dt
import report_roles
import report_quality
import semantic_synthesis as synthesis
import test_document_tabs as fixtures


class RoleFrequencyTests(unittest.TestCase):
    def test_explicit_titles_unique_profile_unions_and_no_compilation_transfer(self):
        cells=[('a','p1','Ada, CTO; Ben, Founder and CEO. Testimonial speakers.',['Ada','Ben']),
               ('b','p1','Ada, CTO.',['Ada']),
               ('c','p2','Cal, article author. An outside CEO praised the product.',['Cal']),
               ('d','p3','Dan, Founding Engineer.',['Dan']),
               ('e','p4','Ada; Ben; roles unavailable.',['Ada','Ben']),
               ('f','p5','Eve, Sr. Platform Engineer.',['Eve'])]
        db={'case_ids':[c[0] for c in cells],'rows':[['Synthetic\nhttps://example.invalid',c[1],c[2],'',''] for c in cells]}
        agg={'distinct_profiles':5,'dimensions':{'stakeholders':[{'observations':[
            {'case_id':c,'profile_id':p,'people':names} for c,p,_,names in cells]}]}}
        before=copy.deepcopy((db,agg));result=report_roles.derive(db,agg);groups={g['group']:g for g in result['groups']}
        self.assertEqual(groups['Founders and general management']['count'],1)
        self.assertEqual(groups['Engineering / technology leadership']['count'],1)
        self.assertEqual(groups['Engineering roles']['count'],2)
        self.assertEqual(groups['Engineering roles']['share'],40)
        self.assertEqual(result['profiles_with_recognized_titles'],3)
        self.assertEqual(result['named_profiles_without_recognized_titles'],2)
        self.assertEqual((db,agg),before)
        self.assertNotIn('p4',set().union(*(set(g['profile_ids']) for g in result['groups'])))

    def test_ambiguous_titles_are_not_promoted_into_unrelated_functions(self):
        db={'case_ids':['a','b','c'],'rows':[['','','Ada, Principal Engineer.','',''],['','','Ben, Vice President of Engineering.','',''],['','','Cal, Senior Analyst, Finance.','','']]}
        agg={'distinct_profiles':3,'dimensions':{'stakeholders':[{'observations':[
            {'case_id':c,'profile_id':c,'people':[n]} for c,n in zip(db['case_ids'],['Ada','Ben','Cal'])]}]}}
        r=report_roles.derive(db,agg);g={x['group']:x['count'] for x in r['groups']}
        self.assertEqual(g['Founders and general management'],0)
        self.assertEqual(g['Technology / AI analysis'],0)

    def test_generic_builder_descriptions_are_not_formal_titles(self):
        db={'case_ids':['a','b','c'],'rows':[['','','Ada, principals/builders.','',''],['','','Ben, operations builder.','',''],['','','Cal, project builder.','','']]}
        agg={'distinct_profiles':3,'dimensions':{'stakeholders':[{'observations':[
            {'case_id':c,'profile_id':c,'people':[n]} for c,n in zip(db['case_ids'],['Ada','Ben','Cal'])]}]}}
        result=report_roles.derive(db,agg)
        self.assertEqual(result['profiles_with_recognized_titles'],0)
        self.assertEqual(result['named_profiles_without_recognized_titles'],3)


class EditorialPublicationTests(unittest.TestCase):
    setUp=fixtures.DocumentTabTests.setUp
    tab=fixtures.DocumentTabTests.tab
    data=fixtures.DocumentTabTests.data
    detail_tabs=fixtures.DocumentTabTests.detail_tabs

    def revised(self):return self.markdown.replace('Detailed caveat:','Clearer interpretation:')

    def begin(self):
        original=(self.base/'report.json').read_bytes();data=self.data(self.detail_tabs(),overview=True)
        dt.revise(self.base,self.state,self.revised(),data,runner.atomic_json)
        self.assertEqual((self.base/'report.json').read_bytes(),original)
        return data

    def test_editorial_revision_uses_existing_doc_and_tab_ids_with_revision_guard(self):
        self.begin();p=self.state['workspace_pending']
        self.assertEqual(p['kind'],'doc_edit_write')
        self.assertEqual(p['arguments']['document_id'],'doc')
        self.assertEqual(p['arguments']['write_control'],{'requiredRevisionId':'revision'})
        self.assertFalse(any('addDocumentTab'in r for r in p['arguments']['requests']))
        self.assertEqual(len(dt.load(self.base,self.state)),5)

    def test_unchanged_or_complete_readbacks_recover_without_duplicate_insertions(self):
        previous=self.begin();self.state.pop('workspace_pending')
        dt.edit_readback(self.base,self.state,previous,runner.atomic_json)
        self.assertEqual(self.state['workspace_pending']['kind'],'doc_edit_write')
        self.state.pop('workspace_pending');sections=dt.sections(self.revised())
        data={'documentId':'doc','revisionId':'new','tabs':[self.tab(s,n,'t.'+str(i)) for i,(s,n) in enumerate(zip(sections,dt.TITLES))]}
        self.assertTrue(dt.edit_readback(self.base,self.state,data,runner.atomic_json))
        self.assertEqual(self.state['phase'],'complete');self.assertNotIn('workspace_pending',self.state)
        self.assertTrue(all(dt.matches(t,s) for t,s in zip(data['tabs'],sections)))

    def test_scaffold_readback_only_fills_native_tables(self):
        self.begin();self.state.pop('workspace_pending');sections=dt.sections(self.revised())
        data={'documentId':'doc','revisionId':'new','tabs':[self.tab(s,n,'t.'+str(i),scaffold=True) for i,(s,n) in enumerate(zip(sections,dt.TITLES))]}
        dt.edit_readback(self.base,self.state,data,runner.atomic_json)
        self.assertEqual(self.state['workspace_pending']['kind'],'doc_edit_fill')
        self.assertFalse(any('deleteContentRange'in r or 'insertTable'in r for r in self.state['workspace_pending']['arguments']['requests']))

    def test_conflicting_native_content_blocks_editorial_overwrite(self):
        data=self.data(self.detail_tabs(),overview=True)
        data['tabs'][1]['body']['content'][1]['paragraph']['elements'][0]['textRun']['content']='Concurrent edit\n'
        with self.assertRaises(ws.WorkspaceError):dt.revise(self.base,self.state,self.revised(),data,runner.atomic_json)
        self.assertNotIn('editorial_report',self.state)


class EditorialCountTests(unittest.TestCase):
    def fixture(self):
        db={'case_ids':['case'],'rows':[['Synthetic\nhttps://example.invalid','Customer','','','']]*4,'provider_counts':{'Synthetic':4},'inaccessible_audit_count':0}
        def node(name,n,trigger=None):
            return {'name':name,'profile_count':n,**({'semantic_kinds':{'trigger':{'profile_count':trigger}}} if trigger is not None else {})}
        agg={'eligible_records':4,'distinct_profiles':4,'dimensions':{
            'company_category':[node('Software',3),node('Unknown / insufficient evidence',1)],
            'buying_situations':[node('Engineering bottleneck',3,2),node('Embedded connectivity',2),node('Faster delivery',1)],
            'selection_requirements':[node('Authentication',2)]}}
        roles={'denominator':4,'profiles_with_recognized_titles':1,'groups':[{'group':'Founders','count':1}]}
        md='''# Overview
Company profiles. People involved. Buying situations. Caveat.
# Company profiles
| Company type | What the company sells / does | Count | Share |
|---|---|---|---|
| Software | Software | 3 | 75% |
| Unknown / insufficient evidence | Unknown | 1 | 25% |
| Total | Profiles | 4 | 100% |
# People and stakeholders
| Functional role group | Representative actual titles | Count | Share |
|---|---|---|---|
| Founders | Founder | 1 | 25% |
# Buying situations
| Recurring situation | Business significance | Profiles | Share |
|---|---|---|---|
| Engineering bottleneck | Delivery constraint | 2 | 50% |

| Deployment context | Profiles | Share |
|---|---|---|
| Embedded connectivity | 2 | 50% |

| Requirement | Profiles | Share |
|---|---|---|
| Authentication | 2 | 50% |

| Reported outcome | Profiles | Share |
|---|---|---|
| Faster delivery | 1 | 25% |
# Methods and sources
| Provider | Eligible case entries |
|---|---|
| Synthetic | 4 |
| Total | 4 |
'''
        return md,db,agg,roles

    def test_all_report_tables_reconcile_to_saved_profile_counts(self):
        md,db,agg,roles=self.fixture();self.assertEqual(report_quality.validate(md,db,agg,roles)['tables_checked'],7)

    def test_broader_mentions_cannot_be_published_as_trigger_counts(self):
        md,db,agg,roles=self.fixture();md=md.replace('constraint | 2 | 50%','constraint | 3 | 75%')
        with self.assertRaises(ws.WorkspaceError):report_quality.validate(md,db,agg,roles)

    def test_wrong_denominators_or_missing_primary_groups_are_rejected(self):
        md,db,agg,roles=self.fixture()
        for changed in (md.replace('Founder | 1 | 25%','Founder | 1 | 20%'),md.replace('| Unknown / insufficient evidence | Unknown | 1 | 25% |\n','')):
            with self.assertRaises(ws.WorkspaceError):report_quality.validate(changed,db,agg,roles)


class NeutralFramingTests(unittest.TestCase):
    def test_explicit_and_disguised_business_recommendations_are_rejected(self):
        advice=["GTM implication", "People to engage", "Practical job titles for outreach",
                "Prioritize agent platforms.", "The target company should prioritize agent platforms.",
                "Lead with managed authentication.", "Ask which connector blocks the prospect's deal.",
                "These companies should be contacted first.", "This makes agents the best segment to target.",
                "These prospects deserve higher priority.", "For a prospect, measure time to connect."]
        for text in advice:
            with self.subTest(text=text),self.assertRaises(ws.WorkspaceError):report_quality.validate_neutral(text)

    def test_attributed_customer_decisions_and_descriptive_inference_are_retained(self):
        observations=["Tradestack prioritized reliable integrations and customer trust over catalog breadth.",
                      "Missing integrations stalled Lago's enterprise deals.",
                      "Agent platforms are the most frequent primary category in this collection.",
                      "The named CTO describes implementation; purchasing authority is unconfirmed.",
                      "A recurring pattern spans multiple providers, with differing source strength."]
        for text in observations:self.assertTrue(report_quality.validate_neutral(text))


class FutureReportContractTests(unittest.TestCase):
    def test_report_prompts_require_neutral_description_and_separate_functions(self):
        from pathlib import Path
        root=Path(__file__).resolve().parents[1]
        global_text=(root/'prompts/global_synthesis.md').read_text().split('For global_synthesis_report:',1)[1]
        fallback=(root/'prompts/07_report.md').read_text()
        for value in (global_text,fallback):
            value=' '.join(value.split())
            for required in ('Company profiles','People involved','Buying situations','caveat',
                             'What it sells / does','actual titles','Post-adoption outcomes'):
                self.assertIn(required.casefold(),value.casefold())
            self.assertNotIn('3500',value)
            self.assertIn('Other',value);self.assertIn('Unknown',value)
            self.assertNotIn('Connect evidence to the target',value)
            self.assertNotIn('prioritize workflow dependence',value)
            self.assertIn('not',value.casefold());self.assertIn('recommend',value.casefold())
        self.assertIn('functional_role_frequencies',global_text)
        self.assertIn('not organizational functions',' '.join(global_text.split()))

    def test_no_arbitrary_word_count_rejection_of_evidence_synthesis(self):
        text='\n\n'.join('# '+s for s in ws.REPORT_SECTIONS)
        text=text.replace('# Company profiles','# Company profiles\n\n'+'Useful detailed explanation. '*3000)
        synthesis.validate_report(text)
        synthesis.validate_report(text.replace('# Overview','# Overview\n'+'Observed pattern. '*451))

    def test_full_primary_company_table_is_not_silently_reduced_to_fit_a_row_cap(self):
        text='\n\n'.join('# '+s for s in ws.REPORT_SECTIONS)
        full='| Company type | What it sells / does | Count | Share |\n|---|---|---|---|\n'+'\n'.join(f'| Type {i} | Description | 1 | 3.33% |' for i in range(30))
        synthesis.validate_report(text.replace('# Company profiles','# Company profiles\n\n'+full))

    def test_future_context_counts_explicit_titles_separately_from_authorship(self):
        db={'sha256':'frozen','case_ids':['a'],'rows':[['Synthetic\nhttps://example.invalid','Customer','Ada, CEO, credited author.','','']],
            'sheet':{'url':'https://example.invalid/sheet'},'complete':1,'unavailable':0}
        obs={'case_id':'a','profile_id':'p1','provider':'Synthetic','strength':'explicit','semantic_kind':'descriptive',
             'people':['Ada'],'evidence':'Ada, CEO, credited author.','involvement':'Authorship only'}
        agg={'distinct_profiles':1,'dimensions':{'stakeholders':[{'id':'author','parent_id':'','name':'Credited authors',
            'profile_count':1,'observations':[obs],'semantic_kinds':{}}]}}
        context=synthesis.report_context(db,agg,'Synthetic');roles=context['functional_role_frequencies']
        self.assertEqual(roles['groups'][0]['name'],'Founders and general management')
        self.assertEqual(roles['groups'][0]['profile_count'],1)
        self.assertEqual(context['global_hierarchy']['stakeholders'][0]['examples'][0]['involvement'],'Authorship only')
        self.assertNotIn('evidence',roles['groups'][0])

    def test_legacy_report_writer_may_remove_source_advice_without_changing_source(self):
        database={'rows':[['Synthetic\nhttps://example.invalid/case','Customer','','','']], 'sheet':{'url':'https://example.invalid/sheet'}}
        analyses={'4':{'markdown':'Observed pressure: 17 profiles. Prioritize these prospects.'}}
        before=copy.deepcopy(analyses)
        markdown='\n\n'.join('# '+s for s in ws.REPORT_SECTIONS)+'\n\n| Observed pressure | Profiles |\n|---|---|\n| Engineering burden | 17 |'
        runner.validate_analysis(7,markdown,database,analyses)
        self.assertEqual(analyses,before)
        with self.assertRaises(ws.WorkspaceError):runner.validate_analysis(7,markdown+'\n\nPrioritize these prospects.',database,analyses)


if __name__=='__main__':unittest.main()
