"""Reusable evidence and deterministic progressive coverage; no network access."""
from __future__ import annotations
import hashlib
import json
import re
from urllib.parse import urlsplit, urlunsplit

POLICY = {'version':2, 'review_batch_size':20, 'discovery_batch_size':100, 'max_source_attempts':60, 'max_execution_seconds':1200,
          'max_context_bytes':180000,
          'coverage':'round-robin approved providers; all relevant accessible cases; no quotas or saturation stopping'}

def canonical(url):
    p=urlsplit(url)
    if p.scheme not in ('https','http') or not p.netloc:raise ValueError('Invalid evidence URL')
    return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',p.query,''))

def read(path,default):return json.loads(path.read_text()) if path.exists() else default

def url_provenance(capture):
    result={k:capture[k] for k in ('url','resolved_url','resolved_url_evidence','canonical_url','canonical_url_evidence') if k in capture}
    # Historical Wingify receipts explicitly recorded this sentence before the
    # structured redirect fields existed. Accept that precise observation only;
    # a generic URL mention or a destination hint is never an alias.
    match=re.match(r'^Redirected to (https?://[^\s]+)',capture.get('text',''))
    if match and not result.get('resolved_url'):
        result.update(resolved_url=match[1].rstrip('.,'),resolved_url_evidence=match[0])
    return result


def capture_urls(capture):
    """Only explicitly witnessed redirect/canonical edges establish aliases."""
    provenance=url_provenance(capture);urls={canonical(capture['url'])}
    for field in ('resolved_url','canonical_url'):
        value=provenance.get(field);evidence=provenance.get(field+'_evidence')
        if value and isinstance(evidence,str) and evidence.strip():urls.add(canonical(value))
    return urls


def captures_for(base, provider, url=None):
    data=read(base/'research/memory.json',{})
    refs=data.get('sources',{})
    wanted=canonical(url) if url else None
    keys=[wanted] if wanted else refs
    if wanted and not refs.get(wanted):
        # Old memory indexes used only requested URLs. Reuse explicit saved
        # listing redirects without rewriting history or calling a worker.
        keys=[wanted]+data.get('inventory_sources',{}).get(provider,[])
    seen=set()
    for key in keys:
        for fp in reversed(refs.get(key,[])):
            if fp in seen:continue
            seen.add(fp);capture=read(base/'research/captures'/f'{fp}.json',{})
            if capture.get('provider')==provider and (not wanted or wanted in capture_urls(capture)):yield capture

def remember(base,atomic_json,*,capture=None,event=None,provider='',origin=''):
    path=base/'research'/'memory.json';data=read(path,{'sources':{},'searches':{},'failures':{},'imported_logs':[]})
    previous=json.dumps(data,sort_keys=True) if path.exists() else None
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
        saved=dict(capture,**url_provenance(capture));saved.update(url=url,provider=provider,origin=origin)
        aliases=capture_urls(saved)
        fingerprint=hashlib.sha256(json.dumps(saved,sort_keys=True).encode()).hexdigest()
        target=base/'research'/'captures'/f'{fingerprint}.json'
        if not target.exists():atomic_json(target,saved)
        for alias in aliases:
            refs=data['sources'].setdefault(alias,[])
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
    if json.dumps(data,sort_keys=True)!=previous:atomic_json(path,data)

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

