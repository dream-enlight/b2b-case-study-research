"""Publication-only projections and native in-place report request planning.

Plans are deterministic, preflighted against actual connector readbacks and
verified before the runner marks a semantic revision complete.
"""
import json
import re
from collections import Counter
import workspace
import analysis_pipeline as ap
import semantic_synthesis as ss

DOC_FIELDS='documentId,title,revisionId,tabs(tabProperties,documentTab(body(content)))'
DOC_BOUNDARY_FIELDS='documentId,title,revisionId,tabs(tabProperties,documentTab(body(content(startIndex,endIndex))))'


def prepare(api,base,state,backups,preflight):
    db=workspace.frozen_database(base,state);h=ss.home(base,db)
    report=json.loads((h/'report.json').read_text());check=dict(report);checksum=check.pop('sha256')
    if workspace.digest(check)!=checksum:raise workspace.WorkspaceError('Synthesis report checksum mismatch.')
    if state.get('semantic_publication'):return advance(api,base,state)
    identities=[]
    for n,mime,original in [(0,'application/vnd.google-apps.document',state['workspace_document']['id']),
                            (1,'application/vnd.google-apps.spreadsheet',state['workspace_sheet']['id'])]:
        result=backups[n]
        if result.get('status')!='fulfilled':raise workspace.WorkspaceError('Both native backups must succeed before revision.')
        identity=workspace.file_identity(workspace.unwrap(result['value']),mime)
        if identity['id']==original:raise workspace.WorkspaceError('A backup must have a separate native ID.')
        identities.append(identity)
    sheet=state['workspace_sheet'];data=workspace.unwrap(preflight)
    if data.get('spreadsheetId')!=sheet['id']:raise workspace.WorkspaceError('Sheet preflight identity mismatch.')
    actual=workspace.grid_values(data,sheet['row_count'])
    requests=sheet_cleanup_requests(db,actual,sheet['row_count'],sheet['sheet_id'])
    p=projection(db);api.atomic_json(h/'publication_projection.json',p)
    api.atomic_json(h/'inaccessible_audit_ledger.json',{'source_database_sha256':db['sha256'],'records':p['inaccessible_audit']})
    api.atomic_json(h/'native_backups.json',backups);api.atomic_json(h/'sheet_preflight.tool.json',preflight)
    state['semantic_publication']={'projection_sha256':p['sha256'],'report_sha256':report['sha256'],
        'native_backups':identities,'step':'sheet_clean','clean_row_count':sheet['row_count']-db['unavailable']}
    state['phase']='publish_synthesis';state['document_verified']=False
    return workspace.request(base,state,'synthesis_sheet_clean','batch_update_spreadsheet',{
        'spreadsheet_id':sheet['id'],'requests':requests},{},api.atomic_json)


def advance(api,base,state):
    if state.get('workspace_pending'):return False
    db=workspace.frozen_database(base,state);h=ss.home(base,db);plan=state['semantic_publication'];sheet=state['workspace_sheet']
    if plan['step']=='sheet_verify':
        return workspace.read_request(base,state,'synthesis_sheet_verify',0,plan['clean_row_count'],{},api.atomic_json)
    if plan['step'] in ('doc_read','doc_empty_read','doc_final_read'):
        return workspace.request(base,state,'synthesis_'+plan['step'],'get_document',{
            'document_id':state['workspace_document']['id'],'fields':DOC_BOUNDARY_FIELDS if plan['step']=='doc_read' else DOC_FIELDS},{},api.atomic_json)
    if plan['step']=='complete':return True
    raise workspace.WorkspaceError('Synthesis publication has an uncertain write; inspect saved receipt before continuing.')


