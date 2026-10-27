"""Global, evidence-preserving synthesis between classification and reporting.

Classifications and profile identities are immutable inputs. A semantic map is a
separate, versioned interpretation; all frequencies are unions of underlying IDs.
No publisher frequency is ever used as a weight or a stopping criterion.
"""
import copy
import json
from collections import Counter, defaultdict
from pathlib import Path
import analysis_pipeline as ap
import workspace

VERSION = 1
DIMS = tuple(d for ds in ap.DIMENSIONS.values() for d in ds)
KINDS = ('trigger', 'goal', 'requirement', 'benefit', 'outcome', 'uncertain', 'descriptive')
# The runner has a 1,048,576-character turn/start limit independent of tokens.
# Leave room for the schema and instructions, including JSON escaping.
MAX_INPUT_BYTES = 900000


def home(base, db): return ap.root(base, db) / 'global_synthesis_v1'
def read(path): return json.loads(path.read_text())


def schema(task):
    s = {'type': 'string'}
    arr = lambda x: {'type': 'array', 'items': x}
    def obj(p): return {'type': 'object', 'properties': p, 'required': list(p), 'additionalProperties': False}
    if task == 'global_semantic_map':
        return obj({'nodes': arr(obj({'id': s, 'parent_id': s, 'name': s,
                    'definition': s, 'distinction': s, 'kind': {'type': 'string', 'enum': list(KINDS)},
                    'countable_function':{'type':'boolean'},
                    'members': arr(s)})),
                    'observation_overrides': arr(obj({'ref': s, 'kind': {'type': 'string', 'enum': list(KINDS)}, 'reason': s})),
                    'observation_annotations': arr(obj({'ref':s,'node_ids':arr(s),'evidence':s,'reason':s})),
                    'review_notes': s})
    return obj({'markdown': s})


def catalog(db, records, index, dim):
    """Full global vocabulary and EVERY observation, not a sample of batches."""
    rows = ap.eligible_rows(db); labels = {}; observations = []
    for cid in rows:
        rec = records[cid]
        for n, obs in enumerate([rec[dim]] if dim == 'company_category' else rec[dim]):
            lid = ap.label_id(obs)
            labels[lid] = {'id': lid, 'label': obs['label'], 'definition': obs['definition']}
            observations.append({'ref': cid+':'+str(n), 'case_id': cid,
                'profile_id': index['case_to_profile'][cid], 'label_id': lid,
                'customer': rows[cid][1], 'provider': rows[cid][0].split('\n')[0],
                'evidence': obs['evidence'], 'strength': obs['evidence_strength'],
                'people': obs['people'], 'involvement': obs['involvement']})
    result = {'dimension': dim, 'labels': list(labels.values()), 'observations': observations}
    # Buying motivations especially require chronology/context, not just a quote.
    if dim == 'buying_situations':
        result['sheet_context'] = {cid: rows[cid][4] for cid in rows}
    return result


