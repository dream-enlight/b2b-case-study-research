"""Shared analysis taxonomy and durable compact classifications.

The optional local MCP checkpoint transport exposes only assigned-record writes.
Original classifications and the finalized Sheet are immutable evidence.
"""
import copy
import datetime as dt
import fcntl
from functools import lru_cache
import json
from pathlib import Path
import workspace
import performance

POLICY={'version':2,'batch_size':60,'max_input_bytes':180000,
        'checkpoint_group_size':5,'transport':'local_mcp'}
DIMS=('buying_situations','selection_requirements','company_category','company_characteristics','stakeholders')


def home(base,db):return base/'analysis_records'/db['sha256']/'compact'
def read(path):return json.loads(Path(path).read_text())
def stamp():return dt.datetime.now(dt.timezone.utc).isoformat(timespec='milliseconds')
def category_id(dim,name,definition):return dim[:2]+'_'+workspace.digest([dim,name,definition])[:12]


def registry(base,db):
    data=read(home(base,db)/'registry.json');checksum=data.pop('sha256')
    if workspace.digest(data)!=checksum or data['database_sha256']!=db['sha256']:
        raise workspace.WorkspaceError('Compact taxonomy checksum/provenance mismatch.')
    data['sha256']=checksum
    return data


def save_registry(base,db,data,atomic_json):
    data=copy.deepcopy(data);data.pop('sha256',None);data['sha256']=workspace.digest(data)
    atomic_json(home(base,db)/'registry.json',data)
    return data


def prepare(api,base,state,db,timeout,cli):
    import analysis_pipeline as ap
    path=home(base,db)/'registry.json'
    if path.exists():registry(base,db);return True
    if state.get('analysis_policy',{}).get('taxonomy_first'):
        import taxonomy_first
        return taxonomy_first.prepare(api,base,state,db,timeout,cli)
    saved=ap.classifications(base,db,include_compact=False)
    maps={}
    for stage in (4,5,6):
        tax=ap.taxonomy(api,base,state,db,stage,saved,timeout,cli)
        if tax is None:return False
        api.atomic_json(home(base,db)/'preliminary'/f'taxonomy_{stage}.json',tax)
        maps.update(tax)
    categories={};legacy={}
    for dim,mapping in maps.items():
        legacy[dim]={}
        for label,value in mapping.items():
            cid=category_id(dim,value['name'],value['definition'])
            categories[cid]={'dimension':dim,**value,'origin':'preliminary'}
            legacy[dim][label]=cid
    data={'database_sha256':db['sha256'],'categories':categories,'legacy_map':legacy,
          'legacy_case_ids':sorted(saved),'legacy_receipt_checksums':{
              cid:read(ap.root(base,db)/'records'/f'{cid}.json')['sha256'] for cid in saved}}
    api.atomic_json(home(base,db)/'preliminary_taxonomy.json',dict(data,sha256=workspace.digest(data)))
    save_registry(base,db,data,api.atomic_json)
    return True


def tool_schema():
    s={'type':'string'};array=lambda x:{'type':'array','items':x}
    def obj(props,required):return {'type':'object','properties':props,'required':required,'additionalProperties':False}
    obs=obj({'cat':s,'cell':{'type':'integer','minimum':1,'maximum':4},'quote':s,
             'strength':{'type':'string','enum':['explicit','supported','outcome_only','unclear']},
             'people':array(s),'involvement':s,'detail':s,'kind':{'type':'string','enum':['trigger','goal','requirement','benefit','outcome','uncertain','descriptive']}},['cat','cell','quote','strength'])
    record=obj({'id':s,'anonymous':{'type':'boolean'},'aliases':array(obj({'name':s,'evidence':s},['name','evidence'])),
                'observations':array(obs),'identity_note':s,'limitations':s},['id','anonymous','observations'])
    new=obj({'ref':s,'dimension':{'type':'string','enum':list(DIMS)},'name':s,'definition':s},['ref','dimension','name','definition'])
    return obj({'records':dict(array(record),minItems=1,maxItems=5),'new_categories':array(new)},['records'])


