"""Reusable evidence and deterministic progressive coverage; no network access."""
from __future__ import annotations
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit

POLICY = {'version':2, 'review_batch_size':20, 'discovery_batch_size':100, 'max_source_attempts':60, 'max_execution_seconds':1200,
          'max_context_bytes':180000,
          'coverage':'round-robin approved providers; all relevant accessible cases; no quotas or saturation stopping'}

def canonical(url):
    p=urlsplit(url)
    if p.scheme not in ('https','http') or not p.netloc:raise ValueError('Invalid evidence URL')
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',p.query,''))

def read(path,default):return json.loads(path.read_text()) if path.exists() else default

def remember(base,atomic_json,*,capture=None,event=None,provider='',origin=''):
    path=base/'research'/'memory.json';data=read(path,{'sources':{},'searches':{},'failures':{},'imported_logs':[]})
    if 'access_failures' not in data:data['access_failures']=failed_sources(base)
    data.setdefault('inventory_sources',{})
    if capture is not None:
        if not isinstance(capture,dict) or capture.get('coverage') not in ('full_text','excerpt','summary','metadata','failed') or not isinstance(capture.get('text'),str):
            raise ValueError('Invalid source capture')
        url=canonical(capture['url']);text=capture['text']
        if capture['coverage']=='failed':data['access_failures'][url]=text
        if capture.get('role')=='listing' or capture['coverage']=='metadata':
            recent=data['inventory_sources'].setdefault(provider,[])
            if url not in recent:recent.append(url)
        if len(text)>100000:raise ValueError('Source capture exceeds bounded evidence size')
        saved=dict(capture,url=url,provider=provider,origin=origin)
        fingerprint=hashlib.sha256(json.dumps(saved,sort_keys=True).encode()).hexdigest()
        target=base/'research'/'captures'/f'{fingerprint}.json'
        if not target.exists():atomic_json(target,saved)
        refs=data['sources'].setdefault(url,[])
        if fingerprint not in refs:refs.append(fingerprint)
    if event:
        item=event.get('item',{});ty=item.get('type');serialized=json.dumps(item.get('result',{}))
        if ty=='mcp_tool_call' and any(t in serialized for t in ('Browser is not available','not approved to use','"text": "[]"')):
            data['failures']['browser']='Browser access unavailable in these workers. Do not probe browsers again; use web search or saved evidence.'
        if ty=='command_execution' and any(t in item.get('aggregated_output','') for t in ('urlopen error','nodename nor servname','Name or service not known')):
            data['failures']['shell_network']='Shell networking failed in this environment. Do not retry curl/urllib or other shell network probes.'
        if ty=='web_search':
            action=item.get('action',{});results=item.get('results',[])
            for q in action.get('queries') or ([action['query']] if action.get('query') else []):
                data['searches'][q]={'provider':provider,'results':[{k:r[k] for k in ('url','title','snippet') if k in r} for r in results[:20] if isinstance(r,dict)],'origin':origin}
            for r in results:
                if not isinstance(r,dict) or not r.get('url') or 'Total lines:' not in r.get('snippet',''):continue
                # CLI telemetry contains metadata, not the article body. Never pass it off as full text.
                url=canonical(r['url']);failed=r.get('title')=='Internal Error'
                entry={'url':url,'coverage':'failed' if failed else 'metadata','text':r.get('title','')+' '+r.get('snippet',''),
                       'provider':provider,'origin':origin}
                if failed:data['access_failures'][url]=entry['text']
                fp=hashlib.sha256(json.dumps(entry,sort_keys=True).encode()).hexdigest()
                atomic_json(base/'research'/'captures'/f'{fp}.json',entry)
                refs=data['sources'].setdefault(url,[])
                if fp not in refs:refs.append(fp)
    atomic_json(path,data)

def import_saved(base,atomic_json,ledger):
    """One-time telemetry import, retaining original logs byte-for-byte."""
    path=base/'research'/'memory.json';data=read(path,{'sources':{},'searches':{},'failures':{},'imported_logs':[]})
    done=set(data['imported_logs'])
    for f in sorted((base/'logs').glob('*.jsonl')):
        if f.name in done:continue
        prompt=f.with_suffix('.prompt.txt');provider=''
        if prompt.exists():
            try:
                ctx=json.JSONDecoder().raw_decode(prompt.read_text().split('TASK ASSIGNMENT (machine generated):',1)[1].lstrip())[0]
                provider=ctx.get('approved_provider') or ctx.get('review_case',{}).get('provider','')
            except (ValueError,IndexError):pass
        for line in f.read_text().splitlines():
            try:e=json.loads(line)
            except ValueError:continue
            if e.get('type')=='item.completed':remember(base,atomic_json,event=e,provider=provider,origin=f.name)
        data=read(path,data);data['imported_logs'].append(f.name);atomic_json(path,data)
    for case in ledger.values():
        remember(base,atomic_json,capture={'url':case['url'],'coverage':'failed' if case['decision']=='unresolved' else 'summary',
                 'text':case.get('evidence','')},provider=case['provider'],origin='saved_screening')

