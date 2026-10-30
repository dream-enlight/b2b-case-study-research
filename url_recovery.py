"""Bounded, local-only recovery of already witnessed listing slots."""
import copy
import json
import re
from pathlib import Path
from urllib.parse import urlsplit,unquote
import research
import workspace


def normalized(text):
    return re.sub(r'\W+',' ',text.casefold()).strip()


def saved_association(api,base,provider,row):
    """Join an actual saved page heading to its saved readable excerpt."""
    sources=list(research.captures_for(base,provider,row['url']))
    slug=normalized(unquote(urlsplit(row['url']).path.rstrip('/').rsplit('/',1)[-1]))
    heading=next((c for c in sources if c.get('coverage')=='metadata' and
        (normalized(row['title']) in normalized(c.get('text','')) or
         slug==normalized(row['title']) and len(normalized(row['customer']))>=6 and
         normalized(row['customer']) in normalized(c.get('text','')))),None)
    if heading is None:return
    for source in sources:
        if source.get('coverage') not in ('excerpt','full_text') or source.get('listing_association'):continue
        text=source['text'];customer=row['customer']
        if row['title'] not in text and not (customer.casefold() not in ('','unknown','not identified','not established') and
            customer.casefold() in row['title'].casefold() and customer.casefold() in text.casefold()):
            page_heading=heading['text'].split(' Total lines:',1)[0]
            text+='\nSaved source page heading: '+page_heading
            source=dict(source,text=text)
        derived=dict(source,listing_association={'listing_url':row['listing_url'],'position':row['listing_position'],
            'title':row['title'],'quote':text},association_provenance={
            'source_sha256':workspace.digest(source),'heading_sha256':workspace.digest(heading)})
        research.remember(base,api.atomic_json,provider=provider,capture=derived,origin='saved_heading_excerpt_association')
        return


def candidates(base,state):
    """Saved URLs are candidates, never automatically asserted associations."""
    result={};slots=[(p,r) for p,u in state['listing_universes'].items() for r in u['entries'] if r.get('url') is None]
    sources=[]
    memory=research.read(base/'research/memory.json',{})
    for search in memory.get('searches',{}).values():
        sources.extend((source,search.get('origin','saved_search')) for source in search.get('results',[]))
    for log in sorted((base/'logs').glob('*.jsonl')):
        for line in log.read_text().splitlines():
            try:event=json.loads(line)
            except ValueError:continue
            item=event.get('item',{})
            if event.get('type')=='item.completed' and item.get('type')=='web_search':
                sources.extend((source,log.name) for source in item.get('results',[]))
    for source,origin in sources:
        title=normalized(source.get('title',''));url=source.get('url','')
        if not url.startswith(('http://','https://')):continue
        for provider,row in slots:
            host=(urlsplit(url).hostname or '').removeprefix('www.')
            root=(urlsplit(row['listing_url']).hostname or '').removeprefix('www.')
            if host!=root and not host.endswith('.'+root):continue
            name=normalized(row['title'])
            exact=name in title and len(name)>=13
            named=len(name)>=6 and normalized(row['customer'])==name and re.search(r'\b'+re.escape(name)+r'\b',title)
            if not (exact or named):continue
            key=provider+':'+str(row['listing_position'])
            value={'url':url,'title':source.get('title',''),'evidence':source.get('snippet',''),'origin':origin}
            entries=result.setdefault(key,[])
            if not any(v['url']==url for v in entries):entries.append(value)
    return result


def start(api,args):
    with api.locked(args.id) as base:
        state=api.read_state(base)
        if state.get('url_recovery'):
            print('URL recovery already initialized; use run to continue.');return
        if state['phase']!='complete' or state.get('workspace_pending'):
            raise api.RunError('URL recovery requires the verified completed run without pending Workspace actions.')
        records=api.read_json(base/'extracted.json')
        baseline={p:{'unresolved_before':sum(r.get('url') is None for r in u['entries']),
            'slots':[copy.deepcopy(r) for r in u['entries'] if r.get('url') is None]}
            for p,u in state['listing_universes'].items()}
        state['url_recovery']={'version':1,'status':'active','backup':api.backup_run(base,'before_url_recovery'),
            'baseline':baseline,'original_records':{cid:workspace.digest(r) for cid,r in records.items()},
            'published_sheet':copy.deepcopy(state['workspace_sheet']),'published_document':state.get('document_url'),
            'turns':{},'results':{},'saved_candidates':candidates(base,state)}
        state['phase']='url_recovery';api.save(base,state)
        print('Local-only URL recovery initialized; published outputs and analysis held unchanged.')