def listing_work(state,provider,ledger,records):
    """Authoritative derived slot lifecycle; never persist a competing work queue.

    Entries supply validated URL associations, screening supplies decisions, and
    immutable records supply extraction completion. Observed-only slots still
    need case checkpoints. Listing completion is a separate scope.
    """
    universe=state.get('listing_universes',{}).get(provider,{})
    entries={r['listing_position']:r for r in universe.get('entries',[])}
    observed={r['position']:r for r in universe.get('observed_slots',[])}
    positions=set(entries)|set(observed)
    work=[]
    for position in sorted(positions):
        row=entries.get(position)
        cid=row.get('source_case_id',row['id']) if row and row.get('url') else None
        decision=ledger.get(cid,{})
        record=records.get(cid)
        if row is None:
            slot=observed[position]
            row={'provider':provider,'listing_position':position,'listing_url':slot['listing_url'],'title':slot['title'],
                 'customer':'Unknown','url':None,'url_status':'unresolved',
                 'reason':'Witnessed listing position lacks a case checkpoint.',
                 'evidence':'Saved ordered listing capture witnesses title: '+slot['title']}
            status='checkpoint_pending'
        elif not row.get('url'):
            legacy=state.get('url_recovery',{}).get('results',{}).get(provider+':'+str(position))
            status='terminal_unresolved' if row.get('resolution_outcome') or legacy else 'url_pending'
        elif record:status='extracted' if record['status']=='complete' else 'inaccessible'
        elif decision.get('decision') in ('excluded','unresolved'):status=decision['decision']
        elif decision.get('decision')=='relevant':status='extraction_pending'
        else:status='relevance_pending'
        work.append({'position':position,'entry':row,'case_id':cid,'status':status,
                     'case':decision or (dict(row,id=cid) if cid else row)})
    return work


def coverage(state,inventory,ledger,records,progress):
    rows=[]
    for order,p in enumerate(state['approved_providers']):
        complete=[r for r in records.values() if r['provider']==p and r['status']=='complete']
        cases=[c for c in ledger.values() if c['provider']==p]
        pending=[c for c in cases if c['decision']=='needs_review' and c['id'] not in records]
        # Legacy inventories may predate the screening ledger.
        # Clearly relevant cases wait for Stage 3, without a redundant review.
        done=p in inventory and (p not in progress or progress[p].get('complete',False))
        universe=state.get('listing_universes',{}).get(p,{})
        if state.get('research_policy',{}).get('first_listing_entries'):
            selected={c.get('source_case_id',c['id']) for c in universe.get('entries',[]) if c.get('url')}
            done=bool(universe.get('complete'))
            work=listing_work(state,p,ledger,records)
            # Relevant metadata needs extraction too; it must not disappear
            # merely because enumeration has closed.
            pending=list({w['case_id']:w['case'] for w in work if w['status'] in ('relevance_pending','extraction_pending')}.values()) if done else []
            resolution=[w['entry'] for w in work if w['status']=='url_pending' or done and w['status']=='checkpoint_pending']
        customers={r['customer'].strip().casefold() for r in complete}
        rows.append({'provider':p,'complete_records':len(complete),'distinct_customers':len(customers),
                     'inaccessible_records':sum(r['provider']==p and r['status']=='inaccessible' for r in records.values()),
                     'screening_counts':{d:sum(c['decision']==d for c in cases) for d in ('relevant','excluded','needs_review','unresolved')},
                     'discovered':len(cases) or len(inventory.get(p,[])),'pending':pending,'inventory_complete':done,
                     'order':order,'last_selected':state.get('coverage_turns',{}).get(p,0)})
        if state.get('research_policy',{}).get('first_listing_entries'):
            rows[-1].update(resolution_pending=resolution,listing_entries=len(universe.get('entries',[])),listing_order_verified=bool(universe.get('order_verified')),
                           unresolved_listing_urls=sum(not c.get('url') for c in universe.get('entries',[])),
                           content_confirmed_urls=sum(c.get('url_status')=='content_confirmed' for c in universe.get('entries',[])),
                           verified_listing_hrefs=sum(bool(c.get('url')) and c.get('url_status')!='content_confirmed' for c in universe.get('entries',[])),
                           listing_coverage_status=universe.get('coverage_status',''),continuation_limitation=universe.get('continuation_limitation',''),
                           listing_access_status=universe.get('listing_access_status',''),listing_story_count=universe.get('listing_story_count'),
                           listing_access_evidence=universe.get('listing_access_evidence'),
                           retained_completed_outside_boundary=sum(r['id'] not in selected for r in complete))
    return rows

