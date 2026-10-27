"""Bounded, restartable classification and deterministic whole-dataset counts.

Only the immutable, independently read-back Sheet rows are evidence. Model calls
classify evidence and reconcile category labels; Python owns coverage and counts.
"""
import json
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
import workspace

POLICY = {'version': 1, 'batch_size': 20, 'max_input_bytes': 60000, 'global_semantic_synthesis': True}
_fresh_calls = 0
class TaskYield(Exception): pass
DIMENSIONS = {4: ('buying_situations', 'selection_requirements'),
              5: ('company_category', 'company_characteristics'), 6: ('stakeholders',)}
STRENGTHS = ('explicit', 'supported', 'outcome_only', 'unclear')


def schema(task):
    if task.startswith('taxonomy_'):
        import taxonomy_first
        return taxonomy_first.schema(task)
    if task in ('global_semantic_map', 'global_synthesis_report'):
        import semantic_synthesis
        return semantic_synthesis.schema(task)
    def obj(props):
        return {'type': 'object', 'properties': props, 'required': list(props), 'additionalProperties': False}
    s = {'type': 'string'}
    arr = lambda x: {'type': 'array', 'items': x}
    observation = obj({'label': s, 'definition': s, 'evidence': s,
                       'evidence_strength': {'type': 'string', 'enum': list(STRENGTHS)},
                       'people': arr(s), 'involvement': s})
    record = obj({'id': s, 'anonymous': {'type': 'boolean'},
                  'aliases': arr(obj({'name': s, 'evidence': s})), 'identity_note': s,
                  'buying_situations': arr(observation), 'selection_requirements': arr(observation),
                  'company_category': observation, 'company_characteristics': arr(observation),
                  'stakeholders': arr(observation), 'limitations': s})
    if task == 'classify_records': return obj({'records': arr(record)})
    if task == 'classify_compact': return obj({'completed_ids': arr(s)})
    if task == 'normalize_categories':
        return obj({'categories': arr(obj({'name': s, 'definition': s, 'members': arr(s)}))})
    if task == 'resolve_company_profiles':
        return obj({'decisions': arr(obj({'profile_id': s, 'category': s, 'reason': s}))})
    return obj({'markdown': s})


def root(base, database): return base / 'analysis_records' / database['sha256']
def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKC', value).casefold() if c.isalnum())
def label_id(obs): return workspace.digest([obs['label'].strip().casefold(), obs['definition'].strip()])[:20]
def metadata(database):
    return {k: database[k] for k in ('sheet', 'sha256', 'headers', 'inventoried', 'complete', 'unavailable', 'provider_counts')}


def eligible_rows(database):
    # Inaccessible native rows are explicitly flagged by the existing bridge.
    ids=database['case_ids'];rows=database['rows']
    if len(ids)!=len(rows) or len(ids)!=len(set(ids)):
        raise workspace.WorkspaceError('Finalized record identity accounting is invalid.')
    eligible={cid:row for cid,row in zip(ids,rows) if not row[4].startswith('INACCESSIBLE — ')}
    if len(eligible)!=database['complete'] or len(rows)-len(eligible)!=database['unavailable']:
        raise workspace.WorkspaceError('Native row eligibility does not match finalized counts.')
    return eligible


def policy(state): return dict(POLICY, **state.get('analysis_policy', {}))


def bounded(items, settings, count=None):
    limit = count or settings['batch_size']; batch = []; size = 0
    for item in items:
        n = len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
        if n > settings['max_input_bytes']:
            raise workspace.WorkspaceError('One analysis input exceeds the configured context bound; no record was truncated.')
        if batch and (len(batch) >= limit or size+n > settings['max_input_bytes']):
            yield batch; batch = []; size = 0
        batch.append(item); size += n
    if batch: yield batch


def read(path): return json.loads(path.read_text())


