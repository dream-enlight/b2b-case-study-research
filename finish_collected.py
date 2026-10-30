"""Explicit, backed-up early completion; discovery checkpoints remain historical."""
from pathlib import Path
import workspace


DISCLOSURE=('The dataset uses completed case studies collected before the new first-30 discovery policy was introduced. '
    'The user intentionally stopped competitor discovery to control model usage and execution time. '
    'Provider coverage is partial and uneven; this is neither a uniform first-30 sample nor an exhaustive inventory. '
    'Unresolved and inaccessible sources are excluded from complete-case counts. '
    'Any bounded target-story recovery is identified separately; content-confirmed associations do not verify listing hrefs.')


def validate_saved(api,base,state):
    records=api.read_json(base/'extracted.json') if (base/'extracted.json').exists() else {}
    if not records:raise api.RunError('No collected records to finalize.','validation')
    for cid,r in records.items():
        case={'id':cid,'provider':r['provider'],'url':r['source_url']}
        normalized=next(iter(api.validate_records([case],[r]).values()))
        if normalized!=r or cid!=api.case_id(r['provider'],r['source_url']):
            raise api.RunError('Collected record identity mismatch: '+cid,'validation')
        receipt=api.case_receipt_path(base,state,cid)
        if not receipt.exists():raise api.RunError('Missing collected case receipt: '+cid,'validation')
        entry=api.read_json(receipt)
        if not entry.get('committed') or entry.get('dataset_revision')!=state.get('dataset_revision') or entry['case']['id']!=cid:
            raise api.RunError('Incomplete collected case receipt: '+cid,'validation')
        row=entry['result'].get('record')
        if row is None or next(iter(api.validate_records([entry['case']],[row]).values()))!=r:
            raise api.RunError('Collected receipt/extraction mismatch: '+cid,'validation')
    api.ordered_records(base)  # Verify the existing published prefix is intact.
    return records


def start(api,args):
    with api.locked(args.id) as base:
        state=api.read_state(base)
        if state.get('early_completion'):
            print('Early completion already requested; saved recovery and publication checkpoints retained.');return
        phase=state.get('paused_from',state['phase'])
        if phase not in ('stage2','stage3') or state.get('workspace_pending'):
            raise api.RunError('Early completion requires unfinished research and no pending Workspace action.')
        if not args.reason.strip():raise api.RunError('Explicit partial-completion reason required.')
        records=validate_saved(api,base,state)
        supplied=api.read_json(args.recovery_file) if args.recovery_file else []
        if not isinstance(supplied,list) or len(supplied)>state['research_policy']['review_batch_size']:
            raise api.RunError('Recovery must fit one existing review batch.','validation')
        cards=[];seen=set()
        for item in supplied:
            provider=item['provider'];position=item['position']
            matches=[c for c in state.get('listing_universes',{}).get(provider,{}).get('entries',[]) if c.get('listing_position')==position]
            if len(matches)!=1 or (provider,position) in seen:raise api.RunError('Recovery requires a unique observed listing card.','validation')
            seen.add((provider,position));card=dict(matches[0]);url=item.get('url')
            evidence=[]
            if url:
                url=api.norm_url(url)
                for ref in item.get('evidence',[]):
                    path=(base/ref['path']).resolve()
                    if not path.is_relative_to(base.resolve()) or not ref['quote'] or ref['quote'] not in path.read_text():
                        raise api.RunError('Recovery candidate lacks exact saved evidence.','validation')
                    evidence.append(dict(ref,sha256=workspace.digest(path.read_text())))
                if not evidence or not any(url in e['quote'] for e in evidence):
                    raise api.RunError('Recovery URL must occur in cited saved evidence.','validation')
            cards.append({'card':card,'candidate_url':url,'evidence':evidence})
        backup=api.backup_run(base,'before_finish_collected')
        plan={'reason':args.reason,'requested_at':api.utc(),'backup':backup,'original_records':records,
              'cards':cards,'recovery_key':'finish_recovery_'+workspace.digest(cards)[:20],
              'disclosure':DISCLOSURE,'outcomes':[]}
        state['early_completion']=plan
        state['phase']='finish_collected';state.pop('paused_from',None);state.pop('pause_reason',None)
        api.save(base,state)
        print('Backed-up partial completion requested; provider exhaustion flags unchanged. Backup:',backup)


