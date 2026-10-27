"""Lossless native report organization; no research or model calls."""
import json
import re
from pathlib import Path
import workspace as ws
import synthesis_publication as native

TITLES=['Overview','Company profiles','People','Buying situations','Methods & sources']

def text(value):
    if isinstance(value,dict):
        if 'textRun' in value:return value['textRun'].get('content','')
        return ''.join(text(v) for k,v in value.items() if k!='textRun')
    if isinstance(value,list):return ''.join(text(v) for v in value)
    return ''

def compact(value):return re.sub(r'\s+','',value)
def body(tab):return tab.get('body') or tab.get('documentTab',{}).get('body',{})
def tid(tab):return tab.get('tabId') or tab.get('tabProperties',{}).get('tabId')
def title(tab):return tab.get('title') or tab.get('tabProperties',{}).get('title')
def wrapper(data,tab):return dict(documentId=data['documentId'],revisionId=data['revisionId'],tabs=[tab])

def sections(markdown):
    matches=list(re.finditer(r'^# (.+)$',markdown,re.M))
    if [m[1] for m in matches]!=ws.REPORT_SECTIONS:raise ws.WorkspaceError('Report section order differs from the verified five-section source.')
    result=[markdown[m.start():matches[i+1].start() if i+1<len(matches) else len(markdown)].strip()+'\n' for i,m in enumerate(matches)]
    return result

def expected(markdown):return ws.render_report(markdown)[1]['text']

def tables(tab):
    return [[[text(c).strip() for c in r['tableCells']] for r in e['table']['tableRows']]
            for e in body(tab).get('content',[]) if 'table' in e]

def matches(tab,markdown):
    _,_,source_tables=native.parse_markdown(markdown)
    return (compact(text(body(tab)))==compact(expected(markdown)) and
            [[list(map(compact,row)) for row in t] for t in tables(tab)]==
            [[list(map(compact,row)) for row in t['rows']] for t in source_tables])

def load(base,state):
    if state.get('editorial_report'):
        pointer=state['editorial_report'];report=json.loads(Path(pointer['path']).read_text());check=dict(report);checksum=check.pop('sha256')
        if ws.digest(check)!=checksum or checksum!=pointer['sha256'] or report['database_sha256']!=state['finalized_sheet_sha256']:
            raise ws.WorkspaceError('Editorial report checksum/provenance mismatch.')
        return sections(report['markdown'])
    report=json.loads((base/'report.json').read_text());check=dict(report);checksum=check.pop('sha256')
    if ws.digest(check)!=checksum or report['database_sha256']!=state['finalized_sheet_sha256'] or (base/'report.md').read_text()!=report['markdown']:
        raise ws.WorkspaceError('Native tab source report checksum/provenance mismatch.')
    return sections(report['markdown'])

def inspect_request(base,state,atomic_json):
    kind='doc_edit_inspect' if state.get('phase')=='revise_doc' else 'doc_tabs_inspect'
    return ws.request(base,state,kind,'get_document',{'document_id':state['workspace_document']['id']},{},atomic_json)

def start(base,state,atomic_json,readback=None):
    load(base,state)
    state['phase']='organize_doc';state.setdefault('workspace_policy',{})['native_doc_tabs']=1
    if readback is None:return inspect_request(base,state,atomic_json)
    return organize(base,state,readback,atomic_json)