def apply_response(base,state,pending,result,atomic_json):
    # The surrounding runner ACK persists state and the complete actual response.
    class API:
        pass
    api=API();api.atomic_json=atomic_json
    data=workspace.unwrap(result);kind=pending['kind'];plan=state['semantic_publication']
    db=workspace.frozen_database(base,state);h=ss.home(base,db)
    report=json.loads((h/'report.json').read_text());markdown=report['markdown']
    state.pop('workspace_pending',None)
    if kind=='synthesis_sheet_clean':
        if data.get('spreadsheetId')!=state['workspace_sheet']['id']:raise workspace.WorkspaceError('Sheet cleanup response identity mismatch.')
        plan['step']='sheet_verify'
    elif kind=='synthesis_sheet_verify':
        if data.get('spreadsheetId')!=state['workspace_sheet']['id']:raise workspace.WorkspaceError('Cleaned Sheet readback identity mismatch.')
        p=json.loads((h/'publication_projection.json').read_text())
        verify_projection(p,workspace.grid_values(data,plan['clean_row_count']),plan['clean_row_count'])
        plan['sheet_verified']=True;plan['step']='doc_read'
        state['workspace_sheet']['row_count']=plan['clean_row_count']
        state['published_complete_case_ids']=p['case_ids'];state['publication_projection_sha256']=p['sha256']
    elif kind=='synthesis_doc_read':
        if data.get('documentId')!=state['workspace_document']['id']:raise workspace.WorkspaceError('Native report identity mismatch.')
        args,tables=document_replace_plan(data,markdown);atomic_json(h/'native_table_plan.json',tables)
        plan['step']='doc_replace'
        return workspace.request(base,state,'synthesis_doc_replace','batch_update_document',args,{},atomic_json)
    elif kind=='synthesis_doc_replace':
        if data.get('documentId')!=state['workspace_document']['id']:raise workspace.WorkspaceError('Doc revision response identity mismatch.')
        plan['step']='doc_empty_read'
    elif kind=='synthesis_doc_empty_read':
        tables=json.loads((h/'native_table_plan.json').read_text());args=table_fill_plan(data,tables)
        plan['step']='doc_fill'
        return workspace.request(base,state,'synthesis_doc_fill','batch_update_document',args,{},atomic_json)
    elif kind=='synthesis_doc_fill':
        if data.get('documentId')!=state['workspace_document']['id']:raise workspace.WorkspaceError('Doc table fill response identity mismatch.')
        plan['step']='doc_final_read'
    elif kind=='synthesis_doc_final_read':
        if data.get('documentId')!=state['workspace_document']['id']:raise workspace.WorkspaceError('Final Doc identity mismatch.')
        verification=verify_document(data,markdown);atomic_json(h/'native_verification.json',verification)
        # Original report and every intermediate artifact remain in the ZIP backup.
        atomic_json(base/'report.json',report)
        (base/'report.md').write_text(markdown)
        html,expected=workspace.render_report(markdown);(base/'report.html').write_text(html);atomic_json(base/'report_expected.json',expected)
        plan['step']='complete';state['phase']='complete';state['document_verified']=True;state['document_layout_done']=True
        state.pop('pause_reason',None);state.pop('paused_from',None)
        return True
    else:raise workspace.WorkspaceError('Unknown semantic publication response.')
    return advance(api,base,state)


def projection(db):
    rows=ap.eligible_rows(db)
    unavailable=[{'id':cid,'cells':row} for cid,row in zip(db['case_ids'],db['rows']) if cid not in rows]
    p={'source_database_sha256':db['sha256'],'sheet':db['sheet'],'headers':db['headers'],
       'case_ids':list(rows),'rows':list(rows.values()),'inaccessible_audit':unavailable}
    p['sha256']=workspace.digest(p)
    return p


def sheet_cleanup_requests(db,actual,row_count,sheet_id):
    expected=[db['headers']]+db['rows']
    expected += [['']*5 for _ in range(row_count-len(expected))]
    if actual!=expected:raise workspace.WorkspaceError('Sheet changed since frozen snapshot; refusing cleanup.')
    excluded=[i+1 for i,row in enumerate(db['rows']) if row[4].startswith('INACCESSIBLE — ')]
    groups=[]
    for n in excluded:
        if groups and groups[-1][1]==n:groups[-1][1]=n+1
        else:groups.append([n,n+1])
    return [{'deleteDimension':{'range':{'sheetId':sheet_id,'dimension':'ROWS','startIndex':a,'endIndex':b}}} for a,b in reversed(groups)]


def verify_projection(p,actual,row_count):
    check=dict(p);checksum=check.pop('sha256')
    if workspace.digest(check)!=checksum:raise workspace.WorkspaceError('Publication projection checksum mismatch.')
    expected=[p['headers']]+p['rows'];expected += [['']*5 for _ in range(row_count-len(expected))]
    if actual!=expected:raise workspace.WorkspaceError('Cleaned Sheet differs from complete-record projection.')
    if len(p['case_ids'])!=len(set(p['case_ids'])) or any(r[4].startswith('INACCESSIBLE — ') for r in p['rows']):
        raise workspace.WorkspaceError('Invalid complete-record publication identity.')