def checkpoint(api,base,state,key,context,row):
    position=row['listing_position'];provider=context['approved_provider']
    if context.get('ordinary_resolution'):
        # Enumeration's unresolved metadata is not a terminal research result.
        # Only an assigned bounded resolution receipt can close this slot.
        receipt={'position':position,'task':key,'row':copy.deepcopy(row)}
        path=base/'research'/'url_resolution'/(key+'_'+str(position)+'.json')
        if path.exists() and api.read_json(path)!=receipt:
            raise api.RunError('URL resolution receipt is immutable.','validation')
        api.atomic_json(path,receipt)
        entry=next(r for r in state['listing_universes'][provider]['entries'] if r['listing_position']==position)
        entry['resolution_outcome']={'receipt':str(path),'decision':row['decision'],
                                     'reason':row['reason'],'evidence':row['evidence']}
        api.save(base,state)
        return
    state['url_recovery']['results'][provider+':'+str(position)]={
        'position':position,'url':row.get('url'),'decision':row['decision'],
        'reason':row['reason'],'task':key,'row':copy.deepcopy(row)}
    api.save(base,state)


def publish(api,args):
    """Explicit publication handoff; retain the old dataset and native IDs."""
    import document_tabs
    import finish_collected
    with api.locked(args.id) as base:
        state=api.read_state(base)
        if state.get('recovered_publication'):
            print('Recovered dataset already handed to normal finalization.');return
        if state['phase']!='url_recovery_complete' or state.get('workspace_pending'):
            raise api.RunError('Finish URL recovery and pending Workspace actions before publication.')
        records=finish_collected.validate_saved(api,base,state)
        ledger=api.read_json(api.screening_path(base))
        if any(c['decision'] in ('relevant','needs_review') and c['id'] not in records for c in ledger.values()):
            raise api.RunError('Recovered cases still require screening or extraction.')
        if any(r['pending_slots'] for r in progress(api,base,state)):
            raise api.RunError('URL recovery still has unaccounted slots.')
        backup=api.backup_run(base,'before_recovered_dataset_publication')
        previous=document_tabs.display_sections(state,document_tabs.load(base,state))
        revision='recovered_'+workspace.digest(records)[:16]
        archive=base/'revisions'/revision/'previous_dataset'
        for name in ['batches.json','case_studies.csv','final_snapshot.json','finalized_sheet.json','report.json','report.md','report.html','report_expected.json']+[f'analysis_{n}.{ext}' for n in range(4,8) for ext in ('json','md')]:
            path=base/name
            if path.exists():
                archive.mkdir(parents=True,exist_ok=True);path.rename(archive/name)
        inventory=api.read_json(api.inventory_path(base))
        api.atomic_json(base/'batches.json',api.compile_batches(inventory))
        if {c['id'] for b in api.read_json(base/'batches.json') for c in b['cases']}!=set(records):
            raise api.RunError('Recovered relevant inventory and extraction coverage differ.')
        state['recovered_publication']={'backup':backup,'previous_sections':previous,'revision':revision}
        state['dataset_revision']=revision
        state['screening_summary']={'relevant':sum(c['decision']=='relevant' for c in ledger.values()),
            'excluded':sum(c['decision']=='excluded' for c in ledger.values()),
            'unresolved':sum(c['decision']=='unresolved' for c in ledger.values()),
            'providers':[{k:v for k,v in row.items() if k not in ('pending','order','last_selected')}
                         for row in api.coverage_plan(base,state)['coverage']],
            'url_recovery':progress(api,base,state),
            'disclosure':'Bounded URL recovery completed for all witnessed slots. Inaccessible listings, incomplete listing coverage, unresolved associations and failed sources remain explicit limitations; no replacement entries were collected.'}
        for key in ('workspace_finalize_offset','finalized_sheet_sha256','workspace_publication_only','editorial_report'):
            state.pop(key,None)
        state['document_verified']=False;state['phase']='stage3';api.save(base,state)
        print('Recovered dataset handed to normal Sheet finalization and full-dataset analysis; existing native IDs retained.')


