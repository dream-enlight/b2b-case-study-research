#!/usr/bin/env python3
"""Offline fake CLI to test orchestration without contacting any model."""
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
if not args or args[0]!='exec':sys.exit(2)
prompt=sys.stdin.read()
out=Path(args[args.index('--output-last-message')+1])
mode=os.getenv('FAKE_MODE','ok')
if os.getenv('FAKE_TRACE'):
 with open(os.environ['FAKE_TRACE'],'a') as f:f.write(json.dumps({'args':args,'prompt':prompt,'cwd':os.getcwd()})+'\n')
print(json.dumps({'type':'thread.started','thread_id':'fake'}),flush=True)
if mode in ('generic429_warning_1','generic429_warning_2'):
 warnings=json.loads((Path(__file__).parent/'fixtures/codex_429_warnings.json').read_text())
 sys.stderr.write(warnings[int(mode[-1])-1]);sys.stderr.flush()
 import time
 time.sleep(2)
 if os.getenv('FAKE_RETRY_MARKER'):Path(os.environ['FAKE_RETRY_MARKER']).write_text('Runner failed to stop before a retry.')
 sys.exit(1)
if mode=='rate_limit_event':
 print(json.dumps({'type':'error','error':{'code':'rate_limit_exceeded','message':'Too many requests'}}),flush=True)
 sys.exit(1)
if mode=='retry_warning':
 print('WARN codex_core::responses_retry: stream disconnected - retrying sampling request (1/5 in 0.1s)... sampling_error=connection reset by peer',file=sys.stderr,flush=True)
if mode in ('quota','quota_hang','quota_hit'):
 print(json.dumps({'type':'error','error':{'codexErrorInfo':'UsageLimitExceeded','message':'You\u2019ve hit your usage limit.' if mode=='quota_hit' else 'Usage limit reached; resets in an hour'}}),flush=True)
 print(json.dumps({'type':'turn.failed'}),flush=True)
 if mode=='quota_hang':
  import time
  time.sleep(120)
 sys.exit(1)
if mode=='offline':
 print(json.dumps({'type':'error','error':{'message':'Connection refused'}}),flush=True)
 sys.exit(1)
task=prompt.split('TASK ASSIGNMENT (machine generated):\n')[1].split('\n\nRUNNER EXECUTION OVERRIDE:')[0]
assign=json.loads(task)
streamed=[]
original_print=print
def print(*values,**kwargs):
 if assign.get('compact_receipts') and len(values)==1 and isinstance(values[0],str):
  try:
   event=json.loads(values[0]);item=event.get('item',{})
   if event.get('type')=='item.completed' and item.get('type')=='agent_message':
    rem=item.get('text','').lstrip();decoder=json.JSONDecoder()
    while rem:
     obj,end=decoder.raw_decode(rem)
     for field in ('discovered_case','case_result','extracted_record'):
      if field in obj:streamed.append((field,obj[field]))
     rem=rem[end:].lstrip()
  except (ValueError,TypeError):pass
 return original_print(*values,**kwargs)
def fixture_record(case):
 return {'provider':case['provider'],'source_url':case['url'],'customer':case.get('customer','Acme'),'people':'Chris — CTO, quoted about evaluation','company_profile':'A B2B application vendor.','buying_situation':'The vendor needed to integrate its customer workflow with external systems; its previous manual approach could not scale.','status':'complete','note':''}
