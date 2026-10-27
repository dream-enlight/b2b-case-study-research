"""Taxonomy before mapping. All model inputs are frozen Sheet evidence.

Legacy analysis is intentionally untouched. New runs use this versioned path;
raw compact receipts stay immutable, with a separate Other-remapping overlay.
"""
import copy
import json
import re
from pathlib import Path
import analysis_pipeline as ap
import analysis_compact as ac
import semantic_synthesis as ss
import workspace as ws
import report_roles

POLICY=dict(ac.POLICY,version=3,taxonomy_first=True,taxonomy_input_bytes=180000,
            taxonomy_max_categories=60,other_review=True)
UNKNOWN='Unknown / insufficient evidence'
OTHER='Other'


def home(base,db):return ap.root(base,db)/'taxonomy_first_v1'


def schema(task):
    s={'type':'string'}
    def arr(x):return {'type':'array','items':x}
    def obj(p):return {'type':'object','properties':p,'required':list(p),'additionalProperties':False}
    if task=='taxonomy_remap':return obj({'assignments':arr(obj({'ref':s,'cat':s}))})
    evidence=obj({'id':s,'cell':{'type':'integer','minimum':1,'maximum':4},'quote':s})
    cat=obj({'dimension':{'type':'string','enum':list(ac.DIMS)},'name':s,'definition':dict(s,maxLength=800),
             'kind':{'type':'string','enum':list(ss.KINDS)},'evidence':dict(arr(evidence),minItems=1,maxItems=3)})
    return obj({'categories':arr(cat),'covered_ids':arr(s)})


def validate_categories(db,categories,limit):
    rows=ap.eligible_rows(db);seen=set()
    if len(categories)>limit:raise ws.WorkspaceError('Taxonomy exceeds compact category budget.')
    for c in categories:
        if c['dimension'] not in ac.DIMS or c['kind'] not in ss.KINDS or not c['name'].strip() or not c['definition'].strip() or not 1<=len(c['evidence'])<=3 or len(c['definition'])>800:
            raise ws.WorkspaceError('Taxonomy requires meaningful source-grounded definitions.')
        key=(c['dimension'],c['name'].casefold())
        if key in seen or c['name'] in (OTHER,UNKNOWN):raise ws.WorkspaceError('Duplicate/reserved taxonomy category.')
        seen.add(key)
        for e in c['evidence']:
            if e['id'] not in rows or type(e['cell']) is not int or not 1<=e['cell']<=4 or not e['quote'] or e['quote'] not in rows[e['id']][e['cell']]:
                raise ws.WorkspaceError('Taxonomy evidence is not a frozen Sheet quote.')
    return categories


def build(api,base,state,db,items,label,timeout,cli):
    """Hierarchical synthesis: every input accounted for, every leaf saved on disk.

    Intermediate themes carry exact record-linked examples. No growing registry
    is appended to mapping prompts. Refuse non-contracting oversized synthesis.
    """
    settings=ap.policy(state);bound=settings.get('taxonomy_input_bytes',180000)
    level=items;round_no=0
    while level:
        parts=list(ap.bounded(level,dict(batch_size=1000000,max_input_bytes=bound)))
        merged=[]
        for n,part in enumerate(parts):
            token=ws.digest([label,round_no,part])[:20]
            key,obj=ap.call(api,base,state,db,4,'taxonomy_build',token,
                {'purpose':label,'inputs':part,'input_ids':[x['id'] for x in part],
                 'max_categories':settings.get('taxonomy_max_categories',60),
                 'contract':'Account for every input ID. Derive recurring business themes from all evidence. Distinguish triggers, goals, requirements, adoption context, benefits and outcomes. Retain exact record/cell quotes. No invented profiles or authority. Missing evidence is unknown. Return compact definitions, no essays. Merge proposals globally across all batches; preserve distinctions in definitions. Other remains available later; do not create singleton bins merely for coverage.'},timeout,cli)
            if obj is None:return None
            if sorted(obj['covered_ids'])!=sorted(x['id'] for x in part):raise ws.WorkspaceError('Taxonomy omitted/duplicated input identities.')
            validate_categories(db,obj['categories'],settings.get('taxonomy_max_categories',60))
            # Reject valid-but-unassigned citations, even if they exist in the database.
            allowed={(e['id'],e['cell'],e['quote']) for x in part for e in x.get('evidence',[])}
            raw={x['id']:x['cells'] for x in part if 'cells' in x}
            for c in obj['categories']:
                for e in c['evidence']:
                    if (e['id'],e['cell'],e['quote']) not in allowed and not (e['id'] in raw and e['quote'] in raw[e['id']][e['cell']]):
                        raise ws.WorkspaceError('Taxonomy citation outside assigned evidence.')
            api.atomic_json(home(base,db)/label/f'{round_no}_{n}.json',{'input_sha256':ws.digest(part),'input_ids':obj['covered_ids'],'categories':obj['categories']})
            apikey=key;api.checkpoint_job(state,apikey);api.save(base,state)
            merged.extend(dict(c,id=ws.digest([round_no,n,j,c])[:16]) for j,c in enumerate(obj['categories']))
        if len(parts)==1:return [{k:v for k,v in c.items() if k!='id'} for c in merged]
        if len(json.dumps(merged).encode())>=len(json.dumps(level).encode()):
            raise ws.WorkspaceError('Hierarchical taxonomy did not contract within context budget; no evidence silently discarded.')
        level=merged;round_no+=1
    return []