def document_body(data):
    tabs=data.get('tabs',[])
    if len(tabs)!=1:raise workspace.WorkspaceError('Report revision requires exactly one inspected native tab.')
    tab=tabs[0];tid=tab.get('tabId') or tab.get('tabProperties',{}).get('tabId')
    body=tab.get('body') or tab.get('documentTab',{}).get('body',{})
    if not tid or not body.get('content'):raise workspace.WorkspaceError('Native Doc structure is unavailable.')
    return tid,body


def u16(s):return len(s.encode('utf-16-le'))//2
def inline(s):
    # Preserve readable links in the native document; target comes from frozen Sheet.
    return re.sub(r'[*`]', '', re.sub(r'\[([^\]]+)\]\((https?://[^\s)]+)\)',r'\1 (\2)',s))


def parse_markdown(markdown):
    lines=markdown.splitlines();text='';headings=[];tables=[];i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].strip().startswith('|'):
                cells=[inline(c.strip()) for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):rows.append(cells)
                i+=1
            if not rows or len({len(r) for r in rows})!=1:raise workspace.WorkspaceError('Invalid synthesis table.')
            marker='[[SYNTHESIS_TABLE_'+str(len(tables))+']]'
            tables.append({'index':1+u16(text),'marker':marker,'rows':rows})
            text+=marker+'\n';continue
        m=re.match(r'^(#{1,3})\s+(.+)',line)
        value=inline(m[2] if m else re.sub(r'^[-*]\s+','',line))
        if m:headings.append({'start':1+u16(text),'end':1+u16(text+value),'level':len(m[1]),'text':value})
        text+=value+'\n';i+=1
    return text,headings,tables


def bullet_ranges(markdown):
    text,_,_=parse_markdown(markdown)
    # Tables become one marker paragraph; only ordinary source lines correspond
    # to paragraphs in the rendered text. Walk in order (titles may repeat).
    rendered=text.splitlines(keepends=True);cursor=0;offset=1;result=[]
    lines=markdown.splitlines();i=0
    while i<len(lines):
        line=lines[i].strip()
        if not line:i+=1;continue
        if line.startswith('|'):
            while i<len(lines) and lines[i].strip().startswith('|'):i+=1
        else:
            if re.match(r'^[-*]\s+',line):
                result.append((offset,offset+u16(rendered[cursor].rstrip('\n'))))
            i+=1
        offset+=u16(rendered[cursor]);cursor+=1
    return result


def document_replace_plan(data,markdown,*,section=False):
    if not section:ss.validate_report(markdown)
    tid,body=document_body(data)
    text,headings,tables=parse_markdown(markdown)
    end=max(e.get('endIndex',0) for e in body['content'])-1
    if end<1 or (end==1 and not section):raise workspace.WorkspaceError('Existing document end is not safely resolved.')
    def rng(start,end):return {'tabId':tid,'startIndex':start,'endIndex':end}
    requests=([{'deleteContentRange':{'range':rng(1,end)}}] if end>1 else [])+[
        {'insertText':{'location':{'index':1,'tabId':tid},'text':text}},
        {'updateParagraphStyle':{'range':rng(1,1+u16(text)), 'paragraphStyle':{
            'namedStyleType':'NORMAL_TEXT','pageBreakBefore':False,'keepWithNext':False,'spaceAbove':{'magnitude':0,'unit':'PT'},'spaceBelow':{'magnitude':6,'unit':'PT'}},
            'fields':'namedStyleType,pageBreakBefore,keepWithNext,spaceAbove,spaceBelow'}},
        {'updateTextStyle':{'range':rng(1,1+u16(text)), 'textStyle':{'fontSize':{'magnitude':11,'unit':'PT'},'bold':False,'italic':False},'fields':'fontSize,bold,italic'}}]
    for h in headings:
        requests.append({'updateParagraphStyle':{'range':rng(h['start'],h['end']), 'paragraphStyle':{
            'namedStyleType':'TITLE' if section and h['level']==1 else 'HEADING_'+str(h['level']),'keepWithNext':True,
            'pageBreakBefore':not section and h['level']==1 and h['text']!='Overview'},'fields':'namedStyleType,keepWithNext,pageBreakBefore'}})
        requests.append({'updateTextStyle':{'range':rng(h['start'],h['end']),'textStyle':{'fontSize':{'magnitude':22 if section and h['level']==1 else 18 if h['level']==1 else 13,'unit':'PT'}},'fields':'fontSize'}})
    for start,end in bullet_ranges(markdown):
        requests.append({'createParagraphBullets':{'range':rng(start,end),'bulletPreset':'BULLET_DISC_CIRCLE_SQUARE'}})
    for match in re.finditer(r'https?://[^\s)]+',text):
        url=match[0].rstrip('.,;');start=1+u16(text[:match.start()])
        requests.append({'updateTextStyle':{'range':rng(start,start+u16(url)),
            'textStyle':{'link':{'url':url}},'fields':'link'}})
    for t in reversed(tables):
        requests.append({'deleteContentRange':{'range':rng(t['index'],t['index']+u16(t['marker']))}})
        requests.append({'insertTable':{'rows':len(t['rows']),'columns':len(t['rows'][0]),'location':{'index':t['index'],'tabId':tid}}})
    return {'document_id':data['documentId'],'write_control':{'requiredRevisionId':data['revisionId']},'requests':requests},tables