def organize(base,state,data,atomic_json):
    source=load(base,state);tabs=data.get('tabs',[])
    if data.get('documentId')!=state['workspace_document']['id'] or not data.get('revisionId'):
        raise ws.WorkspaceError('Native tab document identity/revision mismatch.')
    if any(t.get('childTabs') for t in tabs):raise ws.WorkspaceError('Unexpected nested document tabs; no source replacement attempted.')
    guard={'requiredRevisionId':data['revisionId']};doc={'document_id':data['documentId'],'write_control':guard}
    if len(tabs)==1:
        if compact(text(body(tabs[0])))!=compact(''.join(expected(s) for s in source)):
            raise ws.WorkspaceError('Existing Doc differs from the complete verified report; no tab changes attempted.')
        return ws.request(base,state,'doc_tabs_add','batch_update_document',dict(doc,requests=[
            {'addDocumentTab':{'tabProperties':{'title':name,'index':i}}} for i,name in enumerate(TITLES[1:],1)]),{},atomic_json)
    if len(tabs)!=5 or [title(t) for t in tabs[1:]]!=TITLES[1:]:
        raise ws.WorkspaceError('Unexpected native tab names/order; no duplicate tabs will be created.')
    details=tabs[1:]
    if all(matches(t,s) for t,s in zip(tabs,source)) and [title(t) for t in tabs]==TITLES:
        state['native_doc_tabs']={'version':1,'source_sha256':ws.digest(source),'tab_ids':[tid(t) for t in tabs],'titles':TITLES}
        state['document_verified']=True;state['phase']='complete'
        return True
    original=compact(text(body(tabs[0])))==compact(''.join(expected(s) for s in source))
    if not original:raise ws.WorkspaceError('Original report changed before detailed tabs were verified.')
    if all(not text(body(t)).strip() and not tables(t) for t in details):
        requests=[]
        for tab,section in zip(details,source[1:]):
            args,_=native.document_replace_plan(wrapper(data,tab),section,section=True);requests+=args['requests']
        return ws.request(base,state,'doc_tabs_write','batch_update_document',dict(doc,requests=requests),{},atomic_json)
    if all(matches(t,s) for t,s in zip(details,source[1:])):
        # Keep the verified Overview verbatim; trim the original detailed tail
        # only after every copied paragraph and table has passed readback.
        content=body(tabs[0])['content']
        # Overview may repeat section names in H2/H3 summaries. Only the
        # verified top-level section sequence establishes the detailed tail.
        headings=[e for e in content if e.get('paragraph',{}).get('paragraphStyle',{}).get('namedStyleType')=='HEADING_1']
        if [text(e['paragraph']).strip() for e in headings]!=ws.REPORT_SECTIONS:
            raise ws.WorkspaceError('Original top-level report section boundaries differ from the verified source; no trimming attempted.')
        boundary=headings[1]['startIndex']
        end=max(e.get('endIndex',0) for e in content)-1;root=tid(tabs[0]);heading=next(e for e in content if 'paragraph'in e)
        requests=[{'deleteContentRange':{'range':{'tabId':root,'startIndex':boundary,'endIndex':end}}},
            {'updateDocumentTabProperties':{'tabProperties':{'tabId':root,'title':'Overview','index':0},'fields':'title,index'}},
            {'updateParagraphStyle':{'range':{'tabId':root,'startIndex':1,'endIndex':boundary},'paragraphStyle':{'pageBreakBefore':False,'keepWithNext':False,'spaceAbove':{'magnitude':0,'unit':'PT'},'spaceBelow':{'magnitude':6,'unit':'PT'},'lineSpacing':110},'fields':'pageBreakBefore,keepWithNext,spaceAbove,spaceBelow,lineSpacing'}},
            {'updateParagraphStyle':{'range':{'tabId':root,'startIndex':heading['startIndex'],'endIndex':heading['endIndex']-1},'paragraphStyle':{'namedStyleType':'TITLE','keepWithNext':True},'fields':'namedStyleType,keepWithNext'}},
            {'updateTextStyle':{'range':{'tabId':root,'startIndex':heading['startIndex'],'endIndex':heading['endIndex']-1},'textStyle':{'fontSize':{'magnitude':22,'unit':'PT'}},'fields':'fontSize'}}]
        return ws.request(base,state,'doc_tabs_finish','batch_update_document',dict(doc,requests=requests),{},atomic_json)
    # Recover an acknowledged or uncertain scaffold write without repeating it.
    requests=[]
    for tab,section in zip(details,source[1:]):
        parsed,_,source_tables=native.parse_markdown(section)
        scaffold=parsed
        for table in source_tables:scaffold=scaffold.replace(table['marker'],'')
        outside=''.join(text(e) for e in body(tab)['content'] if 'table'not in e)
        if compact(outside)!=compact(scaffold) or any(cell.strip() for table in tables(tab) for row in table for cell in row):
            raise ws.WorkspaceError('Detailed tab contains conflicting or partially edited content; original report retained.')
        requests+=native.table_fill_plan(wrapper(data,tab),source_tables)['requests']
    return ws.request(base,state,'doc_tabs_fill','batch_update_document',dict(doc,requests=requests),{},atomic_json)

