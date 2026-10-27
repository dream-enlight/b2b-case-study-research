"""Deterministic, contract-valid editorial output for offline test workers."""


def markdown(ctx):
    def table(header,rows):
        return '\n'.join(['| '+' | '.join(header)+' |','|'+'|'.join('---' for _ in header)+'|']+
                         ['| '+' | '.join(map(str,row))+' |' for row in rows])
    dims=ctx['global_hierarchy'];den=ctx['profiles'];coverage=ctx.get('stakeholder_coverage',{})
    overview=(f"Eligible cases: {ctx['eligible_cases']}; Preserved profiles: {den}; "
              f"Providers: {len(ctx['providers'])}; Inaccessible cases: {ctx.get('inaccessible_audit_cases',0)}.\n"
              'Company profiles. People involved. Buying situations. Caveat: synthetic offline evidence.')
    if coverage:
        overview+=('\nNamed stakeholder profiles: '+str(coverage['profiles_with_named_stakeholders'])+
                   '; Identified function profiles: '+str(coverage['profiles_with_identified_functions'])+
                   '; Named profiles with unknown function: '+str(coverage['profiles_with_only_unidentified_functions'])+'.')
    company=table(['Company type','What it sells / does','Count','Share'],
        [[n['name'],n.get('definition','Saved evidence'),n['profile_count'],str(n['percent'])+'%']
         for n in dims['company_category'] if n['profile_count'] and not n.get('parent_id')])
    people=table(['Functional role group','Representative actual titles','Count','Share'],
        [[g['name'],g['title_evidence'][0]['title_phrase'],g['profile_count'],str(g['percent'])+'%']
         for g in ctx.get('functional_role_frequencies',{}).get('groups',[])])
    capabilities=[]
    for n in dims['selection_requirements']:
        if ctx.get('selection_evidence_kinds'):
            for prefix,kind in [('Stated requirement','requirement'),('Documented use','descriptive')]:
                k=n['semantic_kinds'].get(kind,{})
                if k.get('profile_count'):capabilities.append([prefix+': '+n['name'],k['profile_count'],str(k['percent'])+'%'])
        elif n['profile_count']:capabilities.append([n['name'],n['profile_count'],str(n['percent'])+'%'])
    triggers=[];contexts=[];outcomes=[]
    for n in dims['buying_situations']:
        kinds=n.get('semantic_kinds',{});trigger=kinds.get('trigger',{});outcome=kinds.get('outcome',{})
        if trigger.get('profile_count'):triggers.append([n['name'],n.get('definition','Saved constraint'),trigger['profile_count'],str(trigger['percent'])+'%'])
        if kinds.get('descriptive',{}).get('profile_count'):contexts.append([n['name'],n['profile_count'],str(n['percent'])+'%'])
        if outcome.get('profile_count'):
            count=outcome['profile_count'] if ctx.get('selection_evidence_kinds') else n['profile_count']
            outcomes.append([n['name'],count,str(round(100*count/den,2))+'%'])
    buying='\n\n'.join([table(['Recurring situation','Business significance','Profiles','Share'],triggers),
        table(['Deployment context','Profiles','Share'],contexts),table(['Requirement','Profiles','Share'],capabilities),
        table(['Reported outcome','Profiles','Share'],outcomes)])
    methods=table(['Provider','Eligible case entries'],list(ctx['providers'].items()))
    return '\n\n'.join('# '+name+'\n'+body for name,body in zip(
        ['Overview','Company profiles','People and stakeholders','Buying situations','Methods and sources'],
        [overview,company,people,buying,methods]))
