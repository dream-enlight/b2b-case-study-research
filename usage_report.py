"""Read-only worker/session observability. Standard library, no model calls."""
import collections
import datetime
import json
import re
from pathlib import Path
import performance

TOKENS=('input_tokens','cached_input_tokens','output_tokens')


def events(path):
    if not path.exists():return
    for line in path.open():
        try:yield json.loads(line)
        except ValueError:continue


def read(path,default=None):
    try:return json.loads(path.read_text())
    except (OSError,ValueError):return default


def messages(text):
    decoder=json.JSONDecoder();text=text.lstrip()
    while text:
        try:obj,end=decoder.raw_decode(text)
        except ValueError:return
        if not isinstance(obj,dict):return
        yield obj;text=text[end:].lstrip()


def session_details(path):
    requests=[];seen=set();tools=collections.Counter();started=None;elapsed=None;turns=0;missing_observations=0
    for event in events(path):
        payload=event.get('payload',{});kind=payload.get('type')
        if event.get('type')=='event_msg' and kind=='task_started':
            turns+=1
            if turns>1:break # exec starts a fresh worker; later human turns are unrelated
            started=event.get('timestamp')
        if event.get('type')=='event_msg' and kind=='task_complete':
            elapsed=payload.get('duration_ms');elapsed=elapsed/1000 if elapsed is not None else None
        if event.get('type')=='event_msg' and kind=='token_count':
            info=payload.get('info') or {};last=info.get('last_token_usage');total=info.get('total_token_usage')
            if not last or not total:
                missing_observations+=1;continue
            identity=tuple(total.get(k) for k in TOKENS)
            if identity in seen:continue
            seen.add(identity)
            row={'request':len(requests)+1,'at':event.get('timestamp'),**{k:last.get(k) for k in TOKENS}}
            row['uncached_input_tokens']=row['input_tokens']-row['cached_input_tokens'] if all(row[k] is not None for k in TOKENS[:2]) else None
            requests.append(row)
        if event.get('type')=='response_item' and kind=='custom_tool_call' and payload.get('name')=='exec':
            code=payload.get('input','');tools['exec_calls']+=1
            if re.fullmatch(r'\s*(?://[^\n]*\n\s*)*text\(("(?:[^"\\]|\\.)*")\);?\s*',code):tools['literal_print_noops']+=1
            elif 'tools.web__run' in code or 'web.run' in code:tools['web_operations']+=1
            elif ('JSON.stringify' in code and ('record:' in code or '"record"' in code)) or re.search(r'text\(\s*\{\s*(?:discovered_case|case_result|extracted_record)\s*:',code):tools['case_object_echoes']+=1
    inputs=[r['input_tokens'] for r in requests if r['input_tokens'] is not None]
    complete_inputs=bool(requests) and not missing_observations and all(r['input_tokens'] is not None for r in requests)
    first=requests[0]['input_tokens'] if requests and not missing_observations else None
    last=requests[-1]['input_tokens'] if requests and not missing_observations else None
    return {'path':str(path),'model_requests':len(requests) if requests and not missing_observations else None,
            'observed_request_counters':len(requests),'missing_usage_observations':missing_observations,
            'request_count_basis':'distinct cumulative token-count observations in the first worker turn',
            'requests':requests,'first_request_input_tokens':first,
            'last_request_input_tokens':last,'peak_request_input_tokens':max(inputs) if complete_inputs else None,
            'observed_peak_request_input_tokens':max(inputs) if inputs else None,
            'context_growth_tokens':last-first if first is not None and last is not None else None,
            'elapsed_seconds':elapsed,'tools':dict(tools),
            'missing_usage_counters':bool(missing_observations) or not requests or any(r[k] is None for r in requests for k in TOKENS)}


