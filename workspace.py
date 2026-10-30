"""Durable Google Drive plugin requests executed by the Codex app, never by API key.

The runner emits exact connector arguments. The app saves the actual connector
response and acknowledges it. Writes only advance after independent readback.
"""
from __future__ import annotations
import hashlib
import html
import json
import re
import performance
from pathlib import Path

PREFIX = 'mcp__codex_apps__google_drive_'
HEADERS = ['Case-study source','Customer company','People involved','Company profile','Buying situation']
REPORT_SECTIONS = ['Overview','Company profiles','People and stakeholders','Buying situations','Methods and sources']
SEED = Path(__file__).resolve().parent/'assets/case_studies_seed.xlsx'

class WorkspaceError(ValueError): pass

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def unwrap(result):
    """Accept raw MCP results as well as native structured JSON, never prose receipts."""
    if not isinstance(result,dict): raise WorkspaceError('Connector response must be a JSON object.')
    if result.get('isError'): raise WorkspaceError('Connector error: '+json.dumps(result,ensure_ascii=False)[:1500])
    if isinstance(result.get('structuredContent'),dict): return result['structuredContent']
    if isinstance(result.get('content'),list):
        for block in result['content']:
            if block.get('type')=='text':
                try: data=json.loads(block['text'])
                except (ValueError,TypeError): continue
                if isinstance(data,dict): return data
        raise WorkspaceError('Connector supplied no structured JSON. Save the raw response and report the capability blocker.')
    return result

def rows_for(records):
    return [[r['provider']+'\n'+r['source_url'],r['customer'],r['people'],r['company_profile'],
             r['buying_situation'] if r['status']=='complete' else 'INACCESSIBLE — '+r['note']]
            for r in records]

def grid_values(data, row_count):
    """Read get_spreadsheet_cells' native grid data, retaining empty cells."""
    sheets=data.get('sheets',[])
    if len(sheets)!=1: raise WorkspaceError('Readback must contain exactly one requested sheet.')
    blocks=sheets[0].get('data',[])
    if len(blocks)!=1: raise WorkspaceError('Readback must contain exactly one bounded grid range.')
    block=blocks[0]; values=[]
    for row in block.get('rowData',[]):
        for cell in row.get('values',[])[5:]:
            value=cell.get('userEnteredValue',{})
            if cell.get('dataValidation') or (value and value!={'stringValue':''}):
                raise WorkspaceError('Populated fields beyond column E in runner-owned database; refusing to discard them.')
        cells=[]
        for c in row.get('values',[])[:5]:
            if c.get('dataValidation'): raise WorkspaceError('Unexpected validation in runner-owned database.')
            v=c.get('userEnteredValue',{})
            if 'formulaValue' in v: raise WorkspaceError('Formula found in evidence database; expected literal text.')
            cells.append(v.get('stringValue',''))
        values.append((cells+['']*5)[:5])
    return (values+[['']*5 for _ in range(row_count)])[:row_count]

def request(base,state,kind,tool,args,details,atomic_json):
    old=state.get('workspace_pending')
    if old: return False
    seq=state.get('workspace_sequence',0)+1
    req={'id':f'ws_{seq:05d}','kind':kind,'tool':PREFIX+tool,'arguments':args,
         'details':details,'status':'ready'}
    req['sha256']=digest(req)
    atomic_json(base/'workspace'/f'{req["id"]}.request.json',req)
    performance.event(base,state.get('phase','workspace'),'workspace_plan',operation=kind,request_id=req['id'])
    state['workspace_sequence']=seq; state['workspace_pending']=req
    return False

def title(state,kind):
    if kind=='Case-study research':return f'{state["company"]} | Working ICP'
    token=digest([state['id'],state['created_at']])[:12]
    return f'{state["company"]} — {kind} [research-{token}]'