def prepare(api,base,state,db,timeout,cli):
    if (ac.home(base,db)/'registry.json').exists():
        reg=ac.registry(base,db)
        if not reg.get('taxonomy_first'):raise ws.WorkspaceError('Taxonomy-first requires a fresh analysis namespace; legacy receipts remain immutable.')
        return True
    categories=build(api,base,state,db,[{'id':cid,'cells':row} for cid,row in ap.eligible_rows(db).items()],'initial',timeout,cli)
    if categories is None:return False
    cats={}
    for c in categories:
        cid=ac.category_id(c['dimension'],c['name'],c['definition']);cats[cid]=dict(c,origin='global')
    for dim in ac.DIMS:
        for name in (OTHER,UNKNOWN):
            definition=('Meaningful evidence outside established categories; retain its specific description.' if name==OTHER else 'Available Sheet evidence cannot establish this dimension.')
            cid=ac.category_id(dim,name,definition);cats[cid]={'dimension':dim,'name':name,'definition':definition,'kind':'uncertain','origin':'fallback'}
    ac.save_registry(base,db,{'database_sha256':db['sha256'],'taxonomy_first':True,'categories':cats,
                            'legacy_case_ids':[],'legacy_map':{d:{} for d in ac.DIMS}},api.atomic_json)
    return True


def review_other(api,base,state,db,raw,timeout,cli):
    path=home(base,db)/'other_overlay.json'
    if path.exists():return ac.read(path)
    reg=ac.registry(base,db);rows=ap.eligible_rows(db);others=[]
    for cid,r in raw.items():
        for n,o in enumerate(r['observations']):
            c=reg['categories'][o['cat']]
            if c['name']!=OTHER:continue
            ref=o['evidence_ref'];q=rows[cid][ref['cell']][ref['start']:ref['end']]
            others.append({'id':cid+':'+str(n),'dimension':c['dimension'],'detail':o['detail'],
                           'kind':o.get('kind','uncertain'),'evidence':[{'id':cid,'cell':ref['cell'],'quote':q}]})
    if not others:
        api.atomic_json(path,{});return {}
    themes=build(api,base,state,db,others,'other_review',timeout,cli)
    if themes is None:return None
    # Additional themes are separate from the immutable original registry/receipts.
    cats={ac.category_id(c['dimension'],c['name'],c['definition']):c for c in themes}
    overlay={};settings=ap.policy(state)
    for batch in ap.bounded(others,settings):
        key,obj=ap.call(api,base,state,db,4,'taxonomy_remap',ws.digest(batch)[:16],
                       {'observations':batch,'categories':cats,'contract':'Map only evidence that fits a theme. Use cat=Other for the rest. Exactly one assignment per ref; never force-fit.'},timeout,cli)
        if obj is None:return None
        lookup={x['id']:x for x in batch};seen=set()
        for a in obj['assignments']:
            ref=a['ref'];cat=a['cat']
            if ref not in lookup or ref in seen or (cat!=OTHER and (cat not in cats or cats[cat]['dimension']!=lookup[ref]['dimension'])):
                raise ws.WorkspaceError('Invalid focused Other remapping.')
            seen.add(ref)
            if cat!=OTHER:overlay[ref]=cats[cat]
        if seen!=set(lookup):raise ws.WorkspaceError('Other review omitted observations.')
        api.checkpoint_job(state,key);api.save(base,state)
    api.atomic_json(path,overlay);return overlay