def emitted_outcomes(log,provider):
    rows={}
    for event in events(log):
        item=event.get('item',{})
        if event.get('type')!='item.completed' or item.get('type')!='agent_message':continue
        for message in messages(item.get('text','')):
            for key in ('case_result','discovered_case','extracted_record'):
                row=message.get(key)
                if not isinstance(row,dict):continue
                record=row.get('record') if key!='extracted_record' else row
                identity=row.get('id') or (provider,row.get('url',row.get('source_url')))
                if not row.get('id') and not row.get('url',row.get('source_url')):identity=(provider,row.get('listing_position'))
                status='complete' if isinstance(record,dict) and record.get('status')=='complete' else row.get('decision',row.get('status','unknown'))
                rows[str(identity)]=status
    return dict(collections.Counter(rows.values()))


def aggregate(workers):
    totals={'workers':len(workers),'measured_model_requests':sum(w['session'].get('observed_request_counters',w['session'].get('model_requests') or 0) for w in workers),
            'workers_missing_request_counts':sum(w['session'].get('model_requests') is None for w in workers)}
    totals['model_requests']=None if totals['workers_missing_request_counts'] else totals['measured_model_requests']
    for key in TOKENS+('uncached_input_tokens',):
        measured=[w['usage'][key] for w in workers if w['usage'].get(key) is not None]
        totals[key]=sum(measured) if measured else None
        totals[key+'_measured_workers']=len(measured)
    peaks=[w['session'].get('peak_request_input_tokens') for w in workers if w['session'].get('peak_request_input_tokens') is not None]
    totals['peak_request_input_tokens']=max(peaks) if peaks else None
    elapsed=[w['elapsed_seconds'] for w in workers if w['elapsed_seconds'] is not None]
    totals['elapsed_seconds']=round(sum(elapsed),3) if elapsed else None
    totals['elapsed_measured_workers']=len(elapsed)
    totals['observed_web_operations']=sum(w['web_operations'] for w in workers)
    totals['retry_warnings']=sum(w['retry_warning_count'] for w in workers)
    totals['local_recovery_events']=sum(len(w['local_recoveries']) for w in workers)
    totals['workers_with_error_diagnostics']=sum(bool(w['error'] or w['cli_errors']) for w in workers)
    return totals