def read_request(base,state,kind,start,count,details,atomic_json):
    sheet=state['workspace_sheet']
    tab="'"+sheet['tab'].replace("'","''")+"'"
    # Physical capacity may exceed the five-field publication schema. Inspect
    # those cells too, so populated extra fields cannot be silently truncated.
    width=sheet.get('column_count',5);last=''
    while width:
        width,remainder=divmod(width-1,26);last=chr(65+remainder)+last
    return request(base,state,kind,'get_spreadsheet_cells',{
        'spreadsheet_id':sheet['id'],'ranges':[f'{tab}!A{start+1}:{last}{start+count}'],
        'cell_fields':'userEnteredValue,dataValidation'},
        dict(details,start=start,count=count),atomic_json)

def ensure_sync(base,state,records,atomic_json,flush=True):
    """Called before another extraction. Fixed row addresses make replays safe."""
    if state.get('workspace_pending'): return False
    policy=state.get('workspace_policy',{})
    if policy.get('complete_only'):records=[r for r in records if r['status']=='complete']
    if not flush and policy and len(records)-len(state.get('workspace_verified_ids',[]))<policy.get('sync_batch_size',100):return True
    if not state.get('workspace_sheet'):
        if not SEED.exists(): raise WorkspaceError('Missing assets/case_studies_seed.xlsx; rebuild with scripts/build_seed.mjs.')
        args={
            'source_file':str(SEED),'title':title(state,'Case-study database'),
            'upload_mode':'native_google_sheets'}
        if state.get('workspace_parent_folder_id'):args['parent_folder_id']=state['workspace_parent_folder_id']
        return request(base,state,'sheet_create','import_spreadsheet',args,{},atomic_json)
    if not state['workspace_sheet'].get('tab'):
        return request(base,state,'sheet_metadata','get_spreadsheet_metadata',{
            'spreadsheet_id':state['workspace_sheet']['id']},{},atomic_json)
    if not state.get('workspace_header_verified'):
        return read_request(base,state,'sheet_header',0,1,{},atomic_json)
    verified=state.get('workspace_verified_ids',[])
    ids=[r['id'] for r in records]
    if ids[:len(verified)]!=verified: raise WorkspaceError('Saved row identity order changed; refusing to overwrite completed rows.')
    if len(verified)==len(records): return True
    sheet=state['workspace_sheet']
    if len(records)+1>sheet['row_count']:
        needed=max(len(records)+1,sheet['row_count']*2)
        return request(base,state,'sheet_resize','batch_update_spreadsheet',{'spreadsheet_id':sheet['id'],
            'requests':[{'updateSheetProperties':{'properties':{'sheetId':sheet['sheet_id'],'gridProperties':{'rowCount':needed}},'fields':'gridProperties.rowCount'}}]},
            {'row_count':needed},atomic_json)
    chunk=records[len(verified):len(verified)+state.get('workspace_policy',{}).get('sync_batch_size',20)]
    return read_request(base,state,'sheet_preflight',len(verified)+1,len(chunk),
                        {'ids':[r['id'] for r in chunk],'rows':rows_for(chunk)},atomic_json)

def write_rows(base,state,details,atomic_json):
    sheet=state['workspace_sheet'];start=details['start']; rows=details['rows']
    end=start+len(rows)
    if end>sheet['row_count']: raise WorkspaceError('Database exceeds allocated rows; metadata/grid capacity must be repaired before resuming.')
    cell_rows=[{'values':[{'userEnteredValue':{'stringValue':str(v)}} for v in r]} for r in rows]
    reqs=[{'updateCells':{'range':{'sheetId':sheet['sheet_id'],'startRowIndex':start,'endRowIndex':end,
             'startColumnIndex':0,'endColumnIndex':5},'rows':cell_rows,'fields':'userEnteredValue'}},
          {'repeatCell':{'range':{'sheetId':sheet['sheet_id'],'startRowIndex':start,'endRowIndex':end,'startColumnIndex':0,'endColumnIndex':5},
             'cell':{'userEnteredFormat':{'wrapStrategy':'WRAP','verticalAlignment':'TOP','textFormat':{'fontFamily':'Arial','fontSize':11}}},
             'fields':'userEnteredFormat'}},
          {'autoResizeDimensions':{'dimensions':{'sheetId':sheet['sheet_id'],'dimension':'ROWS','startIndex':start,'endIndex':end}}}]
    return request(base,state,'sheet_write','batch_update_spreadsheet',{'spreadsheet_id':sheet['id'],'requests':reqs},details,atomic_json)


