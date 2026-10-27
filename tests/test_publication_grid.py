import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import runner
import workspace


class PublicationGridTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name)
        self.state={'id':'synthetic','company':'Synthetic','phase':'stage2','created_at':'synthetic',
                    'workspace_policy':{'complete_only':True,'sync_batch_size':100},
                    'workspace_sheet':{'id':'synthetic-sheet','url':'https://example.invalid/synthetic-sheet'}}

    def grid(self,rows,start=0):
        return {'spreadsheetId':'synthetic-sheet','sheets':[{'properties':{'sheetId':7},'data':[
            {'startRow':start,'rowData':[{'values':[{'userEnteredValue':{'stringValue':v}} if v else {} for v in row]} for row in rows]}]}]}

    def metadata(self,width=26):
        return {'spreadsheetId':'synthetic-sheet','sheets':[{'properties':{'sheetId':7,'title':'Case studies',
            'gridProperties':{'rowCount':1000,'columnCount':width}}}]}

    def initialize(self):
        workspace.apply_response(self.base,self.state,{'kind':'sheet_metadata','details':{}},self.metadata(),runner.atomic_json)
        workspace.ensure_sync(self.base,self.state,[],runner.atomic_json)
        pending=self.state['workspace_pending']
        self.assertEqual(pending['arguments']['ranges'],["'Case studies'!A1:Z1"])
        workspace.apply_response(self.base,self.state,pending,self.grid([workspace.HEADERS+['']*21]),runner.atomic_json)

    def records(self,n):
        return [{'id':str(i),'provider':'Synthetic','source_url':f'https://example.invalid/case/{i}',
                 'customer':f'Customer {i}','people':'Unspecified','company_profile':'Source profile',
                 'buying_situation':'Source buying evidence','status':'complete','note':'Internal audit note',
                 'private_capture':{'evidence':'Retain this internally'},'internal_score':i} for i in range(n)]

    def test_26_column_empty_grid_with_five_headers_initializes(self):
        self.initialize()
        self.assertTrue(self.state['workspace_header_verified'])
        self.assertEqual(self.state['workspace_sheet']['column_count'],26)
        self.assertEqual(workspace.grid_values(self.grid([workspace.HEADERS]),1),[workspace.HEADERS])

    def test_internal_extra_fields_never_enter_csv_or_publication_projection(self):
        records=self.records(2);before=copy.deepcopy(records)
        runner.atomic_json(self.base/'extracted.json',{r['id']:r for r in records})
        saved=(self.base/'extracted.json').read_bytes()
        runner.write_csv(self.base,records)
        with (self.base/'case_studies.csv').open() as f:rows=list(csv.reader(f))
        self.assertEqual(rows,[workspace.HEADERS]+workspace.rows_for(records))
        self.assertTrue(all(len(r)==5 for r in rows))
        self.assertEqual(rows[1],[records[0]['provider']+'\n'+records[0]['source_url'],
            records[0]['customer'],records[0]['people'],records[0]['company_profile'],records[0]['buying_situation']])
        self.assertEqual(records,before)
        self.assertEqual((self.base/'extracted.json').read_bytes(),saved)

    def test_populated_extra_header_and_late_extra_data_are_rejected(self):
        for rows in ([workspace.HEADERS+['Unexpected field']], [['']*26,['']*25+['Late research data']]):
            with self.subTest(rows=rows),self.assertRaisesRegex(workspace.WorkspaceError,'beyond column E'):
                workspace.grid_values(self.grid(rows),len(rows))
        for value in ({'numberValue':0},{'boolValue':False},{'formulaValue':'=""'}):
            data=self.grid([['']*6]);data['sheets'][0]['data'][0]['rowData'][0]['values'][5]={'userEnteredValue':value}
            with self.subTest(value=value),self.assertRaises(workspace.WorkspaceError):workspace.grid_values(data,1)

    def test_metadata_still_rejects_insufficient_grid_capacity(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.apply_response(self.base,self.state,{'kind':'sheet_metadata','details':{}},self.metadata(4),runner.atomic_json)

    def test_100_row_batches_reuse_exact_rows_and_finalize_full_physical_grid(self):
        self.initialize();records=self.records(101)
        workspace.ensure_sync(self.base,self.state,records,runner.atomic_json,flush=False)
        p=self.state['workspace_pending'];self.assertEqual(p['kind'],'sheet_preflight')
        self.assertEqual(len(p['details']['ids']),100)
        self.assertEqual(p['arguments']['ranges'],["'Case studies'!A2:Z101"])
        # A lost write response must accept the exact already-published rows.
        workspace.apply_response(self.base,self.state,p,self.grid(p['details']['rows'],1),runner.atomic_json)
        self.assertEqual(len(self.state['workspace_verified_ids']),100)
        workspace.ensure_sync(self.base,self.state,records,runner.atomic_json)
        p=self.state['workspace_pending'];self.assertEqual(p['details']['ids'],['100'])
        self.assertEqual(p['details']['start'],101)
        workspace.apply_response(self.base,self.state,p,self.grid(p['details']['rows'],101),runner.atomic_json)
        workspace.finalize(self.base,self.state,records,runner.atomic_json)
        p=self.state['workspace_pending'];self.assertEqual(p['kind'],'sheet_finalize')
        self.assertEqual(p['arguments']['ranges'],["'Case studies'!A1:Z1000"])
        rows=copy.deepcopy(p['details']['rows']);rows[-1]+=['Unexpected extra field']
        with self.assertRaisesRegex(workspace.WorkspaceError,'beyond column E'):
            workspace.apply_response(self.base,self.state,p,self.grid(rows),runner.atomic_json)


if __name__=='__main__':unittest.main()