if 'ANALYSIS response JSON schema:' in prompt:
 task=assign['analysis_task']
 if task=='taxonomy_build':
  categories=[]
  inputs=assign['inputs']
  if inputs and 'cells' in inputs[0]:
   for dim,col in [('company_category',3),('stakeholders',2),('buying_situations',4)]:
    item=inputs[0]
    categories.append({'dimension':dim,'name':'Synthetic '+dim,'definition':'Synthetic business theme '+dim,'kind':'descriptive','evidence':[{'id':item['id'],'cell':col,'quote':item['cells'][col]}]})
  else:
   grouped={}
   for item in inputs:
    if 'name' in item:grouped.setdefault(item['dimension'],{k:v for k,v in item.items() if k!='id'})
   categories=list(grouped.values())
  obj={'categories':categories,'covered_ids':assign['input_ids']}
 elif task=='taxonomy_remap':obj={'assignments':[{'ref':o['id'],'cat':'Other'} for o in assign['observations']]}
 elif task=='classify_records':
  def obs(label,evidence,people=[]):
   return {'label':label,'definition':'Synthetic '+label,'evidence':evidence,'evidence_strength':'explicit','people':people,'involvement':'Quoted; final purchasing authority unavailable.'}
  records=[]
  for i,item in enumerate(assign['records']):
   cells=item['cells']
   row={'id':item['id'],'anonymous':cells[1].lower() in ('unknown','anonymous'),'aliases':[], 'identity_note':'Synthetic identity.',
        'buying_situations':[obs('Workflow integration',cells[4])], 'selection_requirements':[],
        'company_category':obs('Software',cells[3]),'company_characteristics':[],
        'stakeholders':[obs('Engineering',cells[2],['Chris'])] if 'Chris' in cells[2] else [],'limitations':'Synthetic fixture.'}
   print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'analysis_record':row})}}),flush=True)
   records.append(row)
   if mode=='analysis_interrupt' and i==1:
    print(json.dumps({'type':'error','message':'Usage limit reached after two classified records.'}),flush=True);sys.exit(1)
  obj={'records':records}
 elif task=='classify_compact':
  import subprocess
  configs=[args[i+1] for i,v in enumerate(args[:-1]) if v=='-c']
  command=json.loads(next(v.split('=',1)[1] for v in configs if v.startswith('mcp_servers.analysis_checkpoint.command=')))
  server_args=json.loads(next(v.split('=',1)[1] for v in configs if v.startswith('mcp_servers.analysis_checkpoint.args=')))
  child=subprocess.Popen([command,*server_args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
  cats=assign['categories'];bydim={v['dimension']:k for k,v in cats.items() if v['name'] not in ('Other','Unknown / insufficient evidence')}
  try:
   for start in range(0,len(assign['records']),5):
    records=[]
    for item in assign['records'][start:start+5]:
     cells=item['cells'];observations=[]
     for dim,col in ([('buying_situations',4),('company_category',3),('stakeholders',2),('selection_requirements',4),('company_characteristics',3)] if assign.get('taxonomy_first') else [('buying_situations',4),('company_category',3),('stakeholders',2)]):
      if dim not in bydim and not assign.get('taxonomy_first'):continue
      cat=bydim.get(dim)
      fallback='Other' if dim=='selection_requirements' else 'Unknown / insufficient evidence'
      if cat is None:cat=next(k for k,c in cats.items() if c['dimension']==dim and c['name']==fallback)
      unknown=cats[cat]['name']=='Unknown / insufficient evidence'
      obs={'cat':cat,'cell':col,'quote':'' if unknown else cells[col],'strength':'unclear' if unknown else 'explicit'}
      if assign.get('taxonomy_first'):obs.update(kind='uncertain' if unknown else 'descriptive',detail='Synthetic specific workflow requirement.')
      if dim=='stakeholders':obs.update(people=['Chris'],involvement='Implementation only.')
      observations.append(obs)
     records.append({'id':item['id'],'anonymous':False,'observations':observations})
    params={'name':'save_records','arguments':{'records':records}}
    print(json.dumps({'type':'item.started','item':{'type':'mcp_tool_call','server':'analysis_checkpoint','tool':'save_records'}}),flush=True)
    child.stdin.write(json.dumps({'jsonrpc':'2.0','id':start+1,'method':'tools/call','params':params})+'\n');child.stdin.flush()
    result=json.loads(child.stdout.readline())
    if result.get('result',{}).get('isError'):raise ValueError(result)
    print(json.dumps({'type':'item.completed','item':{'type':'mcp_tool_call','server':'analysis_checkpoint','tool':'save_records','result':result}}),flush=True)
    if mode=='compact_interrupt' and start==5:
     print(json.dumps({'type':'error','message':'Synthetic interrupted execution'}),flush=True);sys.exit(1)
   obj={'completed_ids':[r['id'] for r in assign['records']]}
  finally:
   child.kill();child.wait();child.stdin.close();child.stdout.close()
 elif task=='global_semantic_map':
  labels=assign['catalog']['labels']
  obj={'nodes':[{'id':'fixture_'+x['id'],'parent_id':'','name':x['label'],'definition':x['definition'],
       'distinction':'Synthetic fixture preserves different labels.','kind':'trigger' if assign['dimension']=='buying_situations' else 'descriptive','countable_function':True,'members':[x['id']]} for x in labels],
       'observation_overrides':[],'observation_annotations':[],'review_notes':'Complete synthetic global vocabulary.'}
 elif task=='global_synthesis_report':
  from fake_report import markdown
  obj={'markdown':markdown(assign)}
 elif task=='normalize_categories':
  grouped={}
  for item in assign['labels']:
   grouped.setdefault(item['label'],{'name':item['label'],'definition':item['definition'],'members':[]})['members'].append(item['id'])
  obj={'categories':list(grouped.values())}
 elif task=='resolve_company_profiles':obj={'decisions':[{'profile_id':p['profile_id'],'category':next(iter(p['candidates'])),'reason':'Synthetic fixture reconciliation.'} for p in assign['profiles']]}
 else:obj={'markdown':'### Evidence and interpretation\nSynthetic evidence; published frequency does not establish buying authority or commercial priority.'}
 if mode=='tool_use':print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'curl https://example.com'}}),flush=True)