def validate_record(database, assigned, record, rows=None):
    cid = record.get('id'); rows = eligible_rows(database) if rows is None else rows
    if cid not in assigned or cid not in rows:
        raise workspace.WorkspaceError('Unassigned analysis record: '+str(cid))
    expected = set(schema('classify_records')['properties']['records']['items']['properties'])
    if set(record) != expected or not isinstance(record['anonymous'], bool):
        raise workspace.WorkspaceError('Invalid record classification fields.')
    row = rows[cid]; source = '\n'.join(row)
    for alias in record['aliases']:
        if record['anonymous'] or not alias['name'].strip() or alias['name'] not in source or not alias['evidence'] or alias['evidence'] not in source:
            raise workspace.WorkspaceError('Customer alias is not grounded in the Sheet.')
    for dim in sum((list(v) for v in DIMENSIONS.values()), []):
        observations = [record[dim]] if dim == 'company_category' else record[dim]
        for obs in observations:
            if set(obs) != {'label','definition','evidence','evidence_strength','people','involvement'} or not obs['label'].strip() or not obs['definition'].strip() or obs['evidence_strength'] not in STRENGTHS:
                raise workspace.WorkspaceError('Invalid analysis observation.')
            # Extraction columns can contain overlapping evidence. A company
            # characteristic or selection requirement may occur in another cell
            # of the same case; it must never come from another case or source.
            cell = '\n'.join(row[1:])
            if obs['evidence'] and obs['evidence'] not in cell:
                raise workspace.WorkspaceError('Analysis evidence is not an exact quote from its Sheet row.')
            unknown=obs['label']=='Unknown / insufficient evidence' and obs['evidence_strength']=='unclear'
            if not obs['evidence'] and not (unknown or (dim == 'company_category' and obs['evidence_strength'] == 'unclear')):
                raise workspace.WorkspaceError('Classification lacks Sheet evidence.')
            if dim == 'stakeholders' and not unknown and (not obs['people'] or any(not p.strip() or p not in row[2] for p in obs['people'])):
                raise workspace.WorkspaceError('Stakeholder classification lacks a named person in the Sheet.')
    return record


def commit(base, database, assigned, record, atomic_json):
    validate_record(database, assigned, record)
    cid=record['id']
    payload = {'database_sha256': database['sha256'], 'record': record}
    payload['sha256'] = workspace.digest(payload)
    path = root(base, database)/'records'/f'{cid}.json'
    if path.exists() and read(path) != payload:
        raise workspace.WorkspaceError('Completed record classification is immutable: '+cid)
    if path.exists(): return
    atomic_json(path, payload)


def classifications(base, database, include_compact=True):
    result = {}
    for path in (root(base, database)/'records').glob('*.json'):
        value = read(path); checksum = value.pop('sha256')
        if checksum != workspace.digest(value) or value['database_sha256'] != database['sha256']:
            raise workspace.WorkspaceError('Classification checksum/provenance mismatch.')
        cid = value['record']['id']
        if path.stem != cid or cid in result or cid not in eligible_rows(database):
            raise workspace.WorkspaceError('Unexpected classification identity.')
        result[cid] = value['record']
    if include_compact:
        import analysis_compact
        extra=analysis_compact.records(base,database)
        if set(extra)&set(result):raise workspace.WorkspaceError('Duplicate compact/legacy classification.')
        result.update(extra)
    return result


def call(api, base, state, database, stage, task, token, data, timeout, cli):
    global _fresh_calls
    key = 'analysis_'+database['sha256'][:16]+'_'+task+'_'+token
    context = {'analysis_task': task, 'finalized_google_sheet': metadata(database), **data}
    # Bound the complete assignment; never silently trim evidence or categories.
    if len(json.dumps(context, ensure_ascii=False).encode('utf-8')) > policy(state)['max_input_bytes']+12000:
        raise workspace.WorkspaceError('Analysis assignment exceeds its context budget.')
    job=state.get('jobs',{}).get(key,{})
    reusable=(base/'results'/(key+'.json')).exists() and (job.get('status') in ('returned','complete') or
              (job.get('error_kind')=='validation' and job.get('response_ready')))
    if _fresh_calls and not reusable: raise TaskYield()
    before=sum(j.get('attempts',0) for j in state.get('jobs',{}).values())
    result=api.invoke(base,state,stage,key,context,timeout,cli)
    _fresh_calls += sum(j.get('attempts',0) for j in state.get('jobs',{}).values())-before
    return key,result