def table_fill_plan(data,tables):
    tid,body=document_body(data);native=[e for e in body['content'] if 'table' in e]
    if len(native)!=len(tables):raise workspace.WorkspaceError('Native synthesis table count mismatch.')
    req=[];insertions=[]
    for element,expected in zip(native,tables):
        table=element['table'];rows=expected['rows']
        if len(table['tableRows'])!=len(rows):raise workspace.WorkspaceError('Native table row mismatch.')
        req.append({'updateParagraphStyle':{'range':{'tabId':tid,'startIndex':element['startIndex'],'endIndex':element['endIndex']-1},
            'paragraphStyle':{'namedStyleType':'NORMAL_TEXT','keepWithNext':False,'spaceBelow':{'magnitude':3,'unit':'PT'}},
            'fields':'namedStyleType,keepWithNext,spaceBelow'}})
        req.append({'updateTableRowStyle':{'tableStartLocation':{'index':element['startIndex'],'tabId':tid},
            'tableRowStyle':{'preventOverflow':True},'fields':'preventOverflow'}})
        for rn,(native_row,row) in enumerate(zip(table['tableRows'],rows)):
            if len(native_row['tableCells'])!=len(row):raise workspace.WorkspaceError('Native table column mismatch.')
            for cell,value in zip(native_row['tableCells'],row):
                paras=[e for e in cell['content'] if 'paragraph' in e]
                if len(paras)!=1:raise workspace.WorkspaceError('Unexpected empty native table cell structure.')
                index=paras[0]['startIndex'];insertions.append((index,value,rn==0))
    for index,value,header in sorted(insertions,reverse=True):
        req.append({'insertText':{'location':{'index':index,'tabId':tid},'text':value}})
        if value:req.append({'updateTextStyle':{'range':{'tabId':tid,'startIndex':index,'endIndex':index+u16(value)},
            'textStyle':{'bold':header,'fontSize':{'magnitude':10,'unit':'PT'}},'fields':'bold,fontSize'}})
    return {'document_id':data['documentId'],'write_control':{'requiredRevisionId':data['revisionId']},'requests':req}


def verify_document(data,markdown):
    tid,body=document_body(data);_,expected=workspace.render_report(markdown)
    texts=[];tables=[];headings=[]
    def walk(x):
        if isinstance(x,dict):
            if 'textRun' in x:texts.append(x['textRun'].get('content',''))
            if 'tableRows' in x:tables.append(x)
            if 'paragraph' in x:
                p=x['paragraph'];style=p.get('paragraphStyle',{})
                if style.get('namedStyleType','').startswith('HEADING'):
                    name=''.join(e.get('textRun',{}).get('content','') for e in p.get('elements',[])).strip()
                    headings.append((name,style))
            for k,v in x.items():
                if k!='textRun':walk(v)
        elif isinstance(x,list):
            for v in x:walk(v)
    walk(body)
    compact=lambda s:re.sub(r'\s+','',s)
    if compact(''.join(texts))!=compact(expected['text']):raise workspace.WorkspaceError('Rewritten native Doc content differs from synthesis report.')
    if len(tables)!=expected['tables']:raise workspace.WorkspaceError('Rewritten native Doc table count mismatch.')
    main=[n for n,s in headings if s.get('namedStyleType')=='HEADING_1']
    if main!=workspace.REPORT_SECTIONS:raise workspace.WorkspaceError('Rewritten native Doc main headings mismatch.')
    if any(not s.get('pageBreakBefore') for n,s in headings if n in main and n!='Overview'):
        raise workspace.WorkspaceError('Rewritten native Doc lacks a main section break.')
    return {'text_verified':True,'native_tables':len(tables),'headings':len(headings),'main_sections':main}
