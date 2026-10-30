#!/usr/bin/env python3
"""Read-only comparison of saved assignments; no model, network or run writes."""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import research
import runner


def byte_size(value):return len(json.dumps(value,ensure_ascii=False).encode())


def compare(path):
    old=path.read_text()
    context=json.JSONDecoder().raw_decode(old.split('TASK ASSIGNMENT (machine generated):',1)[1].lstrip())[0]
    if not context.get('efficient_worker'):raise ValueError('Expected an efficient research assignment: '+str(path))
    before=byte_size(context);projected=research.model_context(context)
    old_scopes=dict(context.get('competing_products',{}))
    for case in context.get('review_cases',context.get('assigned_cases',[])):
        if case.get('competing_product'):old_scopes[case['provider']]=case['competing_product']
    if context.get('competing_product'):old_scopes[context.get('approved_provider','')]=context['competing_product']
    new_scopes=dict(projected.get('competing_products',{}))
    if projected.get('competing_product'):new_scopes[projected.get('approved_provider','')]=projected['competing_product']
    evidence_before=context.get('evidence_memory',{}).get('sources',{})
    evidence_after=projected.get('evidence_memory',{}).get('sources',{})
    stage=3 if context['task']=='extract_batch' else 2
    new=runner.prompt_for(stage,context)
    return {'saved_prompt':str(path),'saved_prompt_sha256':hashlib.sha256(old.encode()).hexdigest(),'task':context['task'],'url_resolution':bool(context.get('url_recovery')),
            'assigned_cases':len(context.get('recovery_slots',context.get('review_cases',context.get('assigned_cases',[])))),
            'witnessed_entries_before':len(context.get('selected_listing_entries',[])),
            'prompt_bytes_before':len(old.encode()),'prompt_bytes_after':len(new.encode()),
            'prompt_reduction_percent':round(100*(1-len(new.encode())/len(old.encode())),1),
            'assignment_bytes_before':before,'assignment_bytes_after':byte_size(projected),
            'fields_before':{k:byte_size(v) for k,v in context.items()},
            'fields_after':{k:byte_size(v) for k,v in projected.items()},
            'scope_and_identity_checks':{
                'approved_scopes_preserved':all(scope==old_scopes.get(provider) for provider,scope in new_scopes.items()),
                'retained_source_text_and_associations_unchanged':all(all(capture.get(k)==evidence_before.get(url,{}).get(k) for k in ('text','listing_association','resolved_url','canonical_url')) for url,capture in evidence_after.items()),
                'saved_prompt_unchanged':path.read_text()==old,
                'approved_provider_preserved':context.get('approved_provider')==projected.get('approved_provider'),
                'recovery_identities_preserved':all(all(row[k]==newrow[k] for k in ('listing_position','listing_url','title','customer'))
                    for row,newrow in zip(context.get('recovery_slots',[]),projected.get('recovery_slots',[]))),
                'assigned_case_ids_preserved':[c['id'] for c in context.get('review_cases',context.get('assigned_cases',[]))]==[
                    c['id'] for c in projected.get('review_cases',projected.get('assigned_cases',[]))],
                'target_workflow_preserved':not context.get('product_understanding') or projected['target_scope']['workflow']==context['product_understanding']['core_workflow'],
                'uncertainties_preserved':not context.get('product_understanding') or projected['target_scope']['uncertainties']==context['product_understanding'].get('uncertainties',[]),
            }}


def session_summary(path):
    counts={'exec_calls':0,'literal_print_only_exec_calls':0,'literal_print_only_inputs':[]}
    pattern=re.compile(r'\s*(?://[^\n]*\n\s*)*text\(("(?:[^"\\]|\\.)*")\);?\s*')
    for line in path.open():
        event=json.loads(line);item=event.get('payload',{})
        if event.get('type')!='response_item' or item.get('type')!='custom_tool_call' or item.get('name')!='exec':continue
        counts['exec_calls']+=1;code=item.get('input','')
        if pattern.fullmatch(code):
            counts['literal_print_only_exec_calls']+=1;counts['literal_print_only_inputs'].append(code)
    return counts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('prompts',type=Path,nargs='+');parser.add_argument('--session',type=Path)
    args=parser.parse_args()
    result={'measurement':'UTF-8 prompt and JSON assignment bytes; not tokens, billed usage, or a live execution benchmark',
            'assignments':[compare(path) for path in args.prompts]}
    if args.session:result['saved_session']=session_summary(args.session)
    print(json.dumps(result,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