def execute(api,base,state,db,timeout,cli):
    reportpath=home(base,db)/'report.json'
    if reportpath.exists():return ac.read(reportpath)['markdown']
    if not ac.classify_step(api,base,state,db,timeout,cli):return None
    auditpath=home(base,db)/'aggregation.json'
    if auditpath.exists():agg=ac.read(auditpath)
    else:
        reg=ac.registry(base,db);rows=ap.eligible_rows(db)
        audit=home(base,db)/'classification_audit.json'
        if audit.exists():
            saved=ac.read(audit);checksum=saved.pop('sha256')
            if ws.digest(saved)!=checksum or saved['database_sha256']!=db['sha256']:raise ws.WorkspaceError('Classification audit identity mismatch.')
            records=saved['records'];raw=saved['raw']
        else:
            records=ap.classifications(base,db)
            if set(records)!=set(rows):raise ws.WorkspaceError('Final classification coverage mismatch.')
            for r in records.values():ap.validate_record(db,rows,r,rows=rows)
            raw={p.stem:ac.read(p)['record'] for p in (ac.home(base,db)/'records').glob('*.json')}
            saved={'database_sha256':db['sha256'],'records':records,'raw':raw,'case_ids':sorted(records),'receipt_sha256':{p.stem:ac.read(p)['sha256'] for p in (ac.home(base,db)/'records').glob('*.json')}}
            api.atomic_json(audit,dict(saved,sha256=ws.digest(saved)))
        overlay=review_other(api,base,state,db,raw,timeout,cli)
        if overlay is None:return None
        # Apply focused reinterpretations only in a derived view; original receipts remain immutable.
        for cid,r in raw.items():
            offsets={d:0 for d in ac.DIMS}
            for n,o in enumerate(r['observations']):
                dim=reg['categories'][o['cat']]['dimension'];pos=offsets[dim];offsets[dim]+=1
                if cid+':'+str(n) in overlay:
                    chosen=overlay[cid+':'+str(n)]
                    obs=records[cid][dim] if dim=='company_category' else records[cid][dim][pos]
                    obs.update(label=chosen['name'],definition=chosen['definition'])
        index=ap.profile_index(db,records);catalogs={};maps={}
        for dim in ac.DIMS:
            catalogs[dim]=ss.catalog(db,records,index,dim);nodes={};annotations=[];overrides=[]
            observations={o['ref']:o for o in catalogs[dim]['observations']}
            for cid,r in raw.items():
                dn=0
                for n,o in enumerate(r['observations']):
                    c=reg['categories'][o['cat']]
                    if c['dimension']!=dim:continue
                    chosen=overlay.get(cid+':'+str(n),c);ref=cid+':'+str(dn);dn+=1
                    nid=ac.category_id(dim,chosen['name'],chosen['definition'])
                    node=nodes.setdefault(nid,{'id':nid,'parent_id':'','name':chosen['name'],'definition':chosen['definition'],
                        'distinction':'Unknown is missing evidence; Other retains meaningful unmatched evidence in audit.',
                        'kind':chosen.get('kind','uncertain'),'countable_function':chosen['name'] not in (OTHER,UNKNOWN) and not (dim=='stakeholders' and re.search(r'\b(?:evaluation|selection|implementation|testimonial|authorship|unknown)\b',chosen['name'],re.I)),'members':[]})
                    original=observations[ref]
                    # Shared original labels may be remapped differently: annotations preserve exact associations.
                    annotations.append({'ref':ref,'node_ids':[nid],'evidence':original['evidence'],'reason':o.get('detail','Global taxonomy mapping.') or 'Global taxonomy mapping.'})
                    if dim in ('buying_situations','selection_requirements'):overrides.append({'ref':ref,'kind':'uncertain' if c['name']==UNKNOWN else o.get('kind',chosen.get('kind','uncertain')),'reason':'Evidence kind retained during mapping.'})
            # A catalog label needs one audit owner; annotations own actual evidence membership.
            for label in catalogs[dim]['labels']:
                owner=next((n for n in nodes.values() if n['name']==label['label']),next(iter(nodes.values())))
                owner['members'].append(label['id'])
            maps[dim]={'nodes':list(nodes.values()),'observation_annotations':annotations,'observation_overrides':overrides,'review_notes':'Whole-dataset taxonomy precedes mapping. Other observations reviewed once; Unknown is not evidence of absence.'}
        primary=ss.reconcile_primary(api,base,state,db,records,index,maps,timeout,cli)
        if primary is None:return None
        agg=ss.aggregate(db,records,index,catalogs,maps,primary)
        agg['selection_evidence_kinds']=True
        agg['stakeholder_coverage']=report_roles.coverage(report_roles.derive(db,agg))
        api.atomic_json(home(base,db)/'profile_index.json',index)
        api.atomic_json(home(base,db)/'maps.json',maps)
        api.atomic_json(auditpath,agg)
    if ap._fresh_calls:raise ap.TaskYield()
    markdown=ss.report(api,base,state,db,agg,timeout,cli)
    if markdown is not None:api.atomic_json(reportpath,{'database_sha256':db['sha256'],'markdown':markdown})
    return markdown


def step(api,base,state,db,stage,timeout,cli):
    markdown=execute(api,base,state,db,timeout,cli)
    if markdown is None or stage==7:return markdown
    name={4:'Buying situations',5:'Company profiles',6:'People and stakeholders'}[stage]
    match=re.search(r'^# '+re.escape(name)+r'\n(.*?)(?=^# |\Z)',markdown,re.M|re.S)
    if not match:raise ws.WorkspaceError('Report missing '+name)
    return match[1].strip()