def validate_map(cat, mapping):
    nodes = {n['id']: n for n in mapping['nodes']}
    if len(nodes) != len(mapping['nodes']) or (not nodes and cat['labels']):
        raise workspace.WorkspaceError('Global synthesis requires unique nonempty node IDs.')
    expected = {x['id'] for x in cat['labels']}; members = []
    for node in nodes.values():
        if not node['id'] or not node['name'].strip() or not node['definition'].strip() or node['kind'] not in KINDS:
            raise workspace.WorkspaceError('Invalid global semantic node.')
        parent = node['parent_id']
        if parent and parent not in nodes: raise workspace.WorkspaceError('Unknown semantic parent.')
        chain = {node['id']}; cur = parent
        while cur:
            if cur in chain: raise workspace.WorkspaceError('Cyclic semantic hierarchy.')
            chain.add(cur); cur = nodes[cur]['parent_id']
        members += node['members']
    if len(members) != len(set(members)) or set(members) != expected:
        raise workspace.WorkspaceError('Every original label must map exactly once globally.')
    # Every raw category survives as a named leaf/alias in the audit catalog.
    refs = {x['ref'] for x in cat['observations']}; seen = set()
    for item in mapping['observation_overrides']:
        if item['ref'] not in refs or item['ref'] in seen or item['kind'] not in KINDS or not item['reason'].strip():
            raise workspace.WorkspaceError('Invalid observation-level semantic override.')
        seen.add(item['ref'])
    if cat['dimension'] not in ('buying_situations','selection_requirements') and mapping['observation_overrides']:
        raise workspace.WorkspaceError('Evidence-kind overrides belong only to buying/capability observations.')
    if cat['dimension']=='selection_requirements' and any(x['kind'] not in ('requirement','descriptive','benefit','outcome','uncertain') for x in mapping['observation_overrides']):
        raise workspace.WorkspaceError('Capability evidence cannot be a buying trigger or goal.')
    observed={x['ref']:x for x in cat['observations']};seen=set()
    for item in mapping.get('observation_annotations',[]):
        if item['ref'] not in observed or item['ref'] in seen or not item['node_ids'] or any(n not in nodes for n in item['node_ids']) or not item['reason'].strip():
            raise workspace.WorkspaceError('Invalid evidence-specific semantic annotation.')
        if item['evidence']!=observed[item['ref']]['evidence']:
            raise workspace.WorkspaceError('Semantic annotation evidence differs from frozen Sheet observation.')
        if cat['dimension']=='company_category' and len(item['node_ids'])!=1:
            raise workspace.WorkspaceError('Primary company observations cannot receive overlapping primary types.')
        seen.add(item['ref'])
    if any(n not in nodes for n in mapping.get('unidentified_function_node_ids',[])):
        raise workspace.WorkspaceError('Unknown unidentified-function taxonomy reference.')
    return mapping


def ensure(api, base, state, db, records, index, timeout, cli, bounded_execution=False):
    h = home(base, db); maps = {}; catalogs = {}
    for dim in DIMS:
        cat = catalog(db, records, index, dim); catalogs[dim] = cat
        token = workspace.digest(cat); path = h / (dim+'.json')
        correction_path=h/(dim+'_corrections.json')
        correction_digest=workspace.digest(read(correction_path)) if correction_path.exists() else None
        if path.exists():
            saved = read(path); payload = dict(saved); checksum = payload.pop('sha256')
            if workspace.digest(payload) != checksum or saved['input_sha256'] != token:
                raise workspace.WorkspaceError('Global synthesis input/checksum mismatch.')
            if saved.get('corrections_sha256')==correction_digest:
                maps[dim] = validate_map(cat, saved['mapping']); continue
            api.atomic_json(h/'history'/(dim+'_'+checksum+'.json'),saved)
        context = {'analysis_task': 'global_semantic_map', 'dimension': dim,
                   'catalog': cat, 'database_sha256': db['sha256'],
                   'global_profile_denominator': len(index['profiles'])}
        if len(json.dumps(context, ensure_ascii=False).encode()) > MAX_INPUT_BYTES:
            raise workspace.WorkspaceError('Global semantic catalog exceeds context bound; preserve progress and explicitly configure hierarchical review. No labels were truncated.')
        key = 'global_semantic_v1_'+dim+'_'+token[:16]
        before=sum(j.get('attempts',0) for j in state.get('jobs',{}).values())
        obj = api.invoke(base, state, 4, key, context, timeout, cli)
        if obj is None: return None
        # An operator may resolve a small omission/ambiguity from saved evidence
        # without repeating a completed global review. Corrections are separate
        # versioned interpretation, never edits to source or worker responses.
        correction=None
        if correction_path.exists():
            correction=read(correction_path)
            if correction['input_sha256']!=token:raise workspace.WorkspaceError('Semantic correction targets a different catalog.')
            obj=copy.deepcopy(obj);nodes={n['id']:n for n in obj['nodes']}
            for ref in correction.get('remove_invalid_overrides',[]):
                if ref in {x['ref'] for x in cat['observations']}:
                    raise workspace.WorkspaceError('Cannot discard a valid observation override as an invalid reference.')
                obj['observation_overrides']=[x for x in obj['observation_overrides'] if x['ref']!=ref]
            for addition in correction.get('new_nodes',[]):
                if addition['id'] in nodes:raise workspace.WorkspaceError('Semantic correction duplicates a node.')
                obj['nodes'].append(addition);nodes[addition['id']]=addition
            for item in correction['assignments']:
                if not item['reason'].strip() or item['node_id'] not in nodes:raise workspace.WorkspaceError('Invalid audited semantic correction.')
                for n in nodes.values():
                    if item['label_id'] in n['members']:n['members'].remove(item['label_id'])
                nodes[item['node_id']]['members'].append(item['label_id'])
            for item in correction.get('reparent_nodes',[]):
                if item['id'] not in nodes or item['parent_id'] not in nodes or not item['reason'].strip():
                    raise workspace.WorkspaceError('Invalid audited semantic parent correction.')
                nodes[item['id']]['parent_id']=item['parent_id']
            annotations={x['ref']:x for x in obj.get('observation_annotations',[])}
            annotations.update({x['ref']:x for x in correction.get('observation_annotations',[])})
            obj['observation_annotations']=list(annotations.values())
            obj['unidentified_function_node_ids']=correction.get('unidentified_function_node_ids',obj.get('unidentified_function_node_ids',[]))
        validate_map(cat, obj)
        payload = {'version': VERSION, 'database_sha256': db['sha256'], 'input_sha256': token, 'mapping': obj}
        if correction is not None:payload['corrections_sha256']=workspace.digest(correction)
        payload['sha256'] = workspace.digest(payload); api.atomic_json(path, payload)
        api.atomic_json(h/(dim+'_catalog.json'), cat)
        api.checkpoint_job(state, key); api.save(base, state)
        maps[dim] = obj
        if bounded_execution and sum(j.get('attempts',0) for j in state.get('jobs',{}).values())>before:
            return None  # Standard runner task caps still apply to synthesis.
    return maps, catalogs