def expand_record(record,reg,row):
    result={'id':record['id'],'anonymous':record['anonymous'],'aliases':record.get('aliases',[]),
            'identity_note':record.get('identity_note',''),'limitations':record.get('limitations','')}
    result.update({dim:[] for dim in DIMS})
    for obs in record['observations']:
        cat=reg['categories'].get(obs['cat'])
        if not cat:raise workspace.WorkspaceError('Unknown compact category: '+obs['cat'])
        ref=obs['evidence_ref'];cell=row[ref['cell']]
        if ref['source_sha256']!=workspace.digest(cell) or not 0<=ref['start']<=ref['end']<=len(cell):
            raise workspace.WorkspaceError('Compact evidence reference does not match finalized Sheet.')
        result[cat['dimension']].append({'label':cat['name'],'definition':cat['definition'],
            'evidence':cell[ref['start']:ref['end']],'evidence_strength':obs['strength'],
            'people':obs.get('people',[]),'involvement':obs.get('involvement','')})
    if len(result['company_category'])!=1:
        raise workspace.WorkspaceError('Exactly one primary company category is required.')
    result['company_category']=result['company_category'][0]
    return result


def records(base,db):
    import analysis_pipeline as ap
    if not (home(base,db)/'registry.json').exists():return {}
    reg=registry(base,db);rows=ap.eligible_rows(db);result={}
    for path in (home(base,db)/'records').glob('*.json'):
        item=read(path);checksum=item.pop('sha256')
        if workspace.digest(item)!=checksum or item['database_sha256']!=db['sha256']:
            raise workspace.WorkspaceError('Compact classification checksum/provenance mismatch.')
        cid=item['record']['id']
        if cid!=path.stem or cid not in rows or cid in reg['legacy_case_ids']:
            raise workspace.WorkspaceError('Compact classification identity conflict.')
        result[cid]=expand_record(item['record'],reg,rows[cid])
    return result


@lru_cache(maxsize=4)
def _checkpoint_database(path,mtime,size,expected):
    db=read(path);check=dict(db);checksum=check.pop('sha256')
    if workspace.digest(check)!=checksum or checksum!=expected:
        raise workspace.WorkspaceError('Checkpoint database identity mismatch.')
    import analysis_pipeline as ap
    return db,ap.eligible_rows(db)