elif 'Stage 1 response JSON schema:' in prompt:
 competitor=os.getenv('FAKE_COMPETITOR','Beta Software')
 obj={'product_understanding':{'summary':os.getenv('FAKE_PRODUCT','Synthetic integration product.'),'core_workflow':'Connect application workflows with external systems.',
      'capabilities':[{'name':'Workflow integration','description':'Synthetic source-supported integration capability.','sources':['https://example.com/product']}],
      'sources':['https://example.com/product'],'uncertainties':[]},
      'competitors':[{'name':competitor,'product':'Beta Platform' if competitor=='Beta Software' else competitor+' Platform','reason':'Same core workflow','sources':['https://beta.example.com/product'],'confidence':'confirmed'}]}
elif 'Stage 2 reconciliation response JSON schema:' in prompt:
 obj={'decisions':[{'id':c['case']['id'],'decision':'exclude' if c['case'].get('customer')=='Out of scope' else 'needs_review' if mode=='saved_needs_review' else 'retain',
                    'reason':'Synthetic saved evidence supports this scope decision.'} for c in assign['saved_cases']]}
 if mode=='tool_use':print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'curl https://example.com'}}),flush=True)
elif 'Stage 2 batch review response JSON schema:' in prompt:
 rows=[]
 for i,case in enumerate(assign['review_cases']):
  decision='excluded' if case['url'].endswith('/3') else 'unresolved' if case['url'].endswith('/4') else 'relevant'
  row={'id':case['id'],'decision':decision,'reason':'Synthetic review: '+decision,'evidence':'Synthetic saved source evidence.',
       'record':fixture_record(case) if decision=='relevant' else None,'contribution':'Synthetic distinct workflow evidence.'}
  if mode=='batch_wrong_identity' and i==1:row['id']='unassigned'
  if mode=='batch_empty_customer' and i==0:row['record']['customer']=''
  messages=[json.dumps({'source_capture':{'url':case['url'],'coverage':'excerpt','text':'Synthetic reusable evidence: a B2B application vendor required workflow integration.'}}),json.dumps({'case_result':row})]
  if mode=='combined_interrupt':messages=['\n'.join(messages)]
  if mode in ('envelope','envelope_interrupt'):
   messages=[json.dumps({'source_captures':[json.loads(messages[0])['source_capture']],'case_result':row})]
  if mode=='unrelated_failure' and i==0:
   print(json.dumps({'type':'item.completed','item':{'type':'web_search','action':{'type':'open','url':'https://unrelated.example.com/failure.pdf'}}}),flush=True)
  for text in messages:print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':text}}),flush=True)
  rows.append(row)
  if mode=='batch_budget' and i==1:
   for j in range(2):print(json.dumps({'type':'item.completed','item':{'type':'web_search','action':{'type':'open','url':'https://example.com/budget/'+str(j)}}}),flush=True)
  if mode=='actual_runtime_budget' and i==1:
   print(json.dumps({'type':'item.completed','item':{'type':'web_search','action':{'type':'other'},'results':[
     {'url':'https://example.com/budget/0','ref_id':'turn1view0','snippet':'Total lines: 300'},
     {'url':'https://example.com/budget/1','ref_id':'turn1view1','snippet':'Total lines: 100'}]}}),flush=True)
  if mode in ('batch_interrupt','combined_interrupt','envelope_interrupt') and i==1:
   print(json.dumps({'type':'error','message':'Usage limit reached after two saved cases.'}),flush=True);sys.exit(1)
 obj={'results':rows}