def aggregate(db, records, index, catalogs, maps, primary=None):
    """Union profile IDs at every level, including semantic-kind subsets."""
    out = {}; denominator = len(index['profiles']); primary_members = defaultdict(set);identified_roles=set()
    for dim in DIMS:
        mapping = validate_map(catalogs[dim], maps[dim]); nodes = {n['id']: n for n in mapping['nodes']}
        membership = {m:n['id'] for n in nodes.values() for m in n['members']}
        overrides = {x['ref']: x for x in mapping['observation_overrides']}
        annotations={x['ref']:x for x in mapping.get('observation_annotations',[])}
        accum = {nid: {'profiles': set(), 'case_ids': set(), 'providers': defaultdict(set),
                      'strengths': defaultdict(set), 'kinds': defaultdict(set), 'observations': []} for nid in nodes}
        for obs in catalogs[dim]['observations']:
            nid = membership[obs['label_id']]; pid = obs['profile_id']
            if dim == 'company_category' and primary:
                # Prior primary decisions refer to original normalized names.
                chosen = primary.get(pid)
                if chosen and obs['case_id'] not in chosen: continue
            destinations=annotations.get(obs['ref'],{}).get('node_ids',[nid])
            if dim=='stakeholders':
                unknown=set(mapping.get('unidentified_function_node_ids',[]))
                for destination in destinations:
                    cur=destination;countable=True
                    while cur:
                        if cur in unknown or not nodes[cur].get('countable_function',True):countable=False
                        cur=nodes[cur]['parent_id']
                    if countable:identified_roles.add(pid)
            pending=[];visited=set()
            for destination in destinations:
                kind=overrides.get(obs['ref'],{}).get('kind',nodes[destination]['kind'])
                if dim=='buying_situations':
                    if obs['strength']=='outcome_only':kind='outcome'
                    elif obs['strength']=='unclear':kind='uncertain'
                pending.append((destination,kind))
            while pending:
                cur,kind=pending.pop()
                if (cur,kind) in visited:continue
                visited.add((cur,kind))
                a = accum[cur]; a['profiles'].add(pid); a['case_ids'].add(obs['case_id'])
                a['providers'][obs['provider']].add(pid); a['strengths'][obs['strength']].add(pid)
                a['kinds'][kind].add(pid); a['observations'].append(dict(obs, semantic_kind=kind,
                    interpretation_reason=annotations.get(obs['ref'],overrides.get(obs['ref'], {})).get('reason', 'Global category definition.')))
                if nodes[cur]['parent_id']:pending.append((nodes[cur]['parent_id'],kind))
        result = []
        for nid, a in accum.items():
            node = nodes[nid]; count = len(a['profiles'])
            result.append({**node, 'profile_ids': sorted(a['profiles']), 'case_ids': sorted(a['case_ids']),
                'profile_count': count, 'percent': round(100*count/denominator, 2),
                'providers': {p:len(v) for p,v in sorted(a['providers'].items())},
                'strengths': {s:len(v) for s,v in sorted(a['strengths'].items())},
                'semantic_kinds': {k:{'profile_ids': sorted(v), 'profile_count':len(v),'percent':round(100*len(v)/denominator,2),
                    'providers':{p:len({o['profile_id'] for o in a['observations'] if o['semantic_kind']==k and o['provider']==p}) for p in sorted({o['provider'] for o in a['observations'] if o['semantic_kind']==k})},
                    'strengths':{s:len({o['profile_id'] for o in a['observations'] if o['semantic_kind']==k and o['strength']==s}) for s in sorted({o['strength'] for o in a['observations'] if o['semantic_kind']==k})}}
                    for k,v in sorted(a['kinds'].items())},
                'observations': a['observations']})
            if dim == 'company_category' and not node['parent_id']:
                for pid in a['profiles']: primary_members[pid].add(nid)
        out[dim] = sorted(result, key=lambda x:(-x['profile_count'], x['id']))
    if set(primary_members) != set(index['profiles']) or any(len(v)!=1 for v in primary_members.values()):
        raise workspace.WorkspaceError('Global primary company roots must assign each profile exactly once.')
    role_nodes=out['stakeholders'];unknown=set(maps['stakeholders'].get('unidentified_function_node_ids',[]))
    all_roles={pid for n in role_nodes for pid in n['profile_ids']}
    identified=identified_roles
    kind_sets=defaultdict(set)
    for node in out['buying_situations']:
        if node['parent_id']:continue
        for kind,value in node['semantic_kinds'].items():kind_sets[kind].update(value['profile_ids'])
    return {'version': VERSION, 'database_sha256': db['sha256'], 'eligible_records':len(records),
            'distinct_profiles':denominator, 'dimensions':out,
            'record_ids': sorted(records), 'profile_index_sha256': workspace.digest(index),
            'review_notes':{d:maps[d]['review_notes'] for d in DIMS},
            'stakeholder_coverage':{'profiles_with_named_stakeholders':len(all_roles),'profiles_with_identified_functions':len(identified),
                'profiles_with_only_unidentified_functions':len(all_roles-identified),'profiles_without_named_stakeholders':denominator-len(all_roles)},
            'buying_evidence_coverage':{k:len(v) for k,v in sorted(kind_sets.items())}}


