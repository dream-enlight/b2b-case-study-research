"""Conservative report-only title frequencies; never changes classifications."""
import re
from collections import defaultdict

# Explicit titles only. Unmatched names/activities remain unassigned, rather than
# treating a testimonial, authorship or an implementation task as a job title.
RULES={
    'Founders and general management':r'\b(?:co[- ]?founders?|founders?|CEO|(?<!vice[ -])president)\b',
    'Engineering / technology leadership':r'\b(?:CTO|Tech Lead|Head of Engineering|VP Engineering|Vice President of Engineering)\b',
    'Engineering roles':r'\bengineer\b',
    'Product leadership / management':r'\b(?:Chief Product Officer|Head of (?:Enterprise )?Product|Product (?:Manager|Lead)|Director of Product)\b',
    'Marketing / growth':r'\b(?:CMO|Chief Marketing Officer|Marketing (?:Production )?(?:Lead|Manager|Director)|(?:Head|Director|VP|AVP) of (?:Marketing|Growth)|(?:Head|Director|VP|AVP) (?:Marketing|Growth)|Growth (?:[/&] Product )?(?:Lead|Manager|Director)|Growth/Product (?:Lead|Manager|Director)|(?:User Acquisition|UA|Performance Marketing|Paid Media)(?: Senior)? (?:Manager|Lead|Director)|Director of User Acquisition)\b',
    'Operations leadership / management':r'\b(?:COO|Chief Operating Officer|Head of Operations|Operations Manager|Director of Operations)\b',
    'Technology / AI analysis':r'\bSenior Analyst\b(?=[^;]*\bTech and AI\b)',
}

# A title must precede the description of what someone did. Activities and other
# people's titles later in the sentence cannot establish this person's function.
ACTIVITY=re.compile(r'\b(?:describes?|explains?|discusses?|comments?|says?|supplies|performed|participated|reports?|quotes?|quoted|credited|named|worked|helped|implemented|evaluated|selected|led)\b',re.I)


def coverage(roles):
    return {'profiles_with_named_stakeholders':roles['profiles_with_named_people'],
            'profiles_with_identified_functions':roles['profiles_with_recognized_titles'],
            'profiles_with_only_unidentified_functions':roles['named_profiles_without_recognized_titles'],
            'profiles_without_named_stakeholders':roles['denominator']-roles['profiles_with_named_people']}

def derive(db,aggregation):
    rows=dict(zip(db['case_ids'],db['rows']));names=defaultdict(set);profiles={}
    for node in aggregation['dimensions'].get('stakeholders',[]):
        for obs in node.get('observations',[]):
            cid=obs['case_id'];pid=obs['profile_id']
            if cid not in rows:raise ValueError('Role evidence is outside the finalized database.')
            if cid in profiles and profiles[cid]!=pid:raise ValueError('Conflicting saved profile associations.')
            profiles[cid]=pid;names[cid].update(obs.get('people',[]))
    support={g:[] for g in RULES};named=set()
    for cid,people in names.items():
        cell=rows[cid][2];pid=profiles[cid]
        located=[]
        for person in people:
            match=re.search(r'(?<!\w)'+re.escape(person)+r'(?!\w)',cell,re.I)
            if match:located.append((match.start(),match.end(),person))
        if located:named.add(pid)
        located.sort()
        for i,(start,end,person) in enumerate(located):
            stop=located[i+1][0] if i+1<len(located) else len(cell)
            phrase=cell[end:stop].split(';',1)[0]
            # Stop at another sentence, retaining conventional Sr./Dr. prefixes.
            phrase=re.split(r'(?<!Sr)(?<!Dr)(?<!Mr)(?<!Ms)\.\s+',phrase,maxsplit=1,flags=re.I)[0]
            phrase=ACTIVITY.split(phrase,maxsplit=1)[0].strip(' ,—–-:')
            for group,pattern in RULES.items():
                matches=list(re.finditer(pattern,phrase,re.I))
                if matches:support[group].append({'case_id':cid,'profile_id':pid,'person':person,
                    'source_people_cell':cell,'title_phrase':phrase,'matched_terms':[m[0] for m in matches]})
    denominator=aggregation['distinct_profiles'];groups=[];union=set()
    for group,evidence in support.items():
        ids=sorted({e['profile_id'] for e in evidence});union.update(ids)
        groups.append({'group':group,'count':len(ids),'share':round(100*len(ids)/denominator,2),
                       'profile_ids':ids,'evidence':evidence})
    return {'method':'Named people with explicit title evidence in their own saved People cell; unique existing profile union per group. Generic descriptions such as principals/builders, project builder or operations builder are not formal titles. Titles do not establish involvement or authority. No cross-profile title transfer. Unmatched roles remain unassigned.',
            'denominator':denominator,'profiles_with_named_people':len(named),'profiles_with_recognized_titles':len(union),
            'named_profiles_without_recognized_titles':len(named-union),'rules':RULES,
            'groups':sorted(groups,key=lambda g:(-g['count'],g['group']))}