elif 'Stage 2 review response JSON schema:' in prompt:
 case=assign['review_case']
 decision='excluded' if case['url'].endswith('/3') else 'unresolved' if case['url'].endswith('/4') else 'relevant'
 obj={'decision':decision,'reason':'Synthetic review: '+decision,'evidence':'Synthetic source evidence for the scoped customer need.','record':fixture_record(case) if decision=='relevant' and not assign.get('saved_record') else None}
 if mode=='review_missing_record':obj['record']=None
 if mode=='review_wrong_identity' and obj['record']:obj['record']['source_url']='https://wrong.example.com/unassigned'
elif 'Stage 2 response JSON schema:' in prompt:
 count=(5 if mode=='multi_product' else 25) if mode in ('multi_product','multi_page_review') and assign['approved_provider']=='Beta Software' else int(os.getenv('FAKE_CASES','1'))
 offset=int(assign.get('cursor') or '0');limit=assign.get('max_cases',20)
 end=min(count,offset+limit)
 if mode=='oversized_discovery':end=offset+limit+1
 obj={'cases':[{'customer':'Acme','title':'Acme customer story','url':f'https://stories.example.com/acme/{i}',
                'decision':'relevant','reason':'Synthetic scoped customer problem.','evidence':'Synthetic title/category/summary evidence.'} for i in range(offset,end)],
      'has_more':end<count,'next_cursor':str(end) if end<count else ''}
 if mode=='stalled_cursor':obj.update(has_more=True,next_cursor=assign.get('cursor',''))
 if mode in ('completed_structured_cursor','conflicting_structured_cursor'):
  obj.update(has_more=False,next_cursor=json.dumps({'completed':'Synthetic listing and searches exhausted.','remaining_listing_paths':[] if mode=='completed_structured_cursor' else ['https://example.com/page/2'],'remaining_search_paths':[]}))
 if mode in ('multi_product','multi_page_review') and assign['approved_provider']=='Beta Software':
  for i,case in enumerate(obj['cases'],offset):
   case['decision']='excluded' if i==1 else 'needs_review' if 2<=i<=4 else 'relevant'
   if i==1:case.update(title='Unrelated email product story',reason='Email engagement is a separate business line.',evidence='Category: email engagement.')
 if mode=='missing_relevance':obj['cases'][0]['evidence']=''
 if assign.get('efficient_worker'):
  if assign.get('first_listing_entries'):
   listing='https://stories.example.com/customer-stories'
   for j,case in enumerate(obj['cases'],offset+1):case.update(listing_position=j,listing_url=listing,url_status='resolved')
   print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'source_capture':{'url':listing,'role':'listing','coverage':'excerpt','text':'Synthetic natural listing order.','continuation':{'kind':'offset' if obj['has_more'] else 'exhausted','target':obj['next_cursor'],'evidence':'Synthetic observed listing offset/ending.'},'order_verified':mode!='unverified_listing',
     'ordered_entries':[{'position':case['listing_position'],'url':case['url']} for case in obj['cases']]}})}}),flush=True)
   obj.update(order_verified=mode!='unverified_listing',listing_exhausted=not obj['has_more'])
   if end>=30:obj.update(has_more=False,next_cursor='')
  for case in obj['cases']:
   case.update(record=None,reading_depth='lightweight',contribution='')
   if mode in ('substantive_discovery','stream_only_discovery'):
    case.update(reading_depth='substantive',record=fixture_record(dict(case,provider=assign['approved_provider'])),contribution='Synthetic first-reading contribution.')
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'discovered_case':case})}}),flush=True)
   if mode=='unresolved_discovery':
    case.update(decision='unresolved',reading_depth='substantive',reason='Synthetic first access failed.',evidence='Synthetic timeout; do not retry.')
    print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'discovered_case':case})}}),flush=True)
  if mode=='stream_only_discovery':obj['cases']=[]