def primary_case_choices(base, db, records, index):
    """Reuse saved exclusive choices; never majority-vote by number of stories."""
    p = ap.root(base, db)/'primary_categories.json'; chosen = read(p) if p.exists() else {}
    t = ap.root(base, db)/'taxonomy_5.json'; old = read(t)['company_category'] if t.exists() else {}
    result = {}
    for pid, profile in index['profiles'].items():
        if len(profile['case_ids']) == 1: result[pid] = profile['case_ids']; continue
        if pid not in chosen:
            # No silent tie breaking: a new run must resolve this through the
            # existing evidence-based primary_choices before synthesis.
            raise workspace.WorkspaceError('A multi-case profile needs its saved exclusive primary choice.')
        matches = [cid for cid in profile['case_ids'] if old.get(ap.label_id(records[cid]['company_category']),{}).get('name') == chosen[pid]['category']]
        if not matches: raise workspace.WorkspaceError('Saved primary decision has no classified evidence.')
        result[pid] = matches
    return result


def reconcile_primary(api, base, state, db, records, index, maps, timeout, cli):
    """Reuse historical choices, or resolve only genuinely conflicting profiles."""
    old=ap.root(base,db)/'primary_categories.json'
    if old.exists():return primary_case_choices(base,db,records,index)
    nodes={n['id']:n for n in maps['company_category']['nodes']}
    member={m:n['id'] for n in nodes.values() for m in n['members']}
    def root_name(lid):
        cur=member[lid]
        while nodes[cur]['parent_id']:cur=nodes[cur]['parent_id']
        return nodes[cur]['name']
    tax={'company_category':{lid:{'name':root_name(lid),'definition':'Global primary business group.'} for lid in member}}
    path=home(base,db)/'exclusive_primary_cases.json'
    if path.exists():return read(path)
    decisions=ap.primary_choices(api,base,state,db,records,index,tax,timeout,cli)
    if decisions is None:return None
    result={pid:[cid for cid in profile['case_ids'] if root_name(ap.label_id(records[cid]['company_category']))==decisions[pid]['category']]
            for pid,profile in index['profiles'].items()}
    api.atomic_json(path,result)
    return result