def plan(state,inventory,ledger,records,progress):
    rows=coverage(state,inventory,ledger,records,progress)
    eligible=[r for r in rows if r['pending'] or r.get('resolution_pending') or not r['inventory_complete']]
    # Published volume and repeated themes must not affect collection eligibility
    # or priority. Rotate providers; completeness, not saturation, ends the work.
    eligible.sort(key=lambda r:(r['last_selected'],r['order']))
    if not eligible:return {'action':'done','coverage':rows}
    row=eligible[0]
    if row['inventory_complete'] and row.get('resolution_pending'):
        return {'action':'resolve_urls','provider':row['provider'],
                'cases':row['resolution_pending'][:state['research_policy']['review_batch_size']],
                'coverage':rows}
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


def eligible_inventory(state,inventory,records):
    """Preserve every saved extraction; only selected unfinished cases can run."""
    if not state.get('research_policy',{}).get('first_listing_entries'):return inventory
    selected={c.get('source_case_id',c['id']) for u in state.get('listing_universes',{}).values() for c in u.get('entries',[]) if c.get('url')}
    active={p:[c for c in cases if c['id'] in selected or c['id'] in records] for p,cases in inventory.items()}
    for cid,r in records.items():
        cases=active.setdefault(r['provider'],[])
        if not any(c['id']==cid for c in cases):
            cases.append({'id':cid,'provider':r['provider'],'url':r['source_url'],'customer':r['customer'],'title':'Preserved completed source'})
    return active


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
        assignment={'review_cases':proposed,'evidence_memory':context(base,proposed)}
        size=len(json.dumps(model_context(assignment),ensure_ascii=False).encode())
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


def assignment_urls(assignment):
    """URLs useful to this worker; broad validation history stays in Python."""
    cases=assignment.get('review_cases',assignment.get('assigned_cases',[]))
    urls={c['url'] for c in cases}
    for slot in assignment.get('recovery_slots',[]):
        urls.add(slot['listing_url'])
        if slot.get('url'):urls.add(slot['url'])
    for values in assignment.get('saved_candidate_urls',{}).values():
        urls.update(v['url'] for v in values)
    return urls


def assignment_memory(base,assignment):
    cases=assignment.get('review_cases',assignment.get('assigned_cases',[]))
    provider=assignment.get('approved_provider','')
    urls=assignment_urls(assignment)
    # Known-source assignments must not inherit inventory history. Recovery needs
    # its original listing and candidate pages, not the provider's other archives.
    if cases or assignment.get('url_recovery'):
        providers={c['url']:c['provider'] for c in cases}
        assigned=[{'url':url,'provider':providers.get(url,provider)} for url in sorted(urls)]
        return context(base,assigned,provider if assigned else '')
    return context(base,provider=provider)


