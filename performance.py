"""Append-only observed metrics, with no model or connector calls."""
import collections
import datetime
import json
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit


def source_attempts(item):
    """Actual CLI formats: one attempt per distinct source represented in a call.

    Batched opens sometimes serialize as other (or under the first search).
    View results identify those sources; ordinary search snippets are not reads.
    Multiple windows of one source in a single call count once.
    """
    if item.get('type')!='web_search':return []
    action=item.get('action',{});kind=action.get('type')
    urls=[r['url'] for r in item.get('results',[]) if r.get('url') and
          ('Total lines:' in r.get('snippet','') or 'view' in r.get('ref_id','') and kind!='search')]
    if not urls and kind in ('open','open_page','click','find','find_in_page','other'):
        urls=action.get('urls') or [action.get('url') or action.get('ref_id') or 'unresolved-source-reference']
    def normalize(url):
        p=urlsplit(str(url))
        return urlunsplit((p.scheme.lower(),p.netloc.lower(),p.path.rstrip('/') or '/',p.query,'')) if p.netloc else str(url)
    return list(dict.fromkeys(normalize(u) for u in urls))


def event(base,stage,kind,**values):
    path=Path(base)/'performance.jsonl';path.parent.mkdir(parents=True,exist_ok=True)
    row=dict(at=datetime.datetime.now(datetime.timezone.utc).isoformat(),stage=str(stage),kind=kind,**values)
    with path.open('a') as out:
        out.write(json.dumps(row,ensure_ascii=False)+'\n')


def worker(base,stage,key,elapsed,stdout,failed,*,artifact=None):
    usage={};attempts=[];checkpoints=0
    for line in stdout.splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('type')=='turn.completed':usage=e.get('usage',{})
        if e.get('type')!='item.completed':continue
        item=e.get('item',{})
        attempts.extend(source_attempts(item))
        if item.get('type')=='mcp_tool_call' and item.get('tool')=='save_records':checkpoints+=1
    event(base,stage,'execution',key=key,artifact=artifact,elapsed_seconds=round(elapsed,3),failed=failed,
          input_tokens=usage.get('input_tokens'),cached_input_tokens=usage.get('cached_input_tokens'),
          output_tokens=usage.get('output_tokens'),source_attempts=attempts,checkpoint_calls=checkpoints)


def summary(base):
    stages=collections.defaultdict(lambda:dict(executions=0,elapsed_seconds=0,processed_records=0,failures=0,checkpoints=0,inventory_candidates=0,deep_reviews=0,extracted_records=0,classified_records=0,workspace_planned=0,workspace_operations=0,human_interventions=0,source_attempts=0,repeated_reads=0,input_tokens=None,cached_input_tokens=None,uncached_input_tokens=None,output_tokens=None))
    path=Path(base)/'performance.jsonl';seen=set();times={}
    for line in path.read_text().splitlines() if path.exists() else []:
        e=json.loads(line);s=stages[e['stage']];kind=e['kind']
        end=datetime.datetime.fromisoformat(e['at']);start=end-datetime.timedelta(seconds=e.get('elapsed_seconds',0))
        low,high=times.get(e['stage'],(start,end));times[e['stage']]=(min(start,low),max(end,high))
        if kind=='execution':
            s['executions']+=1;s['elapsed_seconds']+=e['elapsed_seconds'];s['failures']+=int(e['failed'])
            for k in ('input_tokens','cached_input_tokens','output_tokens'):
                if e.get(k) is not None:s[k]=(s[k] or 0)+e[k]
            for url in e['source_attempts']:
                s['source_attempts']+=1;s['repeated_reads']+=int(url in seen);seen.add(url)
        if kind=='checkpoint':
            s['checkpoints']+=1;s['processed_records']+=e.get('records',0)
            if e.get('work_type') in s:s[e['work_type']]+=e.get('records',0)
        if kind=='workspace_plan':s['workspace_planned']+=1
        if kind=='workspace_failure':s['failures']+=1
        if kind=='workspace':s['workspace_operations']+=1
        if kind=='human':s['human_interventions']+=1
    for stage,s in stages.items():
        s['wall_time_span_seconds']=round((times[stage][1]-times[stage][0]).total_seconds(),3)
        if s['input_tokens'] is not None and s['cached_input_tokens'] is not None:s['uncached_input_tokens']=s['input_tokens']-s['cached_input_tokens']
    return dict(stages)