def reconcile_dataset(base,state,atomic_json):
    """Back up and compact runner-owned values in the SAME native Sheet."""
    if state.get('workspace_pending'):return False
    plan=state['workspace_reconciliation'];sheet=state['workspace_sheet']
    if not plan.get('native_backup'):
        return request(base,state,'sheet_reconcile_copy','copy_file',{
            'url':sheet['url'],'new_title':title(state,'Dataset backup '+state['dataset_revision'])},{},atomic_json)
    if not sheet.get('tab'):
        return request(base,state,'sheet_reconcile_metadata','get_spreadsheet_metadata',{'spreadsheet_id':sheet['id']},{},atomic_json)
    count=sheet['row_count']
    if len(plan['old_rows'])+1>count:raise WorkspaceError('Original Sheet rows exceed the known grid; refusing reconciliation.')
    old=[HEADERS]+plan['old_rows'];old += [['']*5 for _ in range(count-len(old))]
    offset=plan['backup_offset']
    if offset<count:
        rows=old[offset:offset+1000]
        return read_request(base,state,'sheet_reconcile_backup',offset,len(rows),{'rows':rows},atomic_json)
    offset=plan['write_offset'];new=plan['new_rows']+[['']*5 for _ in range(len(plan['old_rows'])-len(plan['new_rows']))]
    if offset<len(plan['old_rows']):
        end=min(offset+20,len(plan['old_rows']))
        return read_request(base,state,'sheet_reconcile_preflight',offset+1,end-offset,
                            {'old_rows':plan['old_rows'][offset:end],'rows':new[offset:end],'next':end},atomic_json)
    rows=[HEADERS]+plan['new_rows'];rows += [['']*5 for _ in range(count-len(rows))]
    offset=plan.get('verify_offset',0)
    if offset<count:
        chunk=rows[offset:offset+1000]
        return read_request(base,state,'sheet_reconcile_final',offset,len(chunk),{'rows':chunk},atomic_json)
    state['workspace_verified_ids']=plan['new_ids'];state['workspace_header_verified']=True
    state['last_dataset_backup']=plan['native_backup']
    state.pop('workspace_reconciliation');state['phase']='stage2'
    return True

def finalize(base,state,records,atomic_json):
    audit_unavailable=sum(r['status']=='inaccessible' for r in records)
    if state.get('workspace_policy',{}).get('complete_only'):
        atomic_json(base/'inaccessible_audit.json',[r for r in records if r['status']=='inaccessible'])
        records=[r for r in records if r['status']=='complete']
    if not ensure_sync(base,state,records,atomic_json): return False
    if not any(r['status']=='complete' for r in records): raise WorkspaceError('No accessible case studies; cannot produce evidence-based analysis.')
    # Read all rows in bounded chunks, including a blank sentinel after the data.
    offset=state.get('workspace_finalize_offset',0)
    rows=[HEADERS]+rows_for(records)
    rows += [['']*5 for _ in range(state['workspace_sheet']['row_count']-len(rows))]
    if offset<len(rows):
        chunk=rows[offset:offset+1000]
        return read_request(base,state,'sheet_finalize',offset,len(chunk),{'rows':chunk,'total':len(rows)},atomic_json)
    snapshot={'sheet':state['workspace_sheet'],'headers':HEADERS,'rows':rows_for(records),
              'case_ids':[r['id'] for r in records],
              'inventoried':len(records),'complete':sum(r['status']=='complete' for r in records),
              'unavailable':sum(r['status']=='inaccessible' for r in records),
              'provider_counts':{p:sum(r['provider']==p for r in records) for p in state['approved_providers']}}
    if state.get('workspace_policy',{}).get('complete_only'):snapshot['inaccessible_audit_count']=audit_unavailable
    snapshot['case_notes']={r['id']:r['note'] for r in records if r.get('note','').strip()}
    if 'screening_summary' in state:snapshot['screening_summary']=state['screening_summary']
    snapshot['sha256']=digest(snapshot)
    path=base/'finalized_sheet.json'
    if path.exists() and json.loads(path.read_text())!=snapshot: raise WorkspaceError('Finalized Sheet snapshot is immutable.')
    atomic_json(path,snapshot)
    state['finalized_sheet_sha256']=snapshot['sha256']; state['phase']='stage4'
    return True