def classify_step(api, base, state, database, timeout, cli):
    if policy(state).get('transport')=='local_mcp':
        import analysis_compact
        return analysis_compact.classify_step(api,base,state,database,timeout,cli)
    home = root(base, database); rows = eligible_rows(database)
    # A crash after a validated final response but before merge replays that cache.
    for manifest in (home/'jobs').glob('*.json'):
        job = read(manifest); cached = base/'results'/(job['key']+'.json')
        if cached.exists():
            for item in read(cached)['records']:
                commit(base, database, job['case_ids'], item, api.atomic_json)
    saved = classifications(base, database)
    missing = [dict(id=cid, cells=row) for cid, row in rows.items() if cid not in saved]
    if not missing: return True
    batch = next(bounded(missing, policy(state)))
    ids = [x['id'] for x in batch]; token = workspace.digest(ids)[:16]
    key = 'analysis_'+database['sha256'][:16]+'_classify_records_'+token
    api.atomic_json(home/'jobs'/(key+'.json'), {'key': key, 'case_ids': ids})
    key, obj = call(api, base, state, database, 4, 'classify_records', token,
                    {'records': batch, 'headers': database['headers']}, timeout, cli)
    if obj is None: return False
    seen = set()
    for item in obj['records']:
        if item['id'] in seen: raise workspace.WorkspaceError('Duplicate classification in batch response.')
        seen.add(item['id']); commit(base, database, ids, item, api.atomic_json)
    saved = classifications(base, database)
    if not set(ids) <= set(saved): raise workspace.WorkspaceError('Analysis batch omitted assigned records.')
    api.checkpoint_job(state, key); api.save(base, state)
    return False


def profile_index(database, records):
    """Conservative named-entity union; anonymous profiles stay case-specific.

    Only exact normalized customer labels or explicitly evidenced aliases merge.
    No fuzzy-name matching, parent-company guesses, or generic-label consolidation.
    """
    rows = eligible_rows(database); parent = {cid: cid for cid in rows}; owner = {}
    def find(cid):
        while parent[cid] != cid: cid = parent[cid]
        return cid
    for cid, item in records.items():
        if item['anonymous']: continue
        names = [rows[cid][1]]+[a['name'] for a in item['aliases']]
        for name in names:
            key = normalized(name)
            if not key: continue
            if key in owner: parent[find(cid)] = find(owner[key])
            else: owner[key] = cid
    groups = defaultdict(list)
    for cid in rows: groups[find(cid)].append(cid)
    profiles = {}; mapping = {}
    for members in groups.values():
        pid = workspace.digest(sorted(members))[:16]
        profiles[pid] = {'case_ids': members, 'customers': sorted({rows[c][1] for c in members}),
                         'anonymous': all(records[c]['anonymous'] for c in members)}
        for cid in members: mapping[cid] = pid
    return {'profiles': profiles, 'case_to_profile': mapping,
            'method': 'Exact normalized named customers and Sheet-supported aliases merge. Anonymous customers remain separate unless identity is explicitly established. Unproven aliases remain distinct; this conservative limitation is disclosed.'}


def taxonomy(api, base, state, database, stage, records, timeout, cli):
    home = root(base, database); output = {}
    for dim in DIMENSIONS[stage]:
        catalog = {}
        for record in records.values():
            for obs in [record[dim]] if dim == 'company_category' else record[dim]:
                lid = label_id(obs)
                catalog[lid] = {'id': lid, 'label': obs['label'], 'definition': obs['definition'], 'original_ids': [lid]}
        if not catalog: output[dim] = {}; continue
        level = list(catalog.values()); round_no = 0
        while True:
            # Label lists are much smaller than raw records. Hierarchical merging
            # still bounds unusually large vocabularies without dropping labels.
            parts = list(bounded(level, policy(state), count=1000000))
            merged = []
            for n, part in enumerate(parts):
                token = workspace.digest([dim, round_no, part])[:16]
                key, obj = call(api, base, state, database, stage, 'normalize_categories', token,
                                {'dimension': dim, 'labels': [{k:v for k,v in x.items() if k!='original_ids'} for x in part]}, timeout, cli)
                if obj is None: return None
                expected = {x['id']:x for x in part}; seen = []; names = set()
                for category in obj['categories']:
                    if not category['name'].strip() or not category['definition'].strip() or not category['members'] or normalized(category['name']) in names:
                        raise workspace.WorkspaceError('Invalid or duplicate normalized category.')
                    names.add(normalized(category['name'])); seen += category['members']
                    if any(m not in expected for m in category['members']): raise workspace.WorkspaceError('Taxonomy introduced an unassigned label.')
                    original = sorted({m for cid in category['members'] for m in expected[cid]['original_ids']})
                    merged.append({'id': workspace.digest([dim, original])[:20], 'label': category['name'],
                                   'definition': category['definition'], 'original_ids': original})
                if len(seen)!=len(set(seen)) or set(seen)!=set(expected):
                    raise workspace.WorkspaceError('Taxonomy must account for every input label exactly once.')
                api.checkpoint_job(state,key); api.save(base,state)
            if len(parts)==1:
                output[dim] = {oid: {'name':x['label'],'definition':x['definition']} for x in merged for oid in x['original_ids']}
                break
            if len(merged) >= len(level):
                raise workspace.WorkspaceError('Taxonomy cannot fit its context bound without dropping labels; increase the configured budget or reconcile categories.')
            level = merged; round_no += 1
    api.atomic_json(home/f'taxonomy_{stage}.json', output)
    return output


