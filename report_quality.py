"""Bounded editorial checks against existing, immutable report aggregates."""
import re
import workspace as ws
import synthesis_publication as native

def validate_neutral(markdown):
    """Reject explicit report advice; attributed customer decisions stay valid."""
    cleaned=re.sub(r'(?m)^#{1,6}\s+','',markdown)
    for phrase in ('gtm implication','people to engage','practical job titles for outreach',
                   'qualification implication','question to resolve','prospecting and qualification hypotheses',
                   'best segment to target','people to contact first','recommended positioning'):
        if phrase in cleaned.casefold():raise ws.WorkspaceError('Report contains strategic/advisory framing: '+phrase)
    imperative=r'(?:^|(?<=[.!?])\s+)(?:Prioriti[sz]e|Engage|Qualify|Ask|Validate|Lead with|Start with|Approach|Contact|Position|Sell)\s'
    prescriptions=r'\b(?:deserve[s]? higher priority|(?:should|must) (?:target|prioriti[sz]e|engage|sell|position|ask|approach|be (?:contacted|prioriti[sz]ed|targeted))|for a prospect, measure)\b'
    targeting=r'(?m)^Target (?:software teams|companies|prospects|customers)\b'
    if re.search(imperative,cleaned,re.I|re.M) or re.search(prescriptions,cleaned,re.I) or re.search(targeting,cleaned,re.I):
        raise ws.WorkspaceError('Report contains a business recommendation rather than a descriptive finding.')
    return True