def report_context(db, agg, target=None):
    import report_roles
    dims = {}; rows=ap.eligible_rows(db)
    for dim, nodes in agg['dimensions'].items():
        dims[dim] = []; lookup={n['id']:n for n in nodes}
        for node in nodes:
            if not node['profile_count']:continue  # Empty taxonomy scaffolding has no observation to report.
            # Full hierarchy/counts, bounded diverse examples; full ledger stays local.
            examples = []; seen = set(); providers=set()
            depth=0;ancestor=node
            while ancestor['parent_id']:
                depth+=1;ancestor=lookup[ancestor['parent_id']]
            limit=4 if depth==0 else 1 if depth==1 else 0
            ordered=sorted(node['observations'], key=lambda o:(o['strength']!='explicit',o['semantic_kind']!='trigger',o['provider']!=target,o['provider'],o['case_id']))
            if agg.get('selection_evidence_kinds') and dim=='selection_requirements':
                # Show usage as well as needs within the existing example budget.
                for kind in ('descriptive','requirement'):
                    candidate=next((o for o in ordered if o['semantic_kind']==kind),None)
                    if candidate is not None and len(examples)<limit:
                        examples.append(dict(candidate,source_url=rows[candidate['case_id']][0].split('\n',1)[1]))
                        seen.add(candidate['profile_id']);providers.add(candidate['provider'])
            for diverse in (True,False):
                for obs in ordered:
                    if len(examples)>=limit:break
                    if obs['profile_id'] in seen or (diverse and obs['provider'] in providers):continue
                    seen.add(obs['profile_id']);providers.add(obs['provider'])
                    examples.append(dict(obs,source_url=rows[obs['case_id']][0].split('\n',1)[1]))
            dims[dim].append({**{k:v for k,v in node.items() if k not in ('observations','profile_ids','case_ids','members')},
                'semantic_kinds':{k:{f:v[f] for f in ('profile_count','providers','strengths') if f in v} | ({'percent':v['percent']} if 'percent' in v else {}) for k,v in node['semantic_kinds'].items()}, 'examples':examples})
    providers = Counter(row[0].split('\n')[0] for row in ap.eligible_rows(db).values())
    roles=report_roles.derive(db,agg)
    functional={k:v for k,v in roles.items() if k not in ('rules','groups')}
    functional['groups']=[{'name':g['group'],'profile_count':g['count'],'percent':g['share'],
        'title_evidence':[{'case_id':e['case_id'],'person':e['person'],'title_phrase':e['title_phrase']} for e in g['evidence'][:4]]}
        for g in roles['groups'] if g['count']]
    context={'analysis_task':'global_synthesis_report','database_sha256':db['sha256'],
            'sheet_url':db['sheet']['url'], 'eligible_cases':len(ap.eligible_rows(db)),
            'inaccessible_audit_cases':db.get('inaccessible_audit_count',db['unavailable']), 'profiles':agg['distinct_profiles'],
            'providers':dict(providers), 'global_hierarchy':dims,'global_evidence_cautions':agg.get('review_notes',{}),
            'stakeholder_coverage':report_roles.coverage(roles),'buying_evidence_coverage':agg.get('buying_evidence_coverage',{}),
            'functional_role_frequencies':functional}
    if agg.get('selection_evidence_kinds'):context['selection_evidence_kinds']=True
    return context