def frozen_database(base,state):
    data=json.loads((base/'finalized_sheet.json').read_text())
    checksum=data.pop('sha256')
    if digest(data)!=checksum or checksum!=state.get('finalized_sheet_sha256'):
        raise WorkspaceError('Finalized database checksum mismatch.')
    data['sha256']=checksum
    return data

def file_identity(data,mime):
    # Exact observed provider fields only. Never synthesize a user-facing URL.
    item=data.get('file',data)
    actual=item.get('mimeType',item.get('mime_type'))
    if actual!=mime: raise WorkspaceError('Connector did not confirm the requested native Google file type: '+str(actual))
    fid=item.get('id') or item.get('fileId') or item.get('spreadsheetId') or item.get('documentId')
    url=item.get('webViewLink') or item.get('spreadsheetUrl') or item.get('documentUrl') or item.get('url')
    if not isinstance(fid,str) or not isinstance(url,str) or fid not in url:
        raise WorkspaceError('Connector did not return a matching native file ID and URL.')
    return {'id':fid,'url':url}

def apply_response(base,state,pending,result,atomic_json):
    if pending['kind'].startswith(('doc_tabs_','doc_edit_')):
        import document_tabs
        return document_tabs.apply_response(base,state,pending,result,atomic_json)
    if pending['kind'].startswith('synthesis_'):
        import synthesis_publication
        return synthesis_publication.apply_response(base,state,pending,result,atomic_json)
    data=unwrap(result);kind=pending['kind']; d=pending['details']
    if kind in ('sheet_header','sheet_preflight','sheet_verify','sheet_finalize','sheet_saved_verify','sheet_reconcile_backup','sheet_reconcile_preflight','sheet_reconcile_verify','sheet_reconcile_final'):
        sheet=state['workspace_sheet']
        if data.get('spreadsheetId')!=sheet['id'] or data.get('sheets',[{}])[0].get('properties',{}).get('sheetId')!=sheet['sheet_id']:
            raise WorkspaceError('Sheet readback identity mismatch.')
        block=data['sheets'][0].get('data',[{}])[0]
        if block.get('startRow',0)!=d['start'] or block.get('startColumn',0)!=0:
            raise WorkspaceError('Sheet readback range mismatch.')
    state.pop('workspace_pending',None)
    if kind=='sheet_reconcile_copy':
        backup=file_identity(data,'application/vnd.google-apps.spreadsheet')
        if backup['id']==state['workspace_sheet']['id']:raise WorkspaceError('Backup must be a distinct native file.')
        state['workspace_reconciliation']['backup_candidate']=backup
        return request(base,state,'sheet_reconcile_copy_verify','get_file_metadata',
                       {'fileId':backup['id'],'fields':'id,mimeType,webViewLink'},{},atomic_json)
    elif kind=='sheet_reconcile_copy_verify':
        backup=file_identity(data,'application/vnd.google-apps.spreadsheet')
        if backup['id']!=state['workspace_reconciliation']['backup_candidate']['id']:raise WorkspaceError('Native backup identity mismatch.')
        state['workspace_reconciliation']['native_backup']=backup
        atomic_json(Path(state['workspace_reconciliation']['backup'])/'native_sheet_identity.json',backup)
    elif kind=='sheet_reconcile_backup':
        if grid_values(data,d['count'])!=d['rows']:raise WorkspaceError('Original Sheet changed; no dataset reconciliation write attempted.')
        atomic_json(Path(state['workspace_reconciliation']['backup'])/'native_sheet'/f'{pending["id"]}.json',result)
        state['workspace_reconciliation']['backup_offset']=d['start']+d['count']
    elif kind=='sheet_reconcile_preflight':
        got=grid_values(data,d['count'])
        if got==d['rows']:state['workspace_reconciliation']['write_offset']=d['next']
        elif got==d['old_rows']:
            sheet=state['workspace_sheet']
            rows=[{'values':[{'userEnteredValue':{'stringValue':v}} for v in row]} for row in d['rows']]
            return request(base,state,'sheet_reconcile_write','batch_update_spreadsheet',{
                'spreadsheet_id':sheet['id'],'requests':[{'updateCells':{'range':{
                    'sheetId':sheet['sheet_id'],'startRowIndex':d['start'],'endRowIndex':d['start']+d['count'],
                    'startColumnIndex':0,'endColumnIndex':5},'rows':rows,'fields':'userEnteredValue'}}]},d,atomic_json)
        else:raise WorkspaceError('Reconciliation destination conflicts with saved old and desired rows; no overwrite attempted.')
    elif kind=='sheet_reconcile_write':
        return read_request(base,state,'sheet_reconcile_verify',d['start'],d['count'],d,atomic_json)
    elif kind=='sheet_reconcile_verify':
        if grid_values(data,d['count'])!=d['rows']:raise WorkspaceError('Reconciled rows failed independent readback.')
        state['workspace_reconciliation']['write_offset']=d['next']
    elif kind=='sheet_reconcile_final':
        if grid_values(data,d['count'])!=d['rows']:raise WorkspaceError('Reconciled Sheet has shifted, duplicate, or unexpected rows.')
        state['workspace_reconciliation']['verify_offset']=d['start']+d['count']
    elif kind=='sheet_create':
        state['workspace_sheet']=file_identity(data,'application/vnd.google-apps.spreadsheet')
        state['sheet_url']=state['workspace_sheet']['url']
    elif kind in ('sheet_metadata','sheet_reconcile_metadata'):
        sheet=state['workspace_sheet']
        if data.get('spreadsheetId')!=sheet['id']: raise WorkspaceError('Sheet metadata identity mismatch.')
        tabs=data.get('sheets',[])
        if len(tabs)!=1: raise WorkspaceError('Expected exactly one database sheet.')
        p=tabs[0]['properties']; grid=p['gridProperties']
        if p['title']!='Case studies' or grid['columnCount']<5: raise WorkspaceError('Imported template structure is incorrect.')
        sheet.update(tab=p['title'],sheet_id=p['sheetId'],row_count=grid['rowCount'],column_count=grid['columnCount'])
        if kind=='sheet_reconcile_metadata':return True
        # Allocate a generous but finite grid once; no per-batch global restyling.
        batches=json.loads((base/'batches.json').read_text()) if (base/'batches.json').exists() else []
        needed=max(1000,1+sum(len(b['cases']) for b in batches))
        if sheet['row_count']<needed:
            return request(base,state,'sheet_resize','batch_update_spreadsheet',{
                'spreadsheet_id':sheet['id'],'requests':[{'updateSheetProperties':{'properties':{
                    'sheetId':sheet['sheet_id'],'gridProperties':{'rowCount':needed}},'fields':'gridProperties.rowCount'}}]},
                {'row_count':needed},atomic_json)
    elif kind=='sheet_resize': state['workspace_sheet']['row_count']=d['row_count']
    elif kind=='sheet_header':
        if grid_values(data,1)!=[HEADERS]: raise WorkspaceError('Native Sheet headers differ from Refold template.')
        state['workspace_header_verified']=True
    elif kind=='sheet_preflight':
        got=grid_values(data,d['count'])
        if got==d['rows']:
            state.setdefault('workspace_verified_ids',[]).extend(d['ids'])
        elif got==[['']*5 for _ in d['rows']]:
            return write_rows(base,state,d,atomic_json)
        else: raise WorkspaceError('Sheet destination contains conflicting or shifted rows; no overwrite attempted.')
    elif kind=='sheet_write':
        return read_request(base,state,'sheet_verify',d['start'],d['count'],d,atomic_json)
    elif kind=='sheet_verify':
        if grid_values(data,d['count'])!=d['rows']: raise WorkspaceError('Sheet write readback differs from validated extraction.')
        state.setdefault('workspace_verified_ids',[]).extend(d['ids'])
    elif kind=='sheet_finalize':
        if grid_values(data,d['count'])!=d['rows']: raise WorkspaceError('Final Sheet readback differs from saved records or has an extra row.')
        state['workspace_finalize_offset']=d['start']+d['count']
    elif kind=='sheet_saved_verify':
        if grid_values(data,d['count'])!=d['rows']:raise WorkspaceError('Saved-record Sheet readback has changed, shifted, duplicate or unexpected rows.')
        state['workspace_saved_offset']=d['start']+d['count']
    elif kind=='doc_create':
        state['workspace_document']=file_identity(data,'application/vnd.google-apps.document')
        state['document_url']=state['workspace_document']['url']
    elif kind=='doc_layout':
        state['document_layout_done']=True
    elif kind=='doc_verify':
        doc=state['workspace_document']
        if data.get('documentId')!=doc['id']: raise WorkspaceError('Document readback identity mismatch.')
        expected=json.loads((base/'report_expected.json').read_text())
        texts=[]; headings=[];tables=[]
        def walk(x):
            if isinstance(x,dict):
                if isinstance(x.get('textRun'),dict): texts.append(x['textRun'].get('content',''))
                if x.get('paragraphStyle',{}).get('namedStyleType','').startswith('HEADING'): headings.append(x)
                if 'tableRows' in x: tables.append(x)
                for k,v in x.items():
                    if k!='textRun': walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(data.get('tabs') or data.get('body',{}))
        def bullet_count(x):
            if isinstance(x,dict):return int('bullet' in x.get('paragraph',{}))+sum(bullet_count(v) for v in x.values())
            if isinstance(x,list):return sum(bullet_count(v) for v in x)
            return 0
        if bullet_count(data.get('tabs') or data.get('body',{}))<expected.get('bullets',0):
            raise WorkspaceError('Native Doc lost bullet formatting during conversion.')
        compact=lambda s:re.sub(r'\s+','',s)
        if compact(''.join(texts))!=compact(expected['text']): raise WorkspaceError('Native Doc text readback differs from complete report.')
        if len(tables)!=expected['tables'] or len(headings)<expected['headings']:
            raise WorkspaceError('Native Doc lost report tables or heading structure during conversion.')
        sections={}
        for tab in data.get('tabs',[]):
            tab_id=tab.get('tabId') or tab.get('tabProperties',{}).get('tabId')
            body=tab.get('body') or tab.get('documentTab',{}).get('body',{})
            for element in body.get('content',[]):
                paragraph=element.get('paragraph',{})
                name=''.join(e.get('textRun',{}).get('content','') for e in paragraph.get('elements',[])).strip()
                if name in REPORT_SECTIONS and paragraph.get('paragraphStyle',{}).get('namedStyleType')=='HEADING_1':
                    if name in sections:raise WorkspaceError('Duplicate main report section: '+name)
                    sections[name]=(tab_id,element,paragraph)
        if set(sections)!=set(REPORT_SECTIONS):raise WorkspaceError('Native report section ranges are missing.')
        if not state.get('document_layout_done'):
            revision=data.get('revisionId')
            if not revision:raise WorkspaceError('Document revision is unavailable for guarded formatting.')
            requests=[]
            for name,(tab_id,element,paragraph) in sections.items():
                requests.append({'updateParagraphStyle':{'range':{
                    'tabId':tab_id,'startIndex':element['startIndex'],'endIndex':element['endIndex']},
                    'paragraphStyle':{'pageBreakBefore':name!='Overview','keepWithNext':True},
                    'fields':'pageBreakBefore,keepWithNext'}})
            return request(base,state,'doc_layout','batch_update_document',{'document_id':doc['id'],
                'write_control':{'requiredRevisionId':revision},'requests':requests},{},atomic_json)
        for name,(_,element,paragraph) in sections.items():
            if name!='Overview' and not paragraph.get('paragraphStyle',{}).get('pageBreakBefore'):
                raise WorkspaceError('Native report lost a section page break: '+name)
        state['document_verified']=True;state['phase']='complete'
        if state.get('workspace_policy',{}).get('native_doc_tabs'):
            import document_tabs
            return document_tabs.start(base,state,atomic_json,data)
    else: raise WorkspaceError('Unsupported Workspace action: '+kind)
    return True

