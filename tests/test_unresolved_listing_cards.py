import copy,json,unittest
from unittest.mock import patch
import runner,research,workspace
import test_listing_boundary as boundary


class UnresolvedListingCardTests(unittest.TestCase):
    setUp=boundary.ListingBoundaryTests.setUp
    tearDown=boundary.ListingBoundaryTests.tearDown
    cmd=boundary.ListingBoundaryTests.cmd
    state=boundary.ListingBoundaryTests.state
    fixture=boundary.ListingBoundaryTests.fixture
    setup_listing=boundary.ListingBoundaryTests.setup_listing
    record=boundary.ListingBoundaryTests.record
    result=boundary.ListingBoundaryTests.result
    page=boundary.ListingBoundaryTests.page
    apply=boundary.ListingBoundaryTests.apply

    def unresolved(self,base,s,n=6):
        obj=self.page(base,s,1,n,exhausted=True);rows=obj['cases']
        for r in rows:r.update(url=None,url_status='unresolved',decision='unresolved')
        proof={'url':rows[0]['listing_url'],'role':'listing','coverage':'excerpt','text':'Observed titles and positions; links are unresolved.',
            'positions_verified':True,'order_verified':True,'ordered_entries':[
                {'position':r['listing_position'],'title':r['title'],'url':None,'url_status':'unresolved'} for r in rows]}
        research.remember(base,runner.atomic_json,provider='Beta Software',origin='synthetic',capture=proof)
        return obj,proof

    def test_six_url_less_cards_close_universe_without_source_cases_or_replacements(self):
        base,s,_=self.setup_listing();obj,_=self.unresolved(base,s)
        before=runner.screening_path(base).read_bytes();self.apply(base,s,obj)
        universe=s['listing_universes']['Beta Software'];self.assertTrue(universe['complete']);self.assertEqual(len(universe['entries']),6)
        self.assertTrue(all(c['url'] is None and c['url_status']=='unresolved' for c in universe['entries']))
        self.assertEqual(runner.screening_path(base).read_bytes(),before)
        self.assertFalse((base/'extracted.json').exists())
        self.assertEqual(runner.coverage_plan(base,s)['action'],'resolve_urls')
        self.assertEqual(runner.coverage_plan(base,s)['coverage'][0]['unresolved_listing_urls'],6)
        self.assertEqual(s['phase'],'stage2')

    def test_guessed_url_and_unresolved_extraction_are_rejected(self):
        base,s,_=self.setup_listing();obj,_=self.unresolved(base,s,1)
        for changes in ({'url':'https://guessed.example.com/story'},{'record':{'status':'complete'}},{'decision':'needs_review'}):
            with self.subTest(changes=changes):
                row=dict(obj['cases'][0],**changes)
                with self.assertRaisesRegex(runner.RunError,'Unresolved listing URL'):
                    self.apply(base,s,dict(obj,cases=[row]))

    def test_unresolved_titles_must_match_observed_position(self):
        base,s,_=self.setup_listing();obj,_=self.unresolved(base,s,2)
        bad=copy.deepcopy(obj);bad['cases'][0]['title']='Invented title'
        with self.assertRaisesRegex(runner.RunError,'title/position mismatch'):self.apply(base,s,bad)
        bad=copy.deepcopy(obj);bad['cases'].reverse()
        self.apply(base,s,bad)
        self.assertEqual([r['listing_position'] for r in s['listing_universes']['Beta Software']['entries']],[1,2])

    def test_duplicate_card_does_not_consume_another_slot(self):
        base,s,_=self.setup_listing();obj,proof=self.unresolved(base,s,1);row=obj['cases'][0]
        ctx={'approved_provider':'Beta Software','max_cases':30,'listing_only':True,'_listing_proofs':{row['listing_url']:proof},'competing_product':runner.provider_scope(base,s,'Beta Software')}
        runner.commit_listing_candidate(base,s,'new',ctx,row);runner.commit_listing_candidate(base,s,'new',ctx,row)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),1)
        repeated=dict(row,listing_position=2)
        proof['ordered_entries'].append({'position':2,'title':row['title'],'url':None,'url_status':'unresolved'})
        # Two witnessed positions may share a heading; do not guess that they
        # are duplicates when their destinations are unresolved.
        runner.commit_listing_candidate(base,s,'new',ctx,repeated)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),2)
        self.assertNotEqual(s['listing_universes']['Beta Software']['entries'][0]['id'],s['listing_universes']['Beta Software']['entries'][1]['id'])

    def test_distinct_witnessed_positions_can_share_a_source_url(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2,exhausted=True)
        obj['cases'][1]['url']=obj['cases'][0]['url']
        research.remember(base,runner.atomic_json,provider='Beta Software',origin='synthetic',capture={
            'url':obj['cases'][0]['listing_url'],'role':'listing','coverage':'excerpt','text':'Duplicate source card.',
            'order_verified':True,'ordered_entries':[{'position':r['listing_position'],'url':r['url']} for r in obj['cases']]})
        self.apply(base,s,obj)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),2)
        self.assertEqual(len(runner.coverage_plan(base,s)['cases']),1)

    def test_compact_unresolved_card_reference_never_creates_case_receipt(self):
        base,s,_=self.setup_listing();obj,proof=self.unresolved(base,s,1);row=obj['cases'][0]
        ctx={'approved_provider':'Beta Software','task':'discover','first_listing_entries':30,'compact_receipts':True,'max_cases':30,
             '_listing_proofs':{row['listing_url']:proof},'competing_product':runner.provider_scope(base,s,'Beta Software')}
        runner.commit_worker_message(base,s,'new',ctx,{'discovered_case':row},'synthetic')
        materialized=runner.expand_worker_receipts(base,s,'new',ctx,{'cases':[],'completed_ids':['listing:1']})
        self.assertEqual(materialized['cases'],[row]);self.assertFalse(list((base/'research/cases').rglob('*.json')))

    def saved_combined_failure(self,base,s):
        obj=self.page(base,s,1,6,exhausted=True);obj['order_verified']=False
        text='Listing card order: '+'; '.join(f'({r["listing_position"]}) {r["title"]}' for r in obj['cases'])+'. Each card occurs twice; duplicates count once. Six distinct cards are followed by a CTA and footer; no pagination is exposed. Destinations are unverified.'
        research.remember(base,runner.atomic_json,provider='Beta Software',origin='old-capture',capture={
            'url':obj['cases'][0]['listing_url'],'role':'listing','coverage':'excerpt','text':text,
            'ordered_entries':[{'position':r['listing_position'],'url':r['url']} for r in obj['cases']]})
        key='listing30_beta-software_'+workspace.digest(runner.provider_scope(base,s,'Beta Software'))[:12]+'_page_001'
        runner.atomic_json(base/'results'/f'{key}.json',obj);s['jobs'][key]={'status':'paused','error_kind':'validation','response_ready':True,'attempts':1}
        runner.save(base,s)
        return key,obj

    def test_saved_six_card_failure_recovers_without_model_and_is_idempotent(self):
        base,s,_=self.setup_listing();key,obj=self.saved_combined_failure(base,s)
        result=(base/'results'/f'{key}.json').read_bytes();ledger=runner.screening_path(base).read_bytes()
        with patch.object(runner,'codex_call',side_effect=AssertionError('No repeat listing call')),patch.object(workspace,'ensure_sync',return_value=True):
            runner.discovery_step(base,s,60,'FORBIDDEN')
            self.assertEqual(runner.listing_discovery_plan(base,s)['action'],'resolve_urls')
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),6)
        self.assertTrue(s['listing_universes']['Beta Software']['complete'])
        self.assertEqual((base/'results'/f'{key}.json').read_bytes(),result)
        self.assertEqual(runner.screening_path(base).read_bytes(),ledger)
        self.assertEqual(s['jobs'][key]['attempts'],1)

    def test_incomplete_exhaustion_evidence_is_rejected(self):
        base,s,_=self.setup_listing();key,obj=self.saved_combined_failure(base,s)
        with self.assertRaisesRegex(runner.RunError,'exhausted ordered'):
            runner.recover_saved_listing_cards(base,key,'Beta Software',{},dict(obj,listing_exhausted=False))
        bad=copy.deepcopy(obj);bad['cases'][1]['title']='Not in saved capture'
        with self.assertRaisesRegex(runner.RunError,'confirm card order'):
            runner.recover_saved_listing_cards(base,key,'Beta Software',{},bad)

    def test_interrupted_card_recovery_reuses_saved_prefix_without_duplicates(self):
        base,s,_=self.setup_listing();key,_=self.saved_combined_failure(base,s);write=runner.atomic_json
        def crash(path,value):
            if path.name=='state.json' and len(value.get('listing_universes',{}).get('Beta Software',{}).get('entries',[]))==3:
                raise OSError('Synthetic interruption')
            return write(path,value)
        with patch.object(runner,'atomic_json',side_effect=crash),patch.object(runner,'codex_call',side_effect=AssertionError('No model')),patch.object(workspace,'ensure_sync',return_value=True):
            with self.assertRaises(OSError):runner.discovery_step(base,s,60,'FORBIDDEN')
        s=runner.read_state(base)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),2)
        with patch.object(runner,'codex_call',side_effect=AssertionError('No model')),patch.object(workspace,'ensure_sync',return_value=True):runner.discovery_step(base,s,60,'FORBIDDEN')
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),6)
        self.assertEqual(len({r['id'] for r in s['listing_universes']['Beta Software']['entries']}),6)

    def test_completed_cases_and_sheet_identity_are_preserved_without_tentative_matches(self):
        base,s,cases=self.setup_listing(35)
        for c in cases:runner.commit_case_result(base,s,'old',cases,self.result(c))
        s['workspace_sheet']={'id':'preserved-sheet'};s['workspace_verified_ids']=[c['id'] for c in cases]
        before={p:p.read_bytes() for p in (base/'research/cases').rglob('*.json')}
        before.update({p:p.read_bytes() for p in (base/'extracted.json',runner.screening_path(base),runner.inventory_path(base))})
        key,_=self.saved_combined_failure(base,s);original_ids=list(s['workspace_verified_ids'])
        with patch.object(runner,'codex_call',side_effect=AssertionError('No research')),patch.object(workspace,'ensure_sync',return_value=True):runner.discovery_step(base,s,60,'FORBIDDEN')
        self.assertTrue(all(p.read_bytes()==content for p,content in before.items()))
        active=research.eligible_inventory(s,runner.read_json(runner.inventory_path(base)),runner.read_json(base/'extracted.json'))
        self.assertEqual(len(active['Beta Software']),35)
        self.assertEqual(s['workspace_verified_ids'],original_ids);self.assertEqual(s['workspace_sheet']['id'],'preserved-sheet')
        self.assertTrue(all(c['id'] not in original_ids for c in s['listing_universes']['Beta Software']['entries']))


if __name__=='__main__':unittest.main()