def report(api, base, state, db, agg, timeout, cli):
    ctx = report_context(db, agg,state.get('company'))
    ctx['target']=state.get('company','Target company')
    ctx['publication_mode']='Complete records only in the user-facing Sheet; inaccessible entries remain in the local audit ledger.' if state.get('semantic_revision') else 'Report accessible and inaccessible coverage as separately identified in the frozen snapshot.'
    ctx['counting_contract']=(
        'Primary company types are exclusive and their complete counts sum to the entire profile denominator. Only other dimensions overlap. '
        'Every parent count is a unique-profile union, not a sum. semantic_kinds.trigger counts a documented pressure/change '
        'in the saved case, including existing-customer expansions or later operational changes where noted; it is not '
        'a count of confirmed original purchases. Separate this from goals, requirements, outcomes and uncertain motives. '
        'Selection-dimension frequencies may describe stated requirements OR documented capability usage; never call '
        'all of these proven purchase-selection reasons. Explicit means the observation is stated, not that procurement causation is established. '
        'Use global_evidence_cautions to explain temporal, provider, compound-label and original-classification ambiguities.')
    product=base/'product_understanding.json'
    if product.exists():
        saved=read(product);checksum=saved.pop('sha256')
        if workspace.digest(saved)!=checksum:raise workspace.WorkspaceError('Saved product understanding checksum mismatch.')
        ctx['approved_product_context']={'summary':saved['summary'],'capabilities':[
            {'name':x['name'],'description':x['description']} for x in saved['capabilities']],
            'uncertainties':saved['uncertainties']}
    if len(json.dumps(ctx,ensure_ascii=False).encode())>MAX_INPUT_BYTES:
        raise workspace.WorkspaceError('Global report evidence exceeds its independent context budget; no categories were dropped.')
    key = 'global_report_v1_'+workspace.digest(ctx)[:16]
    obj = api.invoke(base, state, 7, key, ctx, timeout, cli)
    if obj is None: return None
    # Preserve returned work before accepting it for publication.
    draft=base/'report_drafts'/(key+'.json')
    api.atomic_json(draft,{'database_sha256':db['sha256'],'markdown':obj['markdown']})
    import report_quality, report_roles
    try:
        report_quality.validate(obj['markdown'],db,agg,report_roles.derive(db,agg),require_overview=True)
    except (workspace.WorkspaceError,ValueError,KeyError,IndexError,TypeError) as exc:
        raise workspace.WorkspaceError(f'Report reconciliation failed: {exc} Draft preserved at {draft}. Correct the report against saved aggregates before publication.') from exc
    api.checkpoint_job(state,key);api.save(base,state)
    return obj['markdown']


def validate_report(markdown):
    from report_quality import validate_neutral
    headings = [x[2:].strip() for x in markdown.splitlines() if x.startswith('# ')]
    if headings != workspace.REPORT_SECTIONS:
        raise workspace.WorkspaceError('Synthesis report must contain the five main sections in order.')
    validate_neutral(markdown)
    # A report is a selective explanation, never an exhaustive raw taxonomy dump.
    for block in markdown.split('\n\n'):
        if sum(line.startswith('|') for line in block.splitlines()) > 24 and not block.lstrip().startswith(('| Company type | What the company sells / does | Count | Share |','| Company type | What it sells / does | Count | Share |','| Requirement | Profiles | Share |')):
            raise workspace.WorkspaceError('Report table is too large; keep full taxonomy in the audit ledger.')


def execute(api, base, state, db, timeout=1500, cli='codex', bounded_execution=False):
    records=ap.classifications(base,db)
    if set(records)!=set(ap.eligible_rows(db)):
        raise workspace.WorkspaceError('Global synthesis requires every eligible saved classification.')
    index=ap.profile_index(db,records)
    existing=ap.root(base,db)/'profile_index.json'
    if existing.exists() and read(existing)!=index:
        raise workspace.WorkspaceError('Global synthesis must preserve existing profile identities.')
    api.atomic_json(existing,index)
    rows=ap.eligible_rows(db)
    api.atomic_json(ap.root(base,db)/'coverage_audit.json',{
        'database_sha256':db['sha256'],'all_case_ids':db['case_ids'],
        'eligible_case_ids':list(rows),'inaccessible_case_ids':[c for c in db['case_ids'] if c not in rows],
        'classified_case_ids':sorted(records),'case_to_profile':index['case_to_profile'],
        'eligible_records':len(rows),'classified_records':len(records),'distinct_profiles':len(index['profiles']),
        'record_checksums':{cid:workspace.digest(record) for cid,record in records.items()}})
    values=ensure(api,base,state,db,records,index,timeout,cli,bounded_execution)
    if values is None:return None
    maps,catalogs=values
    primary=reconcile_primary(api,base,state,db,records,index,maps,timeout,cli)
    if primary is None:return None
    if bounded_execution and ap._fresh_calls:return None
    agg=aggregate(db,records,index,catalogs,maps,primary)
    api.atomic_json(home(base,db)/'aggregates.json',agg)
    return report(api,base,state,db,agg,timeout,cli)