def apply_response(base,state,pending,result,atomic_json):
    data=ws.unwrap(result);state.pop('workspace_pending',None)
    if pending['kind'].startswith('doc_edit_'):
        if pending['kind']=='doc_edit_inspect':return edit_readback(base,state,data,atomic_json)
        if data.get('documentId')!=state['workspace_document']['id']:raise ws.WorkspaceError('Editorial write identity mismatch.')
        return inspect_request(base,state,atomic_json)
    if pending['kind']=='doc_tabs_inspect':return organize(base,state,data,atomic_json)
    if data.get('documentId')!=state['workspace_document']['id']:raise ws.WorkspaceError('Native tab write identity mismatch.')
    return inspect_request(base,state,atomic_json)

def revise(base,state,markdown,data,atomic_json):
    """Register an editorial version and update the same five native tab IDs."""
    import semantic_synthesis
    semantic_synthesis.validate_report(markdown)
    current=load(base,state);native_tabs=data.get('tabs',[])
    if data.get('documentId')!=state['workspace_document']['id'] or [title(t) for t in native_tabs]!=TITLES or not all(matches(t,s) for t,s in zip(native_tabs,current)):
        raise ws.WorkspaceError('Existing native report differs from its verified editorial source.')
    payload={'markdown':markdown,'database_sha256':state['finalized_sheet_sha256'],'previous_sections':current}
    payload['sha256']=ws.digest(payload);path=base/'presentation'/'editorial'/('report_'+payload['sha256'][:16]+'.json')
    atomic_json(path,payload);state['editorial_report']={'path':str(path),'sha256':payload['sha256']}
    state['phase']='revise_doc';return edit_readback(base,state,data,atomic_json)

def edit_readback(base,state,data,atomic_json):
    source=load(base,state);native_tabs=data.get('tabs',[])
    if data.get('documentId')!=state['workspace_document']['id'] or not data.get('revisionId') or [title(t) for t in native_tabs]!=TITLES:
        raise ws.WorkspaceError('Editorial native tabs or revision differ from the expected document.')
    if all(matches(t,s) for t,s in zip(native_tabs,source)):
        state['native_doc_tabs']={'version':1,'source_sha256':ws.digest(source),'tab_ids':[tid(t) for t in native_tabs],'titles':TITLES}
        state['document_verified']=True;state['phase']='complete';return True
    previous=json.loads(Path(state['editorial_report']['path']).read_text())['previous_sections']
    requests=[];doc={'document_id':data['documentId'],'write_control':{'requiredRevisionId':data['revisionId']}}
    if all(matches(t,s) for t,s in zip(native_tabs,previous)):
        for tab,section in zip(native_tabs,source):
            requests+=native.document_replace_plan(wrapper(data,tab),section,section=True)[0]['requests']
        return ws.request(base,state,'doc_edit_write','batch_update_document',dict(doc,requests=requests),{},atomic_json)
    for tab,section in zip(native_tabs,source):
        if matches(tab,section):continue
        parsed,_,source_tables=native.parse_markdown(section);scaffold=parsed
        for table in source_tables:scaffold=scaffold.replace(table['marker'],'')
        outside=''.join(text(e) for e in body(tab)['content'] if 'table'not in e)
        if compact(outside)!=compact(scaffold) or any(cell.strip() for table in tables(tab) for row in table for cell in row):
            raise ws.WorkspaceError('Editorial native contents conflict; no repeated destructive write attempted.')
        requests+=native.table_fill_plan(wrapper(data,tab),source_tables)['requests']
    return ws.request(base,state,'doc_edit_fill','batch_update_document',dict(doc,requests=requests),{},atomic_json)