def context(base,cases=(),provider=''):
    data=read(base/'research'/'memory.json',{'sources':{},'searches':{},'failures':{}})
    sources={};urls=[c['url'] for c in cases]
    access_failures=failed_sources(base)
    # Only inventory gets listing/search history; deep work gets assigned evidence.
    if provider and not cases:
        urls += data.get('inventory_sources',{}).get(provider,[])[-4:]
    for url in dict.fromkeys(urls):
        refs=data['sources'].get(canonical(url),[]);entries=[read(base/'research'/'captures'/f'{fp}.json',{}) for fp in refs]
        entries.sort(key=lambda c: {'full_text':0,'excerpt':1,'summary':2,'failed':3,'metadata':4}.get(c.get('coverage'),5))
        if entries:
            entry=entries[0];sources[url]=dict(entry)
            if not cases and len(entry.get('text',''))>12000:
                sources[url].update(text=entry['text'][:12000],coverage='excerpt')
            failures=[x for x in entries if x.get('coverage')=='failed']
            if failures:sources[url]['access_failure']=failures[-1]['text']
    searches={q:v for q,v in data['searches'].items() if v.get('provider')==provider} if provider and not cases else {}
    compact_searches={q:dict(v,results=v['results'][:3]) for q,v in list(searches.items())[-20:]}
    return {'sources':sources,'completed_searches':compact_searches,'known_tool_failures':data['failures'],'known_access_failures':access_failures,
            'rules':'Reuse saved evidence first. Metadata is not article text. Do not repeat failed PDF access, completed searches, or unavailable tool probes. Emit faithful source_capture messages for new usable evidence.'}

def coverage(state,inventory,ledger,records,progress):
    rows=[]
    for order,p in enumerate(state['approved_providers']):
        complete=[r for r in records.values() if r['provider']==p and r['status']=='complete']
        cases=[c for c in ledger.values() if c['provider']==p]
        pending=[c for c in cases if c['decision']=='needs_review' and c['id'] not in records]
        # Legacy inventories may predate the screening ledger.
        # Clearly relevant cases wait for Stage 3, without a redundant review.
        done=p in inventory and (p not in progress or progress[p].get('complete',False))
        customers={r['customer'].strip().casefold() for r in complete}
        rows.append({'provider':p,'complete_records':len(complete),'distinct_customers':len(customers),
                     'inaccessible_records':sum(r['provider']==p and r['status']=='inaccessible' for r in records.values()),
                     'screening_counts':{d:sum(c['decision']==d for c in cases) for d in ('relevant','excluded','needs_review','unresolved')},
                     'discovered':len(cases) or len(inventory.get(p,[])),'pending':pending,'inventory_complete':done,
                     'order':order,'last_selected':state.get('coverage_turns',{}).get(p,0)})
    return rows

def plan(state,inventory,ledger,records,progress):
    rows=coverage(state,inventory,ledger,records,progress)
    eligible=[r for r in rows if r['pending'] or not r['inventory_complete']]
    # Published volume and repeated themes must not affect collection eligibility
    # or priority. Rotate providers; completeness, not saturation, ends the work.
    eligible.sort(key=lambda r:(r['last_selected'],r['order']))
    if not eligible:return {'action':'done','coverage':rows}
    row=eligible[0]
    selected=[]
    if row['pending']:
        peers=[r for r in eligible if r['pending']]
        offsets={r['provider']:0 for r in peers}
        while len(selected)<state['research_policy']['review_batch_size']:
            added=False
            for peer in peers:
                offset=offsets[peer['provider']]
                if offset<len(peer['pending']):
                    selected.append(peer['pending'][offset]);offsets[peer['provider']]+=1;added=True
                    if len(selected)==state['research_policy']['review_batch_size']:break
            if not added:break
    return {'action':'review_batch' if row['pending'] else 'discover','provider':row['provider'],
            'cases':selected,
            'max_cases':state['research_policy']['discovery_batch_size'],'coverage':rows}


def failed_sources(base):
    """Durable URL failures, including URLs discovered under another provider."""
    data=read(base/'research'/'memory.json',{'sources':{}})
    if 'access_failures' in data:return dict(data['access_failures'])
    # Compatibility with old memory files; imported evidence populates the index.
    return {url:c['text'] for url,refs in data['sources'].items() for fp in refs
            for c in [read(base/'research'/'captures'/f'{fp}.json',{})] if c.get('coverage')=='failed'}


def bounded_cases(cases,settings):
    batch=[];size=0
    for case in cases:
        n=len(json.dumps(case,ensure_ascii=False).encode())
        if n>settings['max_context_bytes']:raise ValueError('One case exceeds research context budget; no truncation.')
        if batch and size+n>settings['max_context_bytes']:break
        batch.append(case);size+=n
    return batch


def assignment_cases(base,cases,settings):
    """Bound actual case+capture bytes, without truncating successful captures."""
    batch=[]
    for case in cases:
        proposed=batch+[case]
        size=len(json.dumps({'cases':proposed,'evidence':context(base,proposed)},ensure_ascii=False).encode())
        if size>settings['max_context_bytes']-12000:
            if not batch:raise ValueError('One case and saved evidence exceed context budget; increase max-context-bytes. No evidence truncated.')
            break
        batch=proposed
    return batch


def inventory_window(urls,settings):
    """Recent URL metadata only; Python retains complete duplicate protection."""
    chosen=[];size=0;budget=settings['max_context_bytes']//4
    for url in reversed(urls):
        n=len(json.dumps(url).encode())
        if size+n>budget or len(chosen)>=2*settings['discovery_batch_size']:break
        chosen.append(url);size+=n
    return list(reversed(chosen))