def step(api,base,state,timeout,cli):
    plan=state['early_completion'];records=validate_saved(api,base,state)
    if any(records.get(cid)!=r for cid,r in plan['original_records'].items()):
        raise api.RunError('Completed evidence changed after early-completion request.','validation')
    cases=[]
    for entry in plan['cards']:
        card=entry['card'];url=entry['candidate_url']
        if not url:continue
        cid=api.case_id(card['provider'],url)
        if cid in records or api.case_receipt_path(base,state,cid).exists():continue
        cases.append({'id':cid,'provider':card['provider'],'url':url,'customer':card['customer'],'title':card['title'],
            'competing_product':api.provider_scope(base,state,card['provider']),
            'observed_card':card,'candidate_evidence':entry['evidence']})
    key=plan['recovery_key'];job=state['jobs'].get(key,{})
    cache=base/'results'/f'{key}.json'
    # At most one fresh execution. A crash reuses receipts/cache; never rereads
    # sources just because the bounded recovery returned an incomplete prefix.
    if cases and (not job.get('attempts') or (cache.exists() and job.get('status') in ('returned','complete'))):
        failures=api.research.failed_sources(base)
        cases=[c for c in cases if api.norm_url(c['url']) not in failures]
        if cases:
            obj=api.invoke(base,state,2,key,{'task':'review_batch','review_cases':cases,
                'recovery_only':True,'allowed_source_urls':[c['url'] for c in cases],
                'competing_products':{c['provider']:c['competing_product'] for c in cases},
                'scope':'One bounded recovery of ONLY these previously observed cards and saved candidate URLs. No discovery, searches, listings or alternate URLs. Read each assigned story content once. Confirm whether content supports the observed card identity and approved product scope; ambiguous/inaccessible means unresolved with no record. A candidate is NOT a verified listing href. For relevant content, extract the complete five-column record and state content-confirmed association/listing href unverified in its note. Emit each result immediately. Do not reread completed cases.'},timeout,cli)
            if obj is None:return False  # Quota/error pauses retain the attempt.
            for result in obj['results']:api.commit_case_result(base,state,key,cases,result)
    outcomes=[]
    for entry in plan['cards']:
        card=entry['card'];url=entry['candidate_url'];cid=api.case_id(card['provider'],url) if url else None
        path=api.case_receipt_path(base,state,cid) if cid else None
        if path and path.exists():
            receipt=api.read_json(path)
            if not receipt.get('committed'):api.apply_case_receipt(base,state,path)
            result=receipt['result'];decision=result['decision'];reason=result['reason']
        else:decision='unresolved';reason='No reliable saved association, saved access failure, or bounded attempt ended without a complete case checkpoint.'
        outcomes.append({'provider':card['provider'],'position':card['listing_position'],'title':card['title'],
            'candidate_url':url,'decision':decision,'reason':reason,
            'association':'content-confirmed; listing href unverified' if decision=='relevant' else 'unresolved or excluded; listing href unverified'})
    plan['outcomes']=outcomes;plan['recovery_finished']=True
    records=validate_saved(api,base,state)
    inventory={}
    for r in records.values():inventory.setdefault(r['provider'],[]).append({'id':r['id'],'provider':r['provider'],'url':r['source_url'],'customer':r['customer'],'title':'Collected case'})
    batches=api.compile_batches(inventory)
    if {c['id'] for b in batches for c in b['cases']}!=set(records):raise api.RunError('Early-completion batch coverage mismatch.','validation')
    api.atomic_json(base/'batches.json',batches)
    state['screening_summary']={'completion':'user-requested partial coverage','disclosure':plan['disclosure'],
        'reason':plan['reason'],'recovery_outcomes':outcomes,
        'providers':api.coverage_plan(base,state)['coverage']}
    state['phase']='stage3';api.save(base,state)
    print('Collected evidence handed to normal extraction integrity/finalization; no competitor research scheduled.')
    return True
