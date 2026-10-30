"""Assignment projection and streaming protocol; synthetic offline evidence only."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import research
import runner
import workspace
import test_efficiency as efficiency
import test_listing_lifecycle as lifecycle


class WorkerContextTests(unittest.TestCase):
    setUp=efficiency.EfficiencyTests.setUp
    tearDown=efficiency.EfficiencyTests.tearDown
    cmd=efficiency.EfficiencyTests.cmd
    state=efficiency.EfficiencyTests.state
    fixture=efficiency.EfficiencyTests.fixture
    record=efficiency.EfficiencyTests.record
    result=efficiency.EfficiencyTests.result
    traced_assignments=efficiency.EfficiencyTests.traced_assignments
    setup_listing=lifecycle.ListingLifecycleTests.setup_listing
    page=lifecycle.ListingLifecycleTests.page
    apply=lifecycle.ListingLifecycleTests.apply
    unresolved=lifecycle.ListingLifecycleTests.unresolved

    def test_only_active_mode_instructions_are_sent(self):
        base,cases=self.fixture(1)
        common={'efficient_worker':True,'review_batch_size':20,'max_cases':30}
        modes=[({'task':'discover','first_listing_entries':30},'natural order','Resolve ONLY'),
               ({'task':'discover','url_recovery':True,'recovery_slots':[]},'Resolve ONLY','listing_contract_v2'),
               ({'task':'review_batch','review_cases':cases},'Process only review_cases','recovery_slots'),
               ({'task':'extract_batch','assigned_cases':cases},'Process only assigned_cases','natural order'),
               ({'task':'discover'},'thematic saturation','Resolve ONLY')]
        for ctx,wanted,absent in modes:
            prompt=runner.prompt_for(3 if ctx['task']=='extract_batch' else 2,dict(common,**ctx))
            self.assertIn(wanted,prompt);self.assertNotIn(absent,prompt)
            for term in ('purchasing authority','adoption chronology','uncertain cases','source_captures','COMMENTARY'):
                self.assertIn(term,prompt)
        prompt=runner.prompt_for(2,dict(common,task='discover',first_listing_entries=30,listing_only=True))
        self.assertIn('do not open any case',prompt)
        self.assertNotIn('A complete record contains',prompt)

    def test_projection_preserves_scope_uncertainty_and_only_assigned_source_memory(self):
        base,cases=self.fixture(1);case=cases[0]
        research.remember(base,runner.atomic_json,provider=case['provider'],capture={
            'url':case['url'],'coverage':'full_text','text':'Verbatim case with linked https://docs.example.net/failed.pdf'})
        research.remember(base,runner.atomic_json,provider='Other',capture={
            'url':'https://docs.example.net/failed.pdf','coverage':'failed','text':'Recorded PDF failure.'})
        research.remember(base,runner.atomic_json,provider='Other',capture={
            'url':'https://unrelated.example.com/failure.pdf','coverage':'failed','text':'Unrelated failure.'})
        research.remember(base,runner.atomic_json,provider=case['provider'],capture={
            'url':'https://beta.example.com/archive','role':'listing','coverage':'excerpt','text':'Unneeded listing history.'})
        ctx={'target':'Test Company','task':'review_batch','approved_provider':case['provider'],
             'review_cases':cases,'product_understanding':runner.product_understanding(base)}
        ctx['evidence_memory']=research.assignment_memory(base,ctx)
        before=copy.deepcopy(ctx);out=research.model_context(ctx)
        self.assertEqual(ctx,before)
        self.assertEqual(set(out['evidence_memory']['sources']),{case['url']})
        self.assertEqual(out['evidence_memory']['sources'][case['url']]['text'],'Verbatim case with linked https://docs.example.net/failed.pdf')
        self.assertEqual(set(out['evidence_memory']['known_access_failures']),{'https://docs.example.net/failed.pdf'})
        self.assertEqual(len(research.failed_sources(base)),2)
        self.assertEqual(out['target_scope']['workflow'],ctx['product_understanding']['core_workflow'])
        self.assertEqual(out['target_scope']['uncertainties'],ctx['product_understanding']['uncertainties'])
        self.assertEqual(out['competing_products'][case['provider']],case['competing_product'])
        self.assertNotIn('competing_product',out['review_cases'][0])
        self.assertNotIn('product_understanding',out)
        self.assertEqual(research.model_context(out),out)

    def test_recovery_removes_nine_assigned_eleven_witnessed_overlap(self):
        slots=[{'listing_position':i,'listing_url':'https://vendor.test/stories','title':f'Exact title {i}',
                'customer':f'Customer {i}','url':None,'id':f'slot-{i}','provider':'Vendor',
                'evidence':'Witnessed title and position.','reason':'URL not exposed.'} for i in range(1,12)]
        ctx={'target':'Target','approved_provider':'Vendor','task':'discover','url_recovery':True,
             'recovery_slots':slots[:9],'selected_listing_entries':slots,
             'completed_provider_records':[{'id':'complete-1','provider':'Vendor','source_url':'https://vendor.test/done',
                                            'customer':'Saved Customer','people':'Long irrelevant completed body'}],
             'known_case_urls':['https://vendor.test/done','https://other.test/done'],
             'completed_case_urls':['https://vendor.test/done','https://other.test/done'],
             'competing_product':{'product':'Approved line','reason':'Required shared capability','sources':['https://vendor.test']}}
        before=copy.deepcopy(ctx);out=research.model_context(ctx)
        self.assertEqual(len(out['recovery_slots']),9)
        for original,row in zip(slots,out['recovery_slots']):
            for key in ('listing_position','listing_url','title','customer','evidence'):self.assertEqual(original[key],row[key])
        for key in ('selected_listing_entries','known_case_urls','completed_case_urls','completed_provider_records'):self.assertNotIn(key,out)
        self.assertEqual(out['completed_sources'],[{'id':'complete-1','url':'https://vendor.test/done','customer':'Saved Customer'}])
        self.assertEqual(ctx,before)

    def test_target_own_cases_retain_full_capability_descriptions(self):
        base,cases=self.fixture(1);product=runner.product_understanding(base)
        out=research.model_context({'target':'Test Company','approved_provider':'Test Company','product_understanding':product})
        self.assertEqual(out['target_scope']['capabilities'][0]['description'],product['capabilities'][0]['description'])
        self.assertEqual(out['target_scope']['summary'],product['summary'])

    def test_association_captures_are_retained_once_and_without_truncation(self):
        url='https://vendor.test/case';text='Complete reusable evidence. '*1000
        capture={'url':url,'coverage':'full_text','text':text,'listing_association':{'title':'Exact title','position':1,'quote':'Complete reusable evidence.'}}
        ctx={'url_recovery':True,'recovery_slots':[{'listing_url':'https://vendor.test/stories','listing_position':1,'title':'Exact title','customer':'Unknown'}],
             'saved_candidate_urls':{'1':[{'url':url}]},'saved_candidate_captures':{url:[capture]},
             'evidence_memory':{'sources':{url:capture},'completed_searches':{'old':{}},'known_access_failures':{},'known_tool_failures':{}}}
        out=research.model_context(ctx)
        self.assertEqual(out['saved_candidate_captures'][url],[capture])
        self.assertNotIn(url,out['evidence_memory']['sources'])
        self.assertEqual(out['evidence_memory']['completed_searches'],{})
        self.assertEqual(out['saved_candidate_captures'][url][0]['text'],text)

    def test_combined_proof_and_case_persist_in_dependency_order(self):
        base,state,_=self.setup_listing();obj,_=self.unresolved(base,state,1);self.apply(base,state,obj)
        assigned=obj['cases'][0];url='https://stories.example.com/confirmed'
        row=dict(assigned,url=url,url_status='content_confirmed',decision='relevant',reading_depth='substantive',
                 record=self.record({'provider':'Beta Software','url':url,'customer':assigned['customer']}))
        capture={'url':url,'coverage':'excerpt','text':'Story 1 uses the approved product.',
                 'listing_association':{'listing_url':assigned['listing_url'],'position':1,'title':'Story 1','quote':'Story 1 uses the approved product.'}}
        ctx={'approved_provider':'Beta Software','task':'discover','first_listing_entries':30,'url_recovery':True,
             'ordinary_resolution':True,'recovery_slots':[state['listing_universes']['Beta Software']['entries'][0]],
             'competing_product':runner.provider_scope(base,state,'Beta Software'),'max_cases':1}
        message={'source_captures':[capture],'discovered_case':row}
        runner.commit_worker_message(base,state,'combined',ctx,message,'offline')
        cid=runner.case_id('Beta Software',url)
        self.assertEqual(runner.read_json(base/'extracted.json')[cid]['source_url'],url)
        self.assertTrue(list(research.captures_for(base,'Beta Software',url)))
        saved=(base/'extracted.json').read_bytes()
        runner.commit_worker_message(base,state,'combined',ctx,message,'offline')
        self.assertEqual((base/'extracted.json').read_bytes(),saved)

    def test_invalid_combined_capture_does_not_commit_case(self):
        base,cases=self.fixture(1);state=self.state()
        with self.assertRaises(ValueError):
            runner.commit_worker_message(base,state,'bad',{'review_cases':cases},{
                'source_captures':[{'url':cases[0]['url'],'coverage':'invented','text':'Invalid capture'}],
                'case_result':self.result(cases[0])},'offline')
        self.assertFalse((base/'extracted.json').exists())

    def test_real_stream_path_uses_combined_envelopes_and_survives_quota(self):
        base,cases=self.fixture(3);self.cmd('resume','test-company')
        result=self.cmd('run','test-company','--codex',efficiency.FAKE,'--max-tasks','1',env={'FAKE_MODE':'envelope_interrupt'})
        self.assertEqual(len(runner.read_json(base/'extracted.json')),2,result.stdout+result.stderr)
        self.assertEqual(self.state()['phase'],'paused_quota')
        self.assertEqual(len(runner.coverage_plan(base,self.state())['cases']),1)
        self.assertEqual(len(list((base/'research/cases').rglob('*.json'))),2)

    def test_global_failure_guard_survives_model_memory_filtering(self):
        base,cases=self.fixture(1);url='https://unrelated.example.com/failure.pdf'
        research.remember(base,runner.atomic_json,provider='Other provider',capture={'url':url,'coverage':'failed','text':'One saved failed PDF access.'})
        self.cmd('resume','test-company');trace=Path(self.tmp.name)/'trace'
        self.cmd('run','test-company','--codex',efficiency.FAKE,'--max-tasks','1',env={'FAKE_MODE':'unrelated_failure','FAKE_TRACE':str(trace)})
        assignment=self.traced_assignments(trace)[0]
        self.assertNotIn(url,assignment['evidence_memory']['known_access_failures'])
        self.assertIn('reopened a recorded failed source',self.state()['pause_reason'])
        self.assertFalse((base/'extracted.json').exists())

    def test_combined_linked_document_belongs_to_its_assigned_provider(self):
        base,cases=self.fixture(2);state=self.state();case=dict(cases[1],provider='Second Provider')
        case['id']=runner.case_id(case['provider'],case['url'])
        pdf='https://documents.example.net/customer.pdf'
        ctx={'review_cases':[cases[0],case],'approved_provider':cases[0]['provider']}
        runner.commit_worker_message(base,state,'mixed',ctx,{
            'source_captures':[{'url':pdf,'coverage':'excerpt','text':'Faithful linked PDF evidence.'}],
            'case_result':self.result(case)},'offline')
        self.assertEqual(len(list(research.captures_for(base,'Second Provider',pdf))),1)
        self.assertEqual(list(research.captures_for(base,cases[0]['provider'],pdf)),[])

    def test_resolution_listing_memory_omits_redundant_order_and_navigation(self):
        listing='https://vendor.test/stories'
        proof={'url':listing,'role':'listing','coverage':'excerpt','text':'Faithful source excerpt stays unchanged.',
               'positions_verified':True,'ordered_entries':[
                   {'position':1,'title':'First','url':None},
                   {'position':2,'title':'Second','url':'https://vendor.test/second'},
                   {'position':3,'title':'Third','url':'https://vendor.test/third'}],
               'continuation':{'kind':'exhausted','target':'','evidence':'Actual listing end.'}}
        ctx={'url_recovery':True,'recovery_slots':[{'listing_url':listing,'listing_position':2,'title':'Second','customer':'Unknown'}],
             'evidence_memory':{'sources':{listing:proof},'known_access_failures':{}}}
        out=research.model_context(ctx)['evidence_memory']['sources'][listing]
        self.assertEqual(out['text'],proof['text'])
        self.assertEqual(out['ordered_entries'],[proof['ordered_entries'][1]])
        self.assertNotIn('continuation',out)
        self.assertEqual(len(proof['ordered_entries']),3)