def aggregate(database, records, index, tax, stage, primary=None):
    rows = eligible_rows(database); profiles = index['profiles']; groups = {}
    for dim in DIMENSIONS[stage]:
        acc = {}
        for cid, record in records.items():
            pid = index['case_to_profile'][cid]; provider = rows[cid][0].split('\n',1)[0]
            for obs in [record[dim]] if dim=='company_category' else record[dim]:
                category = tax[dim][label_id(obs)]; name = category['name']
                if dim=='company_category' and primary and primary[pid]['category']!=name: continue
                entry = acc.setdefault(name, {'name':name,'definition':category['definition'],'profiles':set(),
                    'case_ids':set(),'providers':defaultdict(set),'strengths':defaultdict(set),'examples':[],'noncounted_case_ids':set()})
                countable = dim.startswith('company_') or obs['evidence_strength'] in ('explicit','supported')
                if not countable:
                    entry['noncounted_case_ids'].add(cid); continue
                entry['profiles'].add(pid); entry['case_ids'].add(cid); entry['providers'][provider].add(pid)
                entry['strengths'][obs['evidence_strength']].add(pid)
                if len(entry['examples']) < 2:
                    entry['examples'].append({'case_id':cid,'customer':rows[cid][1],'provider':provider,
                        'url':rows[cid][0].split('\n',1)[1], 'evidence':obs['evidence'],
                        'people':obs['people'],'involvement':obs['involvement'],'strength':obs['evidence_strength']})
        entries = []
        for entry in acc.values():
            entry['profiles'] = sorted(entry['profiles']); entry['case_ids']=sorted(entry['case_ids'])
            entry['record_count']=len(entry['case_ids'])
            entry['profile_count']=len(entry['profiles']); entry['percent']=round(100*entry['profile_count']/len(profiles),2)
            entry['providers']={p:len(ids) for p,ids in sorted(entry['providers'].items())}
            entry['strengths']={p:len(ids) for p,ids in sorted(entry['strengths'].items())}
            entry['noncounted_case_ids']=sorted(entry['noncounted_case_ids']); entries.append(entry)
        groups[dim]=sorted(entries,key=lambda x:(-x['profile_count'],x['name']))
    return {'database_sha256':database['sha256'],'eligible_records':len(rows),'classified_records':len(records),
            'profiles':len(profiles),'dimensions':groups,
            'missing_stakeholder_profiles':sum(not any(o['evidence_strength'] in ('explicit','supported') for c in p['case_ids'] for o in records[c]['stakeholders']) for p in profiles.values()),
            'counting_method': index['method']}


def primary_choices(api, base, state, database, records, index, tax, timeout, cli):
    choices = {}; conflicts = []
    for pid, profile in index['profiles'].items():
        candidates = defaultdict(list)
        for cid in profile['case_ids']:
            obs=records[cid]['company_category']; name=tax['company_category'][label_id(obs)]['name']
            candidates[name].append({'case_id':cid,'evidence':obs['evidence']})
        if len(candidates)==1: choices[pid]={'category':next(iter(candidates)),'reason':'All classified cases agree.'}
        else: conflicts.append({'profile_id':pid,'customers':profile['customers'],'candidates':dict(candidates)})
    for batch in bounded(conflicts,policy(state)):
        key,obj=call(api,base,state,database,5,'resolve_company_profiles',workspace.digest(batch)[:16],{'profiles':batch},timeout,cli)
        if obj is None:return None
        expected={x['profile_id']:x for x in batch};seen=set()
        for item in obj['decisions']:
            pid=item['profile_id']
            if pid not in expected or pid in seen or item['category'] not in expected[pid]['candidates'] or not item['reason'].strip():
                raise workspace.WorkspaceError('Invalid primary company-category reconciliation.')
            seen.add(pid);choices[pid]={'category':item['category'],'reason':item['reason']}
        if seen!=set(expected):raise workspace.WorkspaceError('Primary-category reconciliation omitted a profile.')
        api.checkpoint_job(state,key);api.save(base,state)
    return choices