def validate(markdown,db,aggregation,roles,*,require_overview=False):
    import semantic_synthesis
    from collections import Counter
    semantic_synthesis.validate_report(markdown)
    # Historical snapshots may also contain explicitly inaccessible audit rows.
    rows=[r for r in db['rows'] if not r[4].startswith('INACCESSIBLE — ')]
    if len(rows)!=aggregation['eligible_records'] or roles['denominator']!=aggregation['distinct_profiles']:
        raise ws.WorkspaceError('Editorial evidence denominators disagree.')
    denominator=aggregation['distinct_profiles'];_,_,tables=native.parse_markdown(markdown)
    claims={}
    def table(prefix):
        found=[t['rows'][1:] for t in tables if t['rows'][0][:len(prefix)]==prefix]
        if len(found)!=1:raise ws.WorkspaceError('Missing/duplicate editorial table: '+str(prefix))
        labels=[r[0] for r in found[0]]
        if len(labels)!=len(set(labels)):raise ws.WorkspaceError('Duplicate report rows: '+str(prefix))
        return found[0]
    def share(value,expected,label):
        raw=value.rstrip('%')
        try:
            reported=float(raw);precision=len(raw.split('.')[1]) if '.' in raw else 0
        except ValueError:raise ws.WorkspaceError('Invalid percentage for '+label+': '+value)
        actual=100*expected/denominator if denominator else 0
        if not 0<=reported<=100 or abs(reported-actual)>.5*10**(-precision)+1e-7:
            raise ws.WorkspaceError(f'Report share for {label}: got {value}; expected {expected}/{denominator} ({actual:.2f}%).')
    def count(row,index,expected):
        try:reported=int(row[index])
        except ValueError:raise ws.WorkspaceError('Invalid count for '+row[0]+': '+row[index])
        if reported!=expected:raise ws.WorkspaceError(f'Report count for {row[0]}: got {reported}; expected {expected}.')
        share(row[index+1],expected,row[0])
        claims.setdefault(row[0],set()).add(expected)
    dims={dim:{n['name']:n for n in nodes if not n.get('parent_id')} for dim,nodes in aggregation['dimensions'].items()}
    all_dims={dim:{n['name']:n for n in nodes} for dim,nodes in aggregation['dimensions'].items()}
    def node(dim,name):
        if name not in all_dims.get(dim,{}):raise ws.WorkspaceError('Report category not found in saved '+dim+': '+name)
        return all_dims[dim][name]
    primary=table(['Company type']);seen=set()
    for row in primary:
        if row[0]=='Total':count(row,2,denominator);continue
        name='Other' if row[0].startswith('Other,') else row[0]
        if name not in dims['company_category'] or name in seen:raise ws.WorkspaceError('Invalid primary company partition.')
        seen.add(name);count(row,2,dims['company_category'][name]['profile_count'])
    if not {n for n,v in dims['company_category'].items() if v['profile_count']}<=seen or sum(int(r[2]) for r in primary if r[0]!='Total')!=denominator:
        raise ws.WorkspaceError('Primary company categories do not reconcile to the profile denominator.')
    grouped={g['group']:g for g in roles['groups']}
    role_rows=table(['Functional role group','Representative actual titles','Count'])
    if not {g for g,v in grouped.items() if v['count']}<={r[0] for r in role_rows}<=set(grouped):raise ws.WorkspaceError('Functional title groups differ from the derived audit.')
    for row in role_rows:count(row,2,grouped[row[0]]['count'])
    for row in table(['Recurring situation','Business significance','Profiles']):
        name='Other' if row[0]=='Staff absence creating reporting need' else row[0]
        item=node('buying_situations',name);count(row,2,item.get('semantic_kinds',{}).get('trigger',{}).get('profile_count',0))
    for row in table(['Deployment context','Profiles']):count(row,1,node('buying_situations',row[0])['profile_count'])
    capability_rows=table(['Requirement','Profiles']);seen_usage=set()
    for row in capability_rows:
        if aggregation.get('selection_evidence_kinds'):
            prefix,separator,name=row[0].partition(': ')
            kinds={'Stated requirement':'requirement','Documented use':'descriptive'}
            if not separator or prefix not in kinds:
                raise ws.WorkspaceError('Capability rows must distinguish stated requirements from documented use.')
            item=node('selection_requirements',name)
            expected=item.get('semantic_kinds',{}).get(kinds[prefix],{}).get('profile_count',0)
            if not expected:raise ws.WorkspaceError('Capability row has no evidence of the stated kind: '+row[0])
            count(row,1,expected)
            if prefix=='Documented use':seen_usage.add(name)
        else:
            name='Reliable real-time execution and synchronization' if row[0]=='Reliable execution and synchronization' else row[0]
            count(row,1,node('selection_requirements',name)['profile_count'])
    if aggregation.get('selection_evidence_kinds'):
        required_usage={n['name'] for n in aggregation['dimensions']['selection_requirements']
                        if n.get('semantic_kinds',{}).get('descriptive',{}).get('profile_count',0)}
        if not required_usage<=seen_usage:raise ws.WorkspaceError('Report omits documented capability usage frequencies.')
    for row in table(['Reported outcome','Profiles']):
        item=node('buying_situations',row[0])
        expected=item.get('semantic_kinds',{}).get('outcome',{}).get('profile_count',0) if aggregation.get('selection_evidence_kinds') else item['profile_count']
        count(row,1,expected)
    providers=Counter(r[0].split('\n',1)[0].casefold() for r in rows)
    coverage=table(['Provider','Eligible case entries'])
    if {r[0].casefold() for r in coverage if r[0]!='Total'}!=set(providers):raise ws.WorkspaceError('Provider coverage differs.')
    for row in coverage:
        expected=len(rows) if row[0]=='Total' else providers[row[0].casefold()]
        if int(row[1])!=expected:raise ws.WorkspaceError(f'Provider count for {row[0]}: got {row[1]}; expected {expected}.')
    # Machine-checkable summary claims use the same labels as the detailed
    # tables; the prose surrounding them remains free descriptive interpretation.
    overview=re.split(r'^# Company profiles\s*$',markdown,maxsplit=1,flags=re.M)[0]
    overview=re.sub(r'[*`]', '',overview)
    totals={'Eligible cases':len(rows),'Preserved profiles':denominator,'Providers':len(providers),
            'Inaccessible cases':db.get('inaccessible_audit_count',db.get('unavailable',0))}
    coverage_labels={'Named stakeholder profiles':'profiles_with_named_people',
                     'Identified function profiles':'profiles_with_recognized_titles',
                     'Named profiles with unknown function':'named_profiles_without_recognized_titles'}
    for label,key in coverage_labels.items():
        if key in roles:
            values=re.findall(re.escape(label)+r':\s*(\d+)\b',overview,re.I)
            if any(int(v)!=roles[key] for v in values):raise ws.WorkspaceError('Overview functional coverage differs: '+label)
    for label,expected in totals.items():
        values=re.findall(re.escape(label)+r':\s*(\d+)\b',overview,re.I)
        if require_overview and not values:raise ws.WorkspaceError('Overview missing verifiable coverage figure: '+label+': N.')
        if any(int(v)!=expected for v in values):raise ws.WorkspaceError(f'Overview {label}: expected {expected}; got {values}.')
    for label,n,pct in re.findall(r'(?m)(?:^|[;.!?]\s*|\n)\s*([^\n:;.!?]+):\s*(\d+)\s*\(([\d.]+%)\)',overview):
        label=label.strip()
        if label not in claims or len(claims[label])!=1 or int(n) not in claims[label]:
            raise ws.WorkspaceError('Overview count has no unambiguous supporting table row: '+label+': '+n)
        share(pct,int(n),'Overview '+label)
    refs=set(re.findall(r'`([a-f0-9]{16})`',markdown))
    if not refs<=set(db['case_ids']):raise ws.WorkspaceError('Report cites a record outside the verified database.')
    if any('testimonial' in r[0].lower() or 'author' in r[0].lower() for r in role_rows):raise ws.WorkspaceError('Evidence relationships leaked into functional role frequencies.')
    return {'eligible_cases':len(rows),'inaccessible_audit_cases':db.get('inaccessible_audit_count',db.get('unavailable',0)),
            'profiles':denominator,'tables_checked':len(tables),'record_references_checked':sorted(refs),
            'functional_title_coverage':roles['profiles_with_recognized_titles']}