def checkpoint(manifest,arguments,atomic_json):
    """Validate and fsync individual records before returning a tool ACK."""
    import analysis_pipeline as ap
    base=Path(manifest['run_dir']);dbpath=base/'finalized_sheet.json';stat=dbpath.stat()
    db,rows=_checkpoint_database(str(dbpath),stat.st_mtime_ns,stat.st_size,manifest['database_sha256'])
    submitted=arguments.get('records',[])
    if not 1<=len(submitted)<=manifest['checkpoint_group_size']:
        raise workspace.WorkspaceError('Checkpoint group exceeds its validated bound.')
    target=home(base,db);target.mkdir(parents=True,exist_ok=True)
    accepted=[]
    with (target/'.checkpoint.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        reg=registry(base,db);refs={}
        if reg.get('taxonomy_first') and arguments.get('new_categories'):raise workspace.WorkspaceError('Fixed taxonomy: use Other, never grow the mapping registry.')
        for category in arguments.get('new_categories',[]):
            if category['dimension'] not in DIMS or not category['name'].strip() or not category['definition'].strip() or category['ref'] in refs:
                raise workspace.WorkspaceError('Invalid emergent category definition.')
            cid=category_id(category['dimension'],category['name'],category['definition']);refs[category['ref']]=cid
            value={'dimension':category['dimension'],'name':category['name'],'definition':category['definition'],'origin':'emergent'}
            if cid in reg['categories']:
                if any(reg['categories'][cid][k]!=value[k] for k in ('dimension','name','definition')):
                    raise workspace.WorkspaceError('Stable category ID conflict.')
            else:reg['categories'][cid]=value
        # Identity index is reconstructed cheaply from filenames after interruptions.
        # Historical receipts are validated once at full stage completion, not per ACK.
        saved={p.stem for p in (target/'records').glob('*.json')}
        remaining=[cid for cid in manifest['case_ids'] if cid not in saved]
        novel=[r['id'] for r in submitted if r['id'] not in saved]
        if novel!=remaining[:len(novel)] or len(novel)!=len(set(novel)):
            raise workspace.WorkspaceError('Checkpoint only the next assigned unfinished records in order.')
        normalized=[]
        for raw in submitted:
            cid=raw.get('id')
            if cid not in manifest['case_ids'] or cid in reg['legacy_case_ids']:
                raise workspace.WorkspaceError('Checkpoint received an unassigned or completed legacy case.')
            value=copy.deepcopy(raw)
            if set(value)-set(tool_schema()['properties']['records']['items']['properties']):
                raise workspace.WorkspaceError('Unexpected compact record fields.')
            for obs in value['observations']:
                obs['cat']=refs.get(obs['cat'],obs['cat']);column=obs.pop('cell');quote=obs.pop('quote')
                if not isinstance(column,int) or isinstance(column,bool) or not 1<=column<=4:
                    raise workspace.WorkspaceError('Evidence cell must be 1 through 4.')
                source=rows[cid][column];start=source.find(quote)
                cat=reg['categories'].get(obs['cat'],{})
                if reg.get('taxonomy_first'):
                    if cat.get('name')=='Other' and not obs.get('detail','').strip():raise workspace.WorkspaceError('Other requires a specific description.')
                    if cat.get('name')!='Unknown / insufficient evidence' and not quote:raise workspace.WorkspaceError('Meaningful classification requires evidence.')
                    if cat.get('name')=='Unknown / insufficient evidence' and obs['strength']!='unclear':raise workspace.WorkspaceError('Unknown requires unclear strength.')
                    if obs.get('kind') not in ('trigger','goal','requirement','benefit','outcome','uncertain','descriptive'):raise workspace.WorkspaceError('Missing semantic evidence kind.')
                if start<0:raise workspace.WorkspaceError('Evidence quote is not in this finalized Sheet cell: '+cid)
                obs['evidence_ref']={'cell':column,'start':start,'end':start+len(quote),'source_sha256':workspace.digest(source)}
            expanded=expand_record(value,reg,rows[cid]);ap.validate_record(db,manifest['case_ids'],expanded,rows=rows)
            if reg.get('taxonomy_first') and any(not expanded[d] for d in DIMS):raise workspace.WorkspaceError('Every dimension requires a mapping or explicit Unknown.')
            normalized.append(value)
        # Category definitions are durable before records can refer to them.
        if arguments.get('new_categories'):reg=save_registry(base,db,reg,atomic_json)
        for value in normalized:
            path=target/'records'/f'{value["id"]}.json'
            if path.exists():
                if read(path)['record']!=value:raise workspace.WorkspaceError('Completed compact classification is immutable.')
            else:
                payload={'database_sha256':db['sha256'],'record':value,'saved_at':stamp(),'assignment':manifest['key']}
                payload['sha256']=workspace.digest(payload);atomic_json(path,payload)
            accepted.append(value['id'])
        event={'time':stamp(),'accepted_ids':accepted,'registry_sha256':reg['sha256']}
        log=target/'checkpoints'/f'{manifest["key"]}.jsonl';log.parent.mkdir(parents=True,exist_ok=True)
        with log.open('a') as out:
            out.write(json.dumps(event)+'\n');out.flush();__import__('os').fsync(out.fileno())
        performance.event(base,4,'checkpoint',records=len(novel),work_type='classified_records',assignment=manifest['key'])
        remaining=[cid for cid in manifest['case_ids'] if not (target/'records'/f'{cid}.json').exists()]
        return {'saved_ids':accepted,'remaining':len(remaining),'next_ids':remaining[:manifest['checkpoint_group_size']],
                'registered_categories':refs}


def classify_step(api,base,state,db,timeout,cli):
    import analysis_pipeline as ap
    if not prepare(api,base,state,db,timeout,cli):return False
    fixed=state.get('analysis_policy',{}).get('taxonomy_first')
    saved={p.stem for p in (home(base,db)/'records').glob('*.json')} if fixed else ap.classifications(base,db)
    rows=ap.eligible_rows(db)
    missing=[{'id':cid,'cells':row} for cid,row in rows.items() if cid not in saved]
    if not missing:return True
    batch=next(ap.bounded(missing,ap.policy(state)));ids=[r['id'] for r in batch]
    key='analysis_'+db['sha256'][:16]+'_compact_v2_'+workspace.digest(ids)[:16]
    manifest={'run_dir':str(base),'database_sha256':db['sha256'],'case_ids':ids,'key':key,
              'checkpoint_group_size':state['analysis_policy']['checkpoint_group_size']}
    path=home(base,db)/'assignments'/f'{key}.json';api.atomic_json(path,manifest)
    reg=registry(base,db)
    ctx={'analysis_task':'classify_compact','finalized_google_sheet':ap.metadata(db),'records':batch,
         'categories':{k:{f:v[f] for f in ('dimension','name','definition','kind') if f in v} for k,v in reg['categories'].items()},'taxonomy_first':reg.get('taxonomy_first',False),'checkpoint_manifest':str(path),'checkpoint_group_size':manifest['checkpoint_group_size']}
    if len(json.dumps(ctx,ensure_ascii=False).encode())>ap.policy(state)['max_input_bytes']+12000:
        raise workspace.WorkspaceError('Compact assignment exceeds independently configured input budget.')
    if ap._fresh_calls:raise ap.TaskYield()
    obj=api.invoke(base,state,4,key,ctx,timeout,cli)
    if obj is None:return False
    current={p.stem for p in (home(base,db)/'records').glob('*.json')} if fixed else records(base,db)
    if any(cid not in current for cid in ids):
        raise workspace.WorkspaceError('Missing incremental checkpoint ACKs; final JSON is not a persistence substitute.')
    if sorted(obj['completed_ids'])!=sorted(ids) or len(obj['completed_ids'])!=len(set(obj['completed_ids'])):
        raise workspace.WorkspaceError('Compact final receipt does not exactly cover its assignment.')
    events=[json.loads(l) for l in (home(base,db)/'checkpoints'/f'{key}.jsonl').read_text().splitlines()]
    if len(events)<(len(ids)+manifest['checkpoint_group_size']-1)//manifest['checkpoint_group_size']:
        raise workspace.WorkspaceError('Incremental checkpoint transport was not verified for this batch.')
    api.checkpoint_job(state,key);api.save(base,state)
    return False


def final_taxonomy(api,base,state,db,stage,all_records,timeout,cli):
    import analysis_pipeline as ap
    reg=registry(base,db);view={};raw_ids={}
    for cid,record in all_records.items():
        converted=copy.deepcopy(record)
        for dim in ap.DIMENSIONS[stage]:
            observations=[record[dim]] if dim=='company_category' else record[dim];output=[]
            for obs in observations:
                lid=ap.label_id(obs)
                catid=reg['legacy_map'][dim].get(lid) if cid in reg['legacy_case_ids'] else next((k for k,v in reg['categories'].items() if v['dimension']==dim and v['name']==obs['label'] and v['definition']==obs['definition']),None)
                if not catid:raise workspace.WorkspaceError('Observation lacks a stable taxonomy reference.')
                cat=reg['categories'][catid];new=dict(obs,label=cat['name'],definition=cat['definition'])
                raw_ids.setdefault(dim,{})[lid]=(ap.label_id(new),catid);output.append(new)
            converted[dim]=output[0] if dim=='company_category' else output
        view[cid]=converted
    normalized=ap.taxonomy(api,base,state,db,stage,view,timeout,cli)
    if normalized is None:return None
    result={dim:{raw:normalized[dim][value[0]] for raw,value in mapping.items()} for dim,mapping in raw_ids.items()}
    for dim in ap.DIMENSIONS[stage]:result.setdefault(dim,{})
    redirects={}
    for dim,mapping in raw_ids.items():
        for _,(lid,catid) in mapping.items():
            cat=normalized[dim][lid];redirects[catid]={'final_id':category_id(dim,cat['name'],cat['definition']),**cat}
    api.atomic_json(home(base,db)/f'final_reconciliation_{stage}.json',{'database_sha256':db['sha256'],'category_redirects':redirects})
    api.atomic_json(ap.root(base,db)/f'taxonomy_{stage}.json',result)
    return result