def progress(api,base,state):
    records=api.read_json(base/'extracted.json');recovery=state['url_recovery']
    events=[json.loads(line) for line in (base/'performance.jsonl').read_text().splitlines()]
    rows=[]
    for provider in state['approved_providers']:
        before=recovery['baseline'][provider]['unresolved_before']
        remaining=sum(r.get('url') is None for r in state['listing_universes'][provider]['entries'])
        results=[v for k,v in recovery['results'].items() if k.startswith(provider+':')]
        prefix='url_recovery_'+api.slugify(provider)+'_'
        review_keys={k for k,p in recovery.get('review_jobs',{}).items() if p==provider}
        executions=sum(j['attempts'] for k,j in state['jobs'].items() if k.startswith(prefix) or k in review_keys)
        metered=[e for e in events if e.get('kind')=='execution' and (e.get('key','').startswith(prefix) or e.get('key') in review_keys) and e.get('input_tokens') is not None]
        universe=state['listing_universes'][provider]
        incomplete=(remaining>0 or any(v['decision']=='unresolved' for v in results) or
            universe.get('listing_access_status')=='inaccessible' or
            universe.get('coverage_status')=='incomplete' and len(universe['entries'])<30)
        rows.append({'provider':provider,'unresolved_before':before,'unresolved_after':remaining,'urls_recovered':before-remaining,
            'new_completed_cases':sum(r['provider']==provider and cid not in recovery['original_records'] and r['status']=='complete' for cid,r in records.items()),
            'attempted_slots':len(results),'pending_slots':before-len(results),'coverage_status':'incomplete' if incomplete else 'resolved',
            'model_executions':executions,'unmetered_executions':executions-len(metered),
            'input_tokens_metered':sum(e['input_tokens'] for e in metered),'cached_input_tokens_metered':sum(e.get('cached_input_tokens') or 0 for e in metered),
            'output_tokens_metered':sum(e.get('output_tokens') or 0 for e in metered)})
    return rows


def step(api,base,state,timeout,cli):
    recovery=state['url_recovery'];records=api.read_json(base/'extracted.json')
    recovery['saved_candidates']=candidates(base,state)
    for cid,checksum in recovery['original_records'].items():
        if cid not in records or workspace.digest(records[cid])!=checksum:
            raise api.RunError('An original completed record changed during URL recovery.','validation')
    if state['workspace_sheet']!=recovery['published_sheet'] or state.get('document_url')!=recovery['published_document']:
        raise api.RunError('Published output identity changed during local-only recovery.','validation')
    ledger=api.read_json(api.screening_path(base))
    pending=[c for c in ledger.values() if c.get('discovery_key','').startswith('url_recovery_') and
        c['decision'] in ('needs_review','relevant') and c['id'] not in records]
    if pending:
        provider=pending[0]['provider'];cases=[c for c in pending if c['provider']==provider][:state['research_policy']['review_batch_size']]
        review_key='review_batch_'+workspace.digest([state.get('dataset_revision'),[c['id'] for c in cases]])[:20]
        recovery.setdefault('review_jobs',{})[review_key]=provider;api.save(base,state)
        done=api.run_review_batch(base,state,{'provider':provider,'cases':cases},timeout,cli)
        if done:
            updated=api.read_json(api.screening_path(base));current=api.read_json(base/'extracted.json')
            for result in recovery['results'].values():
                row=result['row'];cid=api.case_id(provider,row['url']) if row.get('url') and row.get('listing_url') else None
                if result['task'].startswith('url_recovery_'+api.slugify(provider)+'_') and cid in updated:
                    decision=updated[cid];result.update(decision=decision['decision'],reason=decision['reason'])
                    result['row']=dict(row,decision=decision['decision'],reason=decision['reason'],evidence=decision['evidence'],reading_depth='substantive',record=current.get(cid))
            api.save(base,state)
        return done
    eligible=[]
    for order,provider in enumerate(state['approved_providers']):
        missing=[r for r in recovery['baseline'][provider]['slots'] if provider+':'+str(r['listing_position']) not in recovery['results']]
        if missing:eligible.append((recovery['turns'].get(provider,0),order,provider,missing))
    if not eligible:
        recovery['provider_results']=progress(api,base,state)
        recovery['coverage_complete']=all(r['coverage_status']=='resolved' for r in recovery['provider_results'])
        recovery['status']='complete';state['phase']='url_recovery_complete';api.save(base,state)
        print('URL recovery finished locally. Published Sheet, Doc and existing analyses unchanged.');return True
    _,_,provider,missing=min(eligible)
    # Existing source receipts survive a stop between extraction and slot ACK.
    ledger=api.read_json(api.screening_path(base))
    for old in missing:
        current=next(r for r in state['listing_universes'][provider]['entries'] if r['listing_position']==old['listing_position'])
        cid=current.get('source_case_id',current['id'])
        if current.get('url') and cid in ledger:
            saved=ledger[cid]
            if saved['decision']!='relevant' or cid in records:
                checkpoint(api,base,state,saved.get('discovery_key','recovered_receipt'),{'approved_provider':provider},dict(
                    old,url=current['url'],decision=saved['decision'],reason=saved['reason']))
                return True
    missing.sort(key=lambda r:(not bool(recovery['saved_candidates'].get(provider+':'+str(r['listing_position']))),r['listing_position']))
    selected=missing[:state['research_policy']['review_batch_size']]
    key='url_recovery_'+api.slugify(provider)+'_'+workspace.digest([r['listing_position'] for r in selected])[:16]
    turns=recovery['turns'];turns[provider]=1+max(turns.values(),default=0);api.save(base,state)
    return execute_slots(api,base,state,provider,selected,key,recovery['saved_candidates'],timeout,cli)