def render_report(markdown):
    """Small Markdown subset -> native import HTML, including real frequency tables."""
    lines=markdown.splitlines();parts=[];text=[];tables=0;headings=0;i=0;bullets=0
    def inline(value):
        value=re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'\1 (\2)',value)
        return re.sub(r'[*`]', '', value)
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('|'):
            table=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[inline(c.strip()) for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):table.append(cells)
                i+=1
            if not table or len({len(r) for r in table})!=1: raise WorkspaceError('Malformed report frequency table.')
            parts.append('<table>')
            for j,row in enumerate(table):
                tag='th' if j==0 else 'td'
                parts.append('<tr>'+''.join(f'<{tag}>{html.escape(c)}</{tag}>' for c in row)+'</tr>');text.extend(row)
            parts.append('</table>');tables+=1;continue
        if re.match(r'^[-*]\s+',line):
            parts.append('<ul>')
            while i<len(lines) and re.match(r'^[-*]\s+',lines[i].strip()):
                value=inline(re.sub(r'^[-*]\s+','',lines[i].strip()))
                parts.append('<li>'+html.escape(value)+'</li>');text.append(value);bullets+=1;i+=1
            parts.append('</ul>');continue
        match=re.match(r'^(#{1,6})\s+(.+)',line)
        value=inline(match[2] if match else re.sub(r'^[-*]\s+','',line))
        if match:
            level=min(len(match[1]),3);headings+=1
            parts.append(f'<h{level}>{html.escape(value)}</h{level}>')
        else:parts.append('<p>'+html.escape(value)+'</p>')
        text.append(value);i+=1
    doc='<!DOCTYPE html><html><head><meta charset="utf-8"><style>body{font-family:Arial;font-size:11pt}h1{font-size:20pt;page-break-before:always}h1:first-child{page-break-before:auto}h2{font-size:15pt}table{border-collapse:collapse;width:100%}th,td{border:1px solid #d9dfe5;padding:6px;vertical-align:top}th{background:#edf2f5;text-align:left}</style></head><body>'+''.join(parts)+'</body></html>'
    return doc,{'text':'\n'.join(text),'tables':tables,'headings':headings,'bullets':bullets}

