"""Offline regressions for the Example Provider/Fibr failures; never touches real runs."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import runner,research,workspace as ws,document_tabs as tabs,synthesis_publication as native
import test_listing_boundary as fixtures
import test_unresolved_listing_cards as unresolved
import test_document_tabs as docfixtures


class ListingHardeningTests(unittest.TestCase):
    setUp=fixtures.ListingBoundaryTests.setUp
    tearDown=fixtures.ListingBoundaryTests.tearDown
    cmd=fixtures.ListingBoundaryTests.cmd
    state=fixtures.ListingBoundaryTests.state
    fixture=fixtures.ListingBoundaryTests.fixture
    setup_listing=fixtures.ListingBoundaryTests.setup_listing
    page=fixtures.ListingBoundaryTests.page
    apply=fixtures.ListingBoundaryTests.apply
    record=fixtures.ListingBoundaryTests.record
    result=fixtures.ListingBoundaryTests.result
    unresolved=unresolved.UnresolvedListingCardTests.unresolved

    def ctx(self,base,s,proof):
        return dict(approved_provider='Beta Software',max_cases=30,listing_contract_v2=True,
                    competing_product=runner.provider_scope(base,s,'Beta Software'),
                    _listing_proofs={u:proof for u in research.capture_urls(proof)})

    def test_wingify_recorded_redirect_and_resume_from_saved_capture(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2)
        original='https://legacy.example/success-stories';resolved='https://provider.example/success-stories/'
        for r in obj['cases']:r['listing_url']=resolved
        proof=dict(url=original,resolved_url=resolved,resolved_url_evidence='Requested Example Provider success stories; response URL was Example Provider success stories.',
                   role='listing',coverage='excerpt',text='Observed success stories.',order_verified=True,
                   ordered_entries=[dict(position=r['listing_position'],url=r['url']) for r in obj['cases']])
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof)
        # No current-call proof: the durable alias index must work after interruption.
        ctx=self.ctx(base,s,proof);ctx['_listing_proofs']={}
        for r in obj['cases']:runner.commit_listing_candidate(base,s,'x',ctx,r)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),2)
        self.assertEqual(s['listing_universes']['Beta Software']['entries'][0]['listing_provenance']['url'],original)
        for r in obj['cases']:runner.commit_listing_candidate(base,s,'x',ctx,r)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),2)

    def test_actual_saved_wingify_redirect_sentence_and_card_order(self):
        base,s,_=self.setup_listing()
        saved=json.loads((Path(__file__).parent/'fixtures/wingify_listing_captures.json').read_text())
        proof=next(x['capture'] for x in saved if x['capture']['text'].startswith('Redirected to '))
        self.assertEqual(proof['url'],'https://legacy.example/success-stories')
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof)
        # Simulate the old requested-URL-only memory index. No fresh model or
        # rewrite is needed to recover the explicit historical observation.
        memory=runner.read_json(base/'research/memory.json')
        memory['sources'].pop('https://provider.example/success-stories',None)
        runner.atomic_json(base/'research/memory.json',memory)
        ctx=self.ctx(base,s,proof);ctx['_listing_proofs']={}
        for card in proof['ordered_entries']:
            row=dict(title=card['title'],customer='Unknown',url=None,url_status='unresolved',
                     listing_position=card['position'],listing_url='https://provider.example/success-stories/',
                     decision='unresolved',reason='Observed card; no href.',evidence=proof['text'],reading_depth='lightweight',record=None)
            runner.commit_listing_candidate(base,s,'real-witness',ctx,row)
        entries=s['listing_universes']['Beta Software']['entries']
        self.assertEqual([c['title'] for c in entries],[c['title'] for c in proof['ordered_entries']])
        self.assertEqual(len(entries),12)
        self.assertEqual(entries[0]['listing_provenance']['resolved_url'],'https://provider.example/success-stories/')

    def test_looping_cursor_closes_incomplete_without_retry(self):
        base,s,_=self.setup_listing()
        for start,target in ((1,'next-A'),(3,'next-B'),(5,'next-A')):
            obj=self.page(base,s,start,2);obj['next_cursor']=target
            self.navigation(base,s,obj,'load_more',target);self.apply(base,s,obj)
        u=s['listing_universes']['Beta Software']
        self.assertTrue(u['complete']);self.assertEqual(u['coverage_status'],'incomplete')
        self.assertIn('loops',u['continuation_limitation'])

    def test_streamed_unresolved_upgrade_has_one_final_receipt(self):
        base,s,_=self.setup_listing();row,proof,ctx,capture=self.association(base,s)
        ctx.update(task='discover',first_listing_entries=30,compact_receipts=True)
        runner.commit_worker_message(base,s,'x',ctx,{'discovered_case':row},'offline')
        upgraded=dict(row,url=capture['url'],url_status='content_confirmed',decision='relevant')
        runner.commit_worker_message(base,s,'x',ctx,{'discovered_case':upgraded},'offline')
        result=runner.expand_worker_receipts(base,s,'x',ctx,{'cases':[],'completed_ids':['listing:1']})
        self.assertEqual(result['cases'],[upgraded]);self.assertEqual(len(ctx['_checkpoint_rows']),1)
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),1)

    def test_redirect_without_witness_is_not_an_alias(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,1)
        proof=dict(url='https://legacy.example/success-stories',resolved_url='https://provider.example/success-stories',
                   role='listing',coverage='excerpt',text='Similar names.',order_verified=True,ordered_entries=[dict(position=1,url=obj['cases'][0]['url'])])
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof)
        row=dict(obj['cases'][0],listing_url=proof['resolved_url'])
        with self.assertRaisesRegex(runner.RunError,'verify natural listing'):runner.commit_listing_candidate(base,s,'x',self.ctx(base,s,proof),row)

    def test_explicit_canonical_and_fragment_slash_equivalence(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,1)
        proof=dict(url='https://example.com/stories?source=nav',canonical_url=obj['cases'][0]['listing_url']+'/#cards',
                   canonical_url_evidence='Observed rel=canonical link.',role='listing',coverage='excerpt',text='Listing.',
                   order_verified=True,ordered_entries=[dict(position=1,url=obj['cases'][0]['url'])])
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof)
        runner.commit_listing_candidate(base,s,'x',self.ctx(base,s,proof),obj['cases'][0])
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),1)

    def association(self,base,s):
        obj,proof=self.unresolved(base,s,1);row=obj['cases'][0]
        ctx=self.ctx(base,s,proof)
        runner.commit_listing_candidate(base,s,'x',ctx,row)
        url='https://stories.example.com/confirmed'
        quote='Customer 1 describes the in-scope product in Story 1.'
        capture=dict(url=url,coverage='excerpt',text=quote,listing_association=dict(
            listing_url=row['listing_url'],position=1,title=row['title'],quote=quote))
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=capture)
        return row,proof,ctx,capture

    def test_content_association_upgrades_slot_without_fabricating_href(self):
        base,s,_=self.setup_listing();row,proof,ctx,capture=self.association(base,s)
        row=dict(row,url=capture['url'],url_status='content_confirmed',decision='relevant')
        runner.commit_listing_candidate(base,s,'x',ctx,row)
        runner.commit_listing_candidate(base,s,'x',ctx,row)
        entries=s['listing_universes']['Beta Software']['entries'];self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['url_status'],'content_confirmed');self.assertIsNone(entries[0]['listing_href'])
        self.assertIsNone(proof['ordered_entries'][0]['url'])
        self.assertEqual(runner.read_json(runner.screening_path(base))[entries[0]['source_case_id']]['decision'],'relevant')

    def test_ambiguous_or_metadata_only_association_rejected(self):
        for change in ('metadata','quote','customer','listing'):
            with self.subTest(change=change):
                base,s,_=self.setup_listing();obj,proof=self.unresolved(base,s,1);row=obj['cases'][0]
                capture=dict(url='https://stories.example.com/confirmed',coverage='excerpt',text='Customer 1 uses the product.',
                             listing_association=dict(listing_url=row['listing_url'],position=1,title=row['title'],quote='Customer 1 uses the product.'))
                if change=='metadata':capture['coverage']='metadata'
                if change=='quote':capture['listing_association']['quote']='Invented quote'
                if change=='customer':capture['text']=capture['listing_association']['quote']='A different customer uses the product.'
                if change=='listing':capture['listing_association']['listing_url']='https://unrelated.example.com/'
                research.remember(base,runner.atomic_json,provider='Beta Software',capture=capture)
                with self.assertRaisesRegex(runner.RunError,'source-supported'):
                    runner.commit_listing_candidate(base,s,'x',self.ctx(base,s,proof),dict(row,url=capture['url'],url_status='content_confirmed',decision='relevant'))
                self.tearDown();self.setUp()

    def navigation(self,base,s,obj,kind,target='',evidence='Observed next link.'):
        row=obj['cases'][0] if obj['cases'] else s['listing_universes']['Beta Software']['entries'][-1]
        proof=dict(url=row['listing_url'],role='listing',coverage='excerpt',text='Observed listing.',order_verified=True,
                   ordered_entries=[dict(position=r['listing_position'],url=r['url']) for r in obj['cases']],
                   continuation=dict(kind=kind,target=target,evidence=evidence))
        research.remember(base,runner.atomic_json,provider='Beta Software',capture=proof)
        s['research_policy']['listing_navigation_version']=2

    def test_real_pagination_and_load_more_then_inaccessible_continuation(self):
        base,s,_=self.setup_listing()
        for start,kind,cursor in ((1,'link','https://stories.example.com/customer-stories?next=real'),
                                  (3,'load_more','Load More button after card 4'),(5,'blocked','Load More failed')):
            obj=self.page(base,s,start,2);obj['next_cursor']=cursor
            if kind=='blocked':obj['has_more']=False
            self.navigation(base,s,obj,kind,cursor,'Actual control/access observation.')
            self.apply(base,s,obj)
        u=s['listing_universes']['Beta Software'];self.assertEqual(len(u['entries']),6)
        self.assertTrue(u['complete']);self.assertEqual(u['coverage_status'],'incomplete')
        self.assertEqual(runner.coverage_plan(base,s)['coverage'][0]['listing_coverage_status'],'incomplete')
        self.assertEqual(runner.listing_discovery_plan(base,s)['action'],'review_batch')
        self.assertEqual(runner.coverage_plan(base,s)['action'],'review_batch')

    def test_unwitnessed_invented_next_page_rejected(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2);s['research_policy']['listing_navigation_version']=2
        obj['next_cursor']='https://stories.example.com/customer-stories/page/2'
        with self.assertRaisesRegex(runner.RunError,'navigation evidence'):self.apply(base,s,obj)

    def test_duplicate_titles_with_distinct_sources_preserved(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2,exhausted=True)
        obj['cases'][1]['title']=obj['cases'][0]['title'];self.apply(base,s,obj)
        entries=s['listing_universes']['Beta Software']['entries'];self.assertEqual(len(entries),2)
        self.assertNotEqual(entries[0]['id'],entries[1]['id'])

    def test_next_page_shared_source_urls_preserve_distinct_slots(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2);self.apply(base,s,obj)
        repeated=self.page(base,s,3,2)
        for r,old in zip(repeated['cases'],obj['cases']):r['url']=old['url']
        self.navigation(base,s,repeated,'link','third-page')
        repeated['next_cursor']='third-page';self.apply(base,s,repeated)
        u=s['listing_universes']['Beta Software'];self.assertEqual(len(u['entries']),4)
        self.assertFalse(u['complete'])

    def test_duplicate_card_skipped_without_replacement_or_gap(self):
        base,s,_=self.setup_listing();obj=self.page(base,s,1,2)
        proof=dict(url=obj['cases'][0]['listing_url'],order_verified=True,ordered_entries=[
            dict(position=1,url=obj['cases'][0]['url'],card_id='card-one'),dict(position=2,url=obj['cases'][0]['url'],card_id='card-one'),dict(position=3,url=obj['cases'][1]['url'],card_id='card-two')])
        ctx=self.ctx(base,s,proof)
        runner.commit_listing_candidate(base,s,'x',ctx,obj['cases'][0])
        runner.commit_listing_candidate(base,s,'x',ctx,dict(obj['cases'][0],listing_position=2))
        self.assertEqual(len(s['listing_universes']['Beta Software']['entries']),1)


class PresentationHardeningTests(unittest.TestCase):
    setUp=docfixtures.DocumentTabTests.setUp
    tab=docfixtures.DocumentTabTests.tab
    data=docfixtures.DocumentTabTests.data
    detail_tabs=docfixtures.DocumentTabTests.detail_tabs

    def test_clean_doc_title_has_no_run_identifier(self):
        self.assertEqual(ws.title(self.state,'Case-study research'),'Synthetic | Working ICP')

    def test_html_import_uses_native_lists_and_in_place_requests_use_bullets(self):
        md='# Overview\n## People involved\n- Founder: 1 (25%)\n- CTO: 1 (25%)\n'
        html,expected=ws.render_report(md)
        self.assertIn('<ul><li>Founder: 1 (25%)</li><li>CTO: 1 (25%)</li></ul>',html)
        self.assertEqual(expected['bullets'],2)
        data={'documentId':'doc','revisionId':'rev','tabs':[self.tab('','#','root')]}
        args,_=native.document_replace_plan(data,md,section=True)
        bullet_requests=[r['createParagraphBullets'] for r in args['requests'] if 'createParagraphBullets' in r]
        self.assertEqual(len(bullet_requests),2)
        text=native.parse_markdown(md)[0]
        for r in bullet_requests:
            start=r['range']['startIndex']-1;end=r['range']['endIndex']-1
            self.assertIn(text[start:end],('Founder: 1 (25%)','CTO: 1 (25%)'))
        tab=self.tab(md,'Overview','root')
        self.assertFalse(tabs.matches(tab,md))
        for e in tab['body']['content']:
            if tabs.text(e).strip().startswith(('Founder:','CTO:')):e['paragraph']['bullet']={'listId':'native-list'}
        self.assertTrue(tabs.matches(tab,md))

    def test_overview_title_is_changed_only_after_detail_verification(self):
        self.state['workspace_policy']={'overview_presentation':1}
        data=self.data(self.detail_tabs());tabs.organize(self.base,self.state,data,runner.atomic_json)
        req=self.state.pop('workspace_pending')['arguments']['requests']
        insertion=next(r['insertText'] for r in req if 'insertText' in r)
        self.assertEqual(insertion['text'],'Synthetic | Working ICP')
        displayed=tabs.display_sections(self.state,self.sections)
        data['tabs'][0]=self.tab(displayed[0],'Overview','t.0')
        data['tabs'][0]['body']['content'][0]['paragraph']['paragraphStyle']['namedStyleType']='TITLE'
        self.assertTrue(tabs.organize(self.base,self.state,data,runner.atomic_json))
        self.assertEqual(self.state['phase'],'complete')

    def test_bulleted_frequencies_retain_strict_denominator_validation(self):
        import test_fresh_report_readiness as fresh
        import report_quality
        md,db,agg,roles=fresh.fixture()
        md=md.replace('Software: 3 (75%).','- Software: 3 (75%)')
        report_quality.validate(md,db,agg,roles,require_overview=True)
        with self.assertRaisesRegex(ws.WorkspaceError,'Overview'):
            report_quality.validate(md.replace('- Software: 3 (75%)','- Software: 2 (50%)'),db,agg,roles,require_overview=True)
        db['screening_summary']={'providers':[{'listing_coverage_status':'incomplete','continuation_limitation':'Load More inaccessible'}]}
        import semantic_synthesis
        self.assertEqual(semantic_synthesis.report_context(db,agg)['collection_coverage'],db['screening_summary'])

    def test_utf16_bullets_after_tables_and_emoji(self):
        md='# Ω 🐙\n| A | B |\n|---|---|\n| x | y |\n\n- Ω 🐙: 1 (25%)\n'
        text=native.parse_markdown(md)[0];a,b=native.bullet_ranges(md)[0]
        self.assertEqual(text.encode('utf-16-le')[(a-1)*2:(b-1)*2].decode('utf-16-le'),'Ω 🐙: 1 (25%)')

if __name__=='__main__':unittest.main()