def execute_slots(api,base,state,provider,selected,key,saved_candidates,timeout,cli,ordinary=False):
    records=api.read_json(base/'extracted.json') if (base/'extracted.json').exists() else {}
    seed={str(r['listing_position']):saved_candidates.get(provider+':'+str(r['listing_position']),[]) for r in selected}
    captures={}
    for entries in seed.values():
        for candidate in entries:
            captures[candidate['url']]=list(research.captures_for(base,provider,candidate['url']))
    context={'target':state['company'],'task':'discover','approved_provider':provider,
        'competing_product':api.provider_scope(base,state,provider),'first_listing_entries':30,
        'listing_contract_v2':True,'url_recovery':True,'ordinary_resolution':ordinary,'recovery_slots':selected,
        'saved_candidate_urls':seed,'saved_candidate_captures':captures,
        'completed_provider_records':[r for r in records.values() if r['provider']==provider],
        'selected_listing_entries':state['listing_universes'][provider]['entries'],
        'max_cases':len(selected),'known_case_urls':[r['source_url'] for r in records.values()],
        'completed_case_urls':[r['source_url'] for r in records.values()],
        'scope':'Recover ONLY assigned witnessed slots. Saved candidate URLs first. Original listing pages/link targets next; targeted exact-title/customer searches only where links cannot be exposed. No other archives, replacement cards or new positions. Preserve listing_url, position, title and customer exactly. Substantively read relevant cases require full extraction now; partial metadata can queue needs_review. Unavailable or unassociable means unresolved with no record. Never reopen a completed source or any recorded access failure. Checkpoint each card before the next. No publication or analysis.'}
    obj=api.invoke(base,state,2,key,context,timeout,cli)
    if obj is None:return False
    allowed={r['listing_position'] for r in selected}
    for row in obj['cases']:
        if row.get('listing_position') not in allowed:raise api.RunError('Recovery returned an unassigned listing slot.','validation')
        api.commit_worker_message(base,state,key,context,{'discovered_case':row},'saved_url_recovery_response')
    completed={r['listing_position'] for r in state['listing_universes'][provider]['entries'] if r.get('resolution_outcome')} if ordinary else {
        int(k.rsplit(':',1)[1]) for k in state['url_recovery']['results'] if k.startswith(provider+':')}
    if not allowed & completed:
        raise api.RunError('URL recovery returned no validated slot results.','validation')
    api.checkpoint_job(state,key);api.save(base,state)
    print('URL recovery',provider,':',len(allowed & completed),'slot results saved.')
    return True


def resolve_pending(api,base,state,plan,timeout,cli):
    """Normal Stage 2 dispatch using the existing bounded association worker."""
    provider=plan['provider'];selected=plan['cases']
    key='resolve_urls_'+api.slugify(provider)+'_'+workspace.digest([state.get('dataset_revision'),[r['listing_position'] for r in selected]])[:16]
    return execute_slots(api,base,state,provider,selected,key,candidates(base,state),timeout,cli,ordinary=True)
