import argparse
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import document_tabs as tabs
import runner
import synthesis_publication as native
import workspace as ws


class DocumentTabTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.sections=['# '+name+'\n\n'+('Executive summary: 17 profiles; roles overlap; authority unconfirmed.\n' if i==0 else
            'Detailed caveat: 17 profiles; Ω and 🐙 remain verbatim.\n\n| Group | Profiles |\n|---|---|\n| Synthetic | 17 |\n') for i,name in enumerate(ws.REPORT_SECTIONS)]
        self.markdown='\n'.join(self.sections)
        report={'markdown':self.markdown,'database_sha256':'frozen'};report['sha256']=ws.digest(report)
        runner.atomic_json(self.base/'report.json',report);runner.atomic_text(self.base/'report.md',self.markdown)
        self.state={'phase':'complete','company':'Synthetic','id':'synthetic','finalized_sheet_sha256':'frozen',
                    'workspace_document':{'id':'doc','url':'https://example.invalid/doc'},'document_verified':True}
        self.original=self.tab(self.markdown,'Tab 1','t.0')

    def tab(self,markdown,title,tid,scaffold=False):
        value,headings,table_specs=native.parse_markdown(markdown);by_marker={t['marker']:t for t in table_specs}
        pending_headings=list(headings);content=[];index=1
        for line in value.splitlines():
            if line in by_marker:
                rows=[];start=index;index+=2
                for row in by_marker[line]['rows']:
                    cells=[]
                    for cell in row:
                        text='' if scaffold else cell
                        cells.append({'content':[{'startIndex':index,'endIndex':index+native.u16(text+'\n'),
                            'paragraph':{'elements':[{'textRun':{'content':text+'\n'}}]}}]})
                        index+=native.u16(text+'\n')+2
                    rows.append({'tableCells':cells})
                content.append({'startIndex':start,'endIndex':index,'table':{'tableRows':rows}})
            else:
                level=0
                if pending_headings and line==pending_headings[0]['text']:
                    level=pending_headings.pop(0)['level']
                style={'namedStyleType':'TITLE' if line.endswith(' | Working ICP') else 'HEADING_'+str(level) if level else 'NORMAL_TEXT','pageBreakBefore':level==1 and line!='Overview'}
                end=index+native.u16(line+'\n');content.append({'startIndex':index,'endIndex':end,'paragraph':{
                    'paragraphStyle':style,'elements':[{'textRun':{'content':line+'\n'}}]}});index=end
        content.append({'startIndex':index,'endIndex':index+1,'paragraph':{'elements':[{'textRun':{'content':'\n'}}]}})
        return {'tabId':tid,'title':title,'body':{'content':content}}

    def data(self,details=None,overview=False):
        root=self.tab(self.sections[0],'Overview','t.0') if overview else copy.deepcopy(self.original)
        return {'documentId':'doc','revisionId':'revision','tabs':[root]+(details or [])}

    def detail_tabs(self,scaffold=False):
        return [self.tab(section,name,'t.'+str(i),scaffold) for i,(name,section) in enumerate(zip(tabs.TITLES[1:],self.sections[1:]),1)]

    def test_create_tabs_only_and_repeated_pending_plan_is_idempotent(self):
        before=(self.base/'report.json').read_bytes()
        tabs.start(self.base,self.state,runner.atomic_json,self.data())
        p=copy.deepcopy(self.state['workspace_pending'])
        self.assertEqual(p['kind'],'doc_tabs_add')
        self.assertEqual([r['addDocumentTab']['tabProperties']['title'] for r in p['arguments']['requests']],tabs.TITLES[1:])
        tabs.start(self.base,self.state,runner.atomic_json,self.data())
        self.assertEqual(self.state['workspace_pending'],p)
        self.assertEqual((self.base/'report.json').read_bytes(),before)

    def test_empty_detail_tabs_are_written_without_touching_original(self):
        empty=[self.tab('',name,'t.'+str(i)) for i,name in enumerate(tabs.TITLES[1:],1)]
        data=self.data(empty);original=copy.deepcopy(data)
        tabs.organize(self.base,self.state,data,runner.atomic_json)
        p=self.state['workspace_pending'];self.assertEqual(p['kind'],'doc_tabs_write')
        requests=p['arguments']['requests'];self.assertTrue(any('insertTable'in r for r in requests))
        self.assertTrue(all(r['deleteContentRange']['range']['startIndex']>1 for r in requests if 'deleteContentRange'in r))
        self.assertNotIn('"tabId": "t.0"',json.dumps(requests))
        self.assertEqual(data,original)

    def test_uncertain_scaffold_write_recovers_by_filling_tables_only(self):
        data=self.data(self.detail_tabs(scaffold=True))
        tabs.organize(self.base,self.state,data,runner.atomic_json)
        p=self.state['workspace_pending'];self.assertEqual(p['kind'],'doc_tabs_fill')
        req=p['arguments']['requests']
        self.assertFalse(any('insertTable'in r or 'addDocumentTab'in r for r in req))
        self.assertNotIn('"tabId": "t.0"',json.dumps(req))
        self.assertTrue(any(r.get('insertText',{}).get('text')=='17' for r in req))

    def test_original_is_trimmed_only_after_verbatim_details_and_tables_verify(self):
        data=self.data(self.detail_tabs());tabs.organize(self.base,self.state,data,runner.atomic_json)
        p=self.state['workspace_pending'];self.assertEqual(p['kind'],'doc_tabs_finish')
        deletes=[r['deleteContentRange']['range'] for r in p['arguments']['requests'] if 'deleteContentRange'in r]
        self.assertEqual(len(deletes),1);self.assertEqual(deletes[0]['tabId'],'t.0')
        self.assertGreater(deletes[0]['startIndex'],native.u16(self.sections[0])-20)
        self.assertEqual(p['arguments']['write_control'],{'requiredRevisionId':'revision'})

    def test_overview_repeated_heading_at_10_does_not_replace_detailed_boundary_at_85(self):
        self.sections[0]='# Overview\n\n## Company profiles\n\n'+'x'*57+'\n'
        self.markdown='\n'.join(self.sections)
        report={'markdown':self.markdown,'database_sha256':'frozen'};report['sha256']=ws.digest(report)
        runner.atomic_json(self.base/'report.json',report)
        runner.atomic_text(self.base/'report.md',self.markdown)
        self.original=self.tab(self.markdown,'Tab 1','t.0')
        repeated=[e for e in self.original['body']['content'] if 'paragraph'in e and tabs.text(e['paragraph']).strip()=='Company profiles']
        self.assertEqual([e['startIndex'] for e in repeated],[10,85])
        data=self.data(self.detail_tabs());tabs.organize(self.base,self.state,data,runner.atomic_json)
        p=self.state.pop('workspace_pending')
        deletion=next(r['deleteContentRange']['range'] for r in p['arguments']['requests'] if 'deleteContentRange'in r)
        self.assertEqual(deletion['startIndex'],85)
        # Apply the planned trim to the synthetic native document, not just
        # a separately constructed happy-path Overview.
        data['tabs'][0]['body']['content']=[e for e in data['tabs'][0]['body']['content'] if e['startIndex']<85]
        data['tabs'][0]['title']='Overview'
        self.assertTrue(tabs.organize(self.base,self.state,data,runner.atomic_json))
        self.assertTrue(all(tabs.matches(t,s) for t,s in zip(data['tabs'],self.sections)))
        self.assertEqual(tabs.compact(''.join(tabs.text(tabs.body(t)) for t in data['tabs'])),tabs.compact(tabs.text(tabs.body(self.original))))

    def test_missing_or_wrong_top_level_boundary_blocks_trimming(self):
        data=self.data(self.detail_tabs())
        heading=next(e for e in data['tabs'][0]['body']['content'] if 'paragraph'in e and tabs.text(e['paragraph']).strip()=='Company profiles')
        heading['paragraph']['paragraphStyle']['namedStyleType']='HEADING_2'
        with self.assertRaisesRegex(ws.WorkspaceError,'top-level report section boundaries'):
            tabs.organize(self.base,self.state,data,runner.atomic_json)
        self.assertNotIn('workspace_pending',self.state)

    def test_completed_five_tabs_preserve_all_text_counts_and_are_idempotent(self):
        data=self.data(self.detail_tabs(),overview=True)
        self.assertTrue(tabs.organize(self.base,self.state,data,runner.atomic_json))
        self.assertEqual(self.state['phase'],'complete');self.assertEqual(self.state['native_doc_tabs']['titles'],tabs.TITLES)
        self.assertNotIn('workspace_pending',self.state)
        before=copy.deepcopy(self.state);tabs.organize(self.base,self.state,data,runner.atomic_json)
        self.assertEqual(self.state,before)
        self.assertEqual(tabs.compact(''.join(tabs.text(tabs.body(t)) for t in data['tabs'])),tabs.compact(tabs.text(tabs.body(self.original))))

    def test_changed_source_or_partial_detail_is_rejected_without_trimming(self):
        data=self.data(self.detail_tabs());data['tabs'][2]['body']['content'][1]['paragraph']['elements'][0]['textRun']['content']='Changed caveat\n'
        with self.assertRaises(ws.WorkspaceError):tabs.organize(self.base,self.state,data,runner.atomic_json)
        self.assertNotIn('workspace_pending',self.state)
        wrong=self.data();wrong['documentId']='another-doc'
        with self.assertRaises(ws.WorkspaceError):tabs.organize(self.base,self.state,wrong,runner.atomic_json)

    def test_future_runs_default_to_native_doc_tabs_and_single_case_sheet(self):
        with patch.object(runner,'RUNS',self.base):
            runner.create_run(argparse.Namespace(id='future',company='Future',website='https://example.invalid'))
            state=runner.read_state(self.base/'future')
        self.assertEqual(state['workspace_policy']['native_doc_tabs'],1)
        self.assertEqual(state['workspace_policy']['sync_batch_size'],100)
        ws.ensure_sync(self.base,state,[],runner.atomic_json)
        self.assertEqual(state['workspace_pending']['kind'],'sheet_create')
        self.assertEqual(state['workspace_pending']['arguments']['source_file'],str(ws.SEED))

    def test_normal_native_report_verification_automatically_queues_tab_organization(self):
        _,expected=ws.render_report(self.markdown);runner.atomic_json(self.base/'report_expected.json',expected)
        self.state.update(workspace_policy={'native_doc_tabs':1},document_layout_done=True)
        data=self.data()
        ws.apply_response(self.base,self.state,{'kind':'doc_verify','details':{}},data,runner.atomic_json)
        self.assertEqual(self.state['phase'],'organize_doc')
        self.assertEqual(self.state['workspace_pending']['kind'],'doc_tabs_add')


if __name__=='__main__':unittest.main()