def build(base,sessions_root,worker_filter=None):
    base=Path(base);sessions_root=Path(sessions_root)
    logs=sorted(set((base/'logs').glob('*.jsonl')) | {p.with_name(p.name.replace('.execution.json','.jsonl')) for p in (base/'logs').glob('*.execution.json')})
    session_index={}
    if sessions_root.exists():
        for path in sessions_root.rglob('*.jsonl'):
            match=re.search(r'([0-9a-f-]{36})\.jsonl$',path.name)
            if match:session_index.setdefault(match[1],[]).append(path)
    perf=list(events(base/'performance.jsonl'));state=read(base/'state.json',{})
    receipts=collections.defaultdict(collections.Counter)
    for path in (base/'research/cases').rglob('*.json'):
        receipt=read(path,{})
        if receipt.get('committed'):
            result=receipt.get('result',{});record=result.get('record')
            outcome='complete' if isinstance(record,dict) and record.get('status')=='complete' else result.get('decision','unknown')
            receipts[receipt.get('task')][outcome]+=1
    log_counts=collections.Counter((read(p.with_suffix('.execution.json'),{}).get('key') or p.stem.rsplit('_',1)[0]) for p in logs)
    workers=[]
    for log in logs:
        metadata=read(log.with_suffix('.execution.json'),{})
        key=metadata.get('key') or log.stem.rsplit('_',1)[0]
        if worker_filter and not key.startswith(worker_filter):continue
        prompt=log.with_suffix('.prompt.txt');assignment=metadata.get('assignment',{})
        if prompt.exists():
            try:assignment=json.JSONDecoder().raw_decode(prompt.read_text().split('TASK ASSIGNMENT (machine generated):',1)[1].lstrip())[0]
            except (ValueError,IndexError):pass
        provider=assignment.get('approved_provider') or 'unknown'
        providers=list(dict.fromkeys(c['provider'] for c in assignment.get('review_cases',assignment.get('assigned_cases',[]))))
        if len(providers)>1:provider='mixed: '+', '.join(providers)
        task=assignment.get('task') or assignment.get('analysis_task') or 'unknown'
        thread=None;usage={};url_counts=collections.Counter();references=collections.Counter();web_ops=0;cli_errors=[]
        for event in events(log):
            if event.get('type')=='thread.started':thread=event.get('thread_id')
            if event.get('type')=='turn.completed':usage=event.get('usage',{})
            if event.get('type') in ('error','turn.failed'):cli_errors.append(event)
            item=event.get('item',{})
            if event.get('type')=='item.completed' and item.get('type')=='web_search':
                web_ops+=1
                for url in performance.source_attempts(item):
                    (url_counts if url.startswith(('http://','https://')) else references)[url]+=1
        paths=session_index.get(thread,[])
        session=session_details(paths[0]) if len(paths)==1 else {
            'path':None,'model_requests':None,'requests':[],
            'unavailable_reason':'session directory missing' if not sessions_root.exists() else 'session log not found' if not paths else 'multiple matching session logs'}
        matching=[e for e in perf if e.get('kind')=='execution' and e.get('key')==key and
                  (e.get('artifact')==log.name or not e.get('artifact') and log_counts[key]==1)]
        metrics=matching[0] if len(matching)==1 else {}
        if not usage:usage={k:metrics.get(k) for k in TOKENS}
        totals_source='CLI/performance worker totals' if any(usage.get(k) is not None for k in TOKENS) else 'session observed requests only'
        for token in TOKENS:
            if usage.get(token) is None:
                requests=session.get('requests',[])
                values=[r.get(token) for r in requests]
                usage[token]=sum(values) if values and not session.get('missing_usage_observations') and all(v is not None for v in values) else None
        usage={k:usage.get(k) for k in TOKENS}
        usage['uncached_input_tokens']=usage['input_tokens']-usage['cached_input_tokens'] if all(usage[k] is not None for k in TOKENS[:2]) else None
        stderr=log.with_suffix('.stderr.txt');stderr_text=stderr.read_text() if stderr.exists() else ''
        job=state.get('jobs',{}).get(key,{})
        workers.append({'key':key,'artifact':str(log),'events_available':log.exists(),'thread_id':thread,'task':task,'provider':provider,
                        'initial_prompt_bytes':len(prompt.read_bytes()) if prompt.exists() else metadata.get('initial_prompt_bytes'),
                        'session':session,'usage':usage,'usage_source':totals_source,
                        'elapsed_seconds':metadata.get('elapsed_seconds',metrics.get('elapsed_seconds')),
                        'runner_metrics_attribution':'unique artifact/key match' if metrics else 'missing or ambiguous; not attributed',
                        'web_operations':web_ops,'web_operations_source':'CLI item.completed web_search',
                        'resolved_url_accesses':dict(url_counts),'repeated_url_accesses':{u:n for u,n in url_counts.items() if n>1},
                        'unresolved_source_references':dict(references),'emitted_outcomes':emitted_outcomes(log,provider),
                        'durable_receipt_outcomes_for_task':dict(receipts.get(key,{})),
                        'error':metadata.get('failure') or ({'message':job['last_error'],'attribution':'task-level; attempt unknown'} if job.get('last_error') else None),
                        'task_failure_history':job.get('failure_history',[]),'cli_errors':cli_errors,'retry_warning_count':len(re.findall(r'retrying|retry attempt',stderr_text,re.I)),
                        'local_recoveries':[e for e in perf if e.get('kind')=='local_recovery' and e.get('key')==key and e.get('log')==log.name]})
    groups={}
    for field in ('task','provider'):
        grouped=collections.defaultdict(list)
        for worker in workers:grouped[worker[field]].append(worker)
        groups[field]={key:aggregate(value) for key,value in grouped.items()}
    return {'run':base.name,'worker_filter':worker_filter,'sessions_root':str(sessions_root),'workers':workers,
            'unmatched_job_diagnostics':{k:{'status':j.get('status'),'last_error':j.get('last_error')} for k,j in state.get('jobs',{}).items() if j.get('last_error') and k not in {w['key'] for w in workers} and (not worker_filter or k.startswith(worker_filter))},
            'aggregate':{'run':aggregate(workers),**groups},
            'limitations':[
                'Cumulative input sums request inputs; peak input is the largest individual request, not their sum.',
                'Initial prompt bytes exclude system/tool context and are not a token count.',
                'Missing counters/logs are null. Partial per-request counters are not promoted into complete cumulative totals or peaks; observed counters remain available. Measured-worker counts disclose aggregate coverage.',
                'Web operations are observed operations, not an independent assessment of usefulness; repeated URLs count resolved CLI source accesses.',
                'Durable receipts are attributed to task keys, not individual attempts sharing that key. Mixed-provider workers are grouped as mixed; their tokens are not allocated to providers.',
                'Request counts use distinct observed token totals, not unmetered transport retries. Session details cover only the first worker turn.']}