def table_text(agg):
    def cell(v):return str(v).replace('|','/').replace('\n',' ')
    text=[]
    for dim,entries in agg['dimensions'].items():
        text += ['## '+dim.replace('_',' ').title(), '', '| Category | Description | Profiles | Share of all profiles |',
                 '| --- | --- | ---: | ---: |']
        for e in entries:
            text.append('| '+' | '.join(map(cell,[e['name'],e['definition'],e['profile_count'],str(e['percent'])+'%']))+' |')
        text += ['', '### Evidence and provider concentration', '', '| Category | Case records | Provider counts (profiles) | Evidence strength (profiles) |',
                 '| --- | ---: | --- | --- |']
        for e in entries:
            text.append('| '+' | '.join(map(cell,[e['name'],str(e['record_count'])+(' counted; '+str(len(e['noncounted_case_ids']))+' outcome-only/unclear' if e['noncounted_case_ids'] else ''),
                '; '.join(f'{p}: {n}' for p,n in e['providers'].items()),'; '.join(f'{p}: {n}' for p,n in e['strengths'].items())]))+' |')
        text.append('')
    return '\n'.join(text)


def _step(api, base, state, database, stage, analyses, timeout, cli):
    home=root(base,database)
    if policy(state).get('taxonomy_first'):
        import taxonomy_first
        return taxonomy_first.step(api,base,state,database,stage,timeout,cli)
    if policy(state).get('global_semantic_synthesis', True):
        if not classify_step(api,base,state,database,timeout,cli):return None
        import semantic_synthesis as ss
        markdown=ss.execute(api,base,state,database,timeout,cli,bounded_execution=True)
        if markdown is None:return None
        if stage==7:return markdown
        names={4:'Buying situations',5:'Company profiles',6:'People and stakeholders'}
        match=re.search(r'^# '+re.escape(names[stage])+r'\n(.*?)(?=^# |\Z)',markdown,re.M|re.S)
        if not match:raise workspace.WorkspaceError('Global report omitted an analytical dimension.')
        return match[1].strip()
    if stage==7:
        summaries={str(n):read(home/f'aggregate_{n}.json') for n in (4,5,6)}
        concise={n:{'profiles':a['profiles'],'eligible_records':a['eligible_records'],
                    'dimensions':{d:[{k:e[k] for k in ('name','record_count','profile_count','percent','providers','strengths')} for e in es] for d,es in a['dimensions'].items()}} for n,a in summaries.items()}
        key,obj=call(api,base,state,database,7,'report_overview','overview',{'aggregates':concise},timeout,cli)
        if obj is None:return None
        if len(obj['markdown'].split())>430:raise workspace.WorkspaceError('Report overview exceeds its bounded word budget.')
        api.checkpoint_job(state,key)
        method=(f"Finalized native Google Sheet: {database['sheet']['url']}\n\n"
                f"{database['complete']} complete records; {database['unavailable']} inaccessible records; "
                f"{summaries['4']['profiles']} distinct customer profiles. Every eligible Sheet record has a persisted classification. "
                "Counts were computed in code across all classifications, never sampled. Each profile counts once per category; buying situations, characteristics and stakeholder categories can overlap. Primary company categories are exclusive and sum to the profile denominator. "
                +summaries['4']['counting_method']+" Missing information is unknown, not evidence of absence. Named customer stakeholders only enter role counts; vendor representatives, generic teams and unsupported buying authority do not. "
                "Evidence-strength groups and provider groups can overlap within a profile. Published-case frequency reflects publisher selection and concentration, not market prevalence or GTM priority. Outcome-only and unclear buying/role observations are retained in the audit but do not establish buying triggers or identifiable roles. "
                "Analysis used only the verified immutable Sheet rows; no external research.\n\n"
                '| Provider | Sheet records |\n| --- | ---: |\n'+ '\n'.join(f'| {p} | {n} |' for p,n in database['provider_counts'].items()))
        return '# Overview\n'+obj['markdown']+'\n\n# Company profiles\n'+analyses['5']['markdown']+'\n\n# People and stakeholders\n'+analyses['6']['markdown']+'\n\n# Buying situations\n'+analyses['4']['markdown']+'\n\n# Methods and sources\n'+method
    if not classify_step(api,base,state,database,timeout,cli):return None
    records=classifications(base,database);rows=eligible_rows(database)
    if set(records)!=set(rows):raise workspace.WorkspaceError('Every eligible record must have exactly one classification.')
    index=profile_index(database,records);api.atomic_json(home/'profile_index.json',index)
    if sorted(c for p in index['profiles'].values() for c in p['case_ids'])!=sorted(rows):
        raise workspace.WorkspaceError('Profile accounting omitted or duplicated records.')
    api.atomic_json(home/'coverage_audit.json',{
        'database_sha256':database['sha256'],'all_case_ids':database['case_ids'],
        'eligible_case_ids':list(rows),'inaccessible_case_ids':[c for c in database['case_ids'] if c not in rows],
        'classified_case_ids':sorted(records),'case_to_profile':index['case_to_profile'],
        'eligible_records':len(rows),'classified_records':len(records),'distinct_profiles':len(index['profiles']),
        'record_checksums':{cid:workspace.digest(record) for cid,record in records.items()}})
    if policy(state).get('transport')=='local_mcp':
        import analysis_compact
        tax=analysis_compact.final_taxonomy(api,base,state,database,stage,records,timeout,cli)
    else:tax=taxonomy(api,base,state,database,stage,records,timeout,cli)
    if tax is None:return None
    primary=primary_choices(api,base,state,database,records,index,tax,timeout,cli) if stage==5 else None
    if stage==5 and primary is None:return None
    agg=aggregate(database,records,index,tax,stage,primary)
    if stage==5 and sum(e['profile_count'] for e in agg['dimensions']['company_category'])!=len(index['profiles']):
        raise workspace.WorkspaceError('Primary company counts do not match the full profile denominator.')
    api.atomic_json(home/f'aggregate_{stage}.json',agg)
    if primary is not None:api.atomic_json(home/'primary_categories.json',primary)
    compact=[]
    for dim,entries in agg['dimensions'].items():
        for e in entries:compact.append({'dimension':dim,**{k:v for k,v in e.items() if k not in ('profiles','case_ids','noncounted_case_ids')}})
    narratives=[]
    for n,batch in enumerate(bounded(compact,policy(state),count=12)):
        key,obj=call(api,base,state,database,stage,'analysis_narrative',f'{stage}_{n}',
                     {'stage':stage,'denominator':agg['profiles'],'eligible_records':len(rows),
                      'categories':batch,'missing_stakeholder_profiles':agg['missing_stakeholder_profiles']},timeout,cli)
        if obj is None:return None
        if re.search(r'^\|.+\|\s*$',obj['markdown'],re.M):raise workspace.WorkspaceError('Narrative must not invent or duplicate authoritative frequency tables.')
        narratives.append(obj['markdown']);api.checkpoint_job(state,key);api.save(base,state)
    intro=(f"## Coverage and counting\n{len(rows)} of {len(rows)} eligible Sheet records classified; "
           f"{len(index['profiles'])} distinct customer profiles. {index['method']} "
           "Each profile counts once per category. Overlapping categories, provider groups and evidence-strength groups may sum above the denominator. "
           "Frequencies are observations among published cases, not market prevalence or commercial-priority rankings. "
           f"Profiles without identifiable named stakeholders: {agg['missing_stakeholder_profiles']}.\n\n")
    return intro+table_text(agg)+'\n\n'+'\n\n'.join(narratives)


def step(api, base, state, database, stage, analyses, timeout, cli):
    global _fresh_calls
    _fresh_calls=0
    try:return _step(api,base,state,database,stage,analyses,timeout,cli)
    except TaskYield:return None