def publish_report(base,state,atomic_json,atomic_text):
    if state.get('workspace_pending'):return False
    report=json.loads((base/'report.json').read_text());checksum=report.pop('sha256')
    if digest(report)!=checksum or report['database_sha256']!=state['finalized_sheet_sha256'] or (base/'report.md').read_text()!=report['markdown']:
        raise WorkspaceError('Final report checksum/provenance mismatch.')
    if state.get('workspace_document'):
        if state.get('recovered_publication') and not state.get('editorial_report'):
            payload={'markdown':report['markdown'],'database_sha256':state['finalized_sheet_sha256'],
                     'previous_sections':state['recovered_publication']['previous_sections']}
            payload['sha256']=digest(payload)
            path=base/'presentation'/'editorial'/('report_'+payload['sha256'][:16]+'.json')
            atomic_json(path,payload);state['editorial_report']={'path':str(path),'sha256':payload['sha256']}
            state['phase']='revise_doc'
            import document_tabs
            return document_tabs.inspect_request(base,state,atomic_json)
        if state.get('native_doc_tabs'):
            import document_tabs
            return document_tabs.start(base,state,atomic_json)
        return request(base,state,'doc_verify','get_document',{'document_id':state['workspace_document']['id']},{},atomic_json)
    html_text,expected=render_report(report['markdown'])
    atomic_text(base/'report.html',html_text);atomic_json(base/'report_expected.json',expected)
    return request(base,state,'doc_create','import_document',{'source_file':str(base/'report.html'),
        'title':title(state,'Case-study research'),'upload_mode':'native_google_docs'},{},atomic_json)