def markdown(report):
    total=report['aggregate']['run'];lines=[f"# Saved usage report: {report['run']}",
        f"Worker filter: `{report['worker_filter'] or 'all'}`. Read-only; no model or Workspace calls.",
        '\n| Worker | Requests | Cumulative input | Cached input | Uncached input | Output | Peak request input | Elapsed seconds |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
    def show(value):return 'unavailable' if value is None else f'{value:,}' if isinstance(value,(int,float)) else str(value)
    for w in report['workers']:
        usage=w['usage'];session=w['session']
        lines.append('| '+' | '.join([w['key'],show(session.get('model_requests')),*[show(usage.get(k)) for k in ('input_tokens','cached_input_tokens','uncached_input_tokens','output_tokens')],show(session.get('peak_request_input_tokens')),show(w['elapsed_seconds'])])+' |')
        lines.extend([f"\nProvider: {w['provider']}. Task: {w['task']}. Initial prompt: {show(w['initial_prompt_bytes'])} bytes.",
                      f"Context input: {show(session.get('first_request_input_tokens'))} → {show(session.get('last_request_input_tokens'))}; growth {show(session.get('context_growth_tokens'))} tokens.",
                      f"Observed web operations: {w['web_operations']}. Session tool counts: {json.dumps(session.get('tools',{}))}.",
                      f"Repeated resolved URL accesses: {json.dumps(w['repeated_url_accesses'])}.",
                      f"Emitted outcomes (not acceptance): {json.dumps(w['emitted_outcomes'])}. Durable task receipts: {json.dumps(w['durable_receipt_outcomes_for_task'])}.",
                      f"Error: {json.dumps(w['error'])}. Retry warnings: {w['retry_warning_count']}. Local recovery events: {len(w['local_recoveries'])}.",
                      f"Prior task failure history: {json.dumps(w['task_failure_history'])}."])
        if session.get('unavailable_reason'):lines.append('Session detail unavailable: '+session['unavailable_reason'])
        lines.extend(['\n| Request | Input | Cached | Uncached | Output |','| ---: | ---: | ---: | ---: | ---: |'])
        for r in session.get('requests',[]):lines.append('| '+' | '.join(show(r[k]) for k in ('request','input_tokens','cached_input_tokens','uncached_input_tokens','output_tokens'))+' |')
    lines.extend(['\n## Aggregates','```json',json.dumps(report['aggregate'],indent=2),'```','\n## Measurement limits'])
    lines.extend('- '+text for text in report['limitations'])
    return '\n'.join(lines)+'\n'