def model_context(assignment):
    """Pure model-facing projection, also usable on historical saved prompts.

    Never modifies runtime context: full slot proofs, source IDs, failure maps,
    receipts and extraction records remain available to existing validators.
    No model call or guessed semantic summary is used to construct this view.
    """
    out={k:v for k,v in assignment.items() if not k.startswith('_')}
    product=out.pop('product_understanding',None)
    if product:
        boundary={'workflow':product['core_workflow'],
                  'capabilities':[c['name'] for c in product.get('capabilities',[])],
                  'uncertainties':product.get('uncertainties',[])}
        # Researching the target itself requires its full capability breadth.
        if out.get('approved_provider','').casefold()==out.get('target','').casefold() or not (
                out.get('competing_product') or out.get('competing_products')):
            boundary['summary']=product['summary']
            boundary['capabilities']=[{k:c[k] for k in ('name','description')} for c in product.get('capabilities',[])]
        out['target_scope']=boundary
    out.pop('pdf_access_policy',None)  # One authoritative common instruction.
    cases=out.get('review_cases',out.get('assigned_cases',[]))
    if cases:
        scopes=dict(out.get('competing_products',{}))
        for c in cases:
            if c.get('competing_product'):scopes[c['provider']]=c['competing_product']
        scopes={p:scopes[p] for p in dict.fromkeys(c['provider'] for c in cases) if p in scopes}
        if scopes:
            out['competing_products']=scopes
            out.pop('competing_product',None)
        field='review_cases' if 'review_cases' in out else 'assigned_cases'
        fields=('id','provider','url','customer','title','decision','reason','evidence','saved_record')
        out[field]=[{k:c[k] for k in fields if k in c} for c in cases]
    urls=assignment_urls(assignment)
    urls.update(assignment.get('listing_sources',[]))
    hosts={urlsplit(url).hostname for url in urls}
    scope=assignment.get('competing_product',{})
    if isinstance(scope,dict):hosts.update(urlsplit(u).hostname for u in scope.get('sources',[]))

    def useful_url(url):
        return url in urls or urlsplit(url).hostname in hosts

    records=out.pop('completed_provider_records',[])
    completed={r['source_url']:{'id':r.get('id'),'url':r['source_url'],'customer':r['customer']}
               for r in records}
    for url in out.pop('completed_case_urls',[]):
        if not assignment.get('url_recovery') or useful_url(url):completed.setdefault(url,{'url':url})
    known=list(dict.fromkeys(out.get('known_case_urls',[])))
    if assignment.get('url_recovery'):
        # Recovery builders historically supplied identical global URL arrays.
        for url in known:
            if useful_url(url):completed.setdefault(url,{'url':url})
        out.pop('known_case_urls',None)
    elif known:
        out['known_case_urls']=[u for u in known if u not in completed]
    if completed:out['completed_sources']=list(completed.values())
    if assignment.get('url_recovery'):
        fields=('listing_position','listing_url','title','customer','url','evidence')
        out['recovery_slots']=[{k:r[k] for k in fields if k in r} for r in assignment['recovery_slots']]
        out.pop('selected_listing_entries',None)
        out.pop('observed_listing_slots',None)
    elif 'selected_listing_entries' in out:
        fields=('listing_position','title','url','listing_card_id')
        out['selected_listing_entries']=[{k:r[k] for k in fields if k in r} for r in out['selected_listing_entries']]
        positions={r['listing_position'] for r in out['selected_listing_entries']}
        out['observed_listing_slots']=[r for r in out.get('observed_listing_slots',[]) if r['position'] not in positions]
    if cases:
        for key in ('selected_listing_entries','observed_listing_slots','listing_sources','known_case_urls','completed_sources'):
            out.pop(key,None)
    memory=out.get('evidence_memory')
    if memory:
        memory=dict(memory)
        sources=dict(memory.get('sources',{}))
        known_assignment=bool(cases or assignment.get('url_recovery'))
        if known_assignment:sources={u:c for u,c in sources.items() if u in urls}
        if assignment.get('url_recovery'):
            positions={r['listing_position'] for r in assignment['recovery_slots']}
            for url,capture in list(sources.items()):
                if capture.get('role')!='listing':continue
                capture=dict(capture)
                # The full frozen order is a validator input, not another model
                # assignment. Keep readable evidence and any useful saved hrefs.
                hrefs=[r for r in capture.pop('ordered_entries',[]) if r.get('position') in positions and r.get('url')]
                if hrefs:capture['ordered_entries']=hrefs
                capture.pop('continuation',None)
                sources[url]=capture
        candidate_captures=out.get('saved_candidate_captures',{})
        candidate_captures={u:v for u,v in candidate_captures.items() if u in urls and v}
        # Keep association-bearing captures intact, once, rather than duplicating
        # them as both generic evidence memory and candidate capture bodies.
        for url in candidate_captures:sources.pop(url,None)
        if 'saved_candidate_captures' in out:out['saved_candidate_captures']=candidate_captures
        memory['sources']=sources
        failures=memory.get('known_access_failures',{})
        source_text='\n'.join(json.dumps(v,ensure_ascii=False) for v in sources.values())
        source_text+='\n'+json.dumps(candidate_captures,ensure_ascii=False)
        memory['known_access_failures']={u:reason for u,reason in failures.items()
                                        if useful_url(u) or u in source_text}
        searches=memory.get('completed_searches',{})
        # Known-URL review/extraction has no need for prior discovery searches.
        # Recovery candidates already carry the useful saved search results.
        memory['completed_searches']={} if known_assignment else searches
        memory.pop('rules',None)  # Common quality instructions carry this contract.
        out['evidence_memory']=memory
    return out