elif 'Stage 3 response JSON schema:' in prompt:
 obj={'records':[fixture_record(c) for c in assign['assigned_cases']]}
 if mode=='pdf_single_failure':
  for row in obj['records']:
   if row['source_url'].endswith('.pdf'):
    row.update(status='inaccessible',note='Synthetic first PDF attempt failed; no retry.',people='',company_profile='',buying_situation='')
    print(json.dumps({'type':'item.completed','item':{'type':'web_search','query':row['source_url'],'results':[]}}),flush=True)
 if mode=='missing_record':obj['records']=obj['records'][:-1]
 if mode=='duplicate_record':obj['records']+=obj['records'][:1]
 if mode=='inaccessible':
  for row in obj['records']:row.update(status='inaccessible',note='Synthetic fixture: source unavailable.',people='',company_profile='',buying_situation='')
 if assign.get('efficient_worker'):
  for i,row in enumerate(obj['records']):
   print(json.dumps({'type':'item.completed','item':{'type':'agent_message','text':json.dumps({'extracted_record':row})}}),flush=True)
   if mode=='extract_interrupt' and i==1:
    print(json.dumps({'type':'error','message':'Usage limit reached after two extracted cases.'}),flush=True);sys.exit(1)
else:
 task=prompt.split('TASK ASSIGNMENT (machine generated):\n')[1].split('\n\nRUNNER EXECUTION OVERRIDE:')[0]
 assign=json.loads(task)
 if 'COMPLETE final report' in prompt:
  analyses=assign['completed_analyses']
  obj={'markdown':'# Overview\nSynthetic test overview.\n\n# Company profiles\n'+analyses['5']['markdown']+'\n\n# People and stakeholders\n'+analyses['6']['markdown']+'\n\n# Buying situations\n'+analyses['4']['markdown']+'\n\n# Methods and sources\nOne synthetic profile; fixture only. No research.\n'+assign['finalized_google_sheet']['sheet']['url']}
 else:obj={'markdown':'## Synthetic fixture analysis\nOne synthetic profile; no real research.\n\n| Category | Profiles | Share |\n| --- | --- | --- |\n| Test fixture | 1 | 100% |\n'}
 if mode=='tool_use':print(json.dumps({'type':'item.completed','item':{'type':'command_execution','command':'curl https://example.com'}}),flush=True)
 if mode=='invalid':obj={'markdown':''}
if assign.get('compact_receipts'):
 field={'discover':'cases','review_batch':'results','extract_batch':'records'}.get(assign['task'])
 if field:
  refs=[]
  for ty,row in streamed:
   if field=='cases' and ty=='discovered_case':ref=row['url']
   elif field=='results' and ty=='case_result':ref=row['id']
   elif field=='records' and ty=='extracted_record':ref=next(c['id'] for c in assign['assigned_cases'] if c['url']==row['source_url'] and c['provider']==row['provider'])
   else:continue
   if ref not in refs:refs.append(ref)
   obj[field]=[value for value in obj[field] if value!=row]
  obj['completed_ids']=refs
out.parent.mkdir(parents=True,exist_ok=True)
out.write_text('{broken' if mode=='invalid_final_json' else json.dumps(obj))
print(json.dumps({'type':'turn.completed','usage':{'input_tokens':0,'output_tokens':0}}),flush=True)
